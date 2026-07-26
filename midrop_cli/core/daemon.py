# -*- coding: utf-8 -*-
"""
midrop daemon: stays attached to XiaomiPcManager and maintains the real
online Lyra device set by hooking OnLyraDisplayedFeatureAdd / Removed.

State is written to %LOCALAPPDATA%\\midrop\\lyra_state.json for `midrop
devices --source live` to consume.
"""
from __future__ import annotations

import json
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any

from midrop_cli.config import config_dir
from midrop_cli.core.live_devices import (
    DEVICE_LABELS,
    STATE_FILE,
    _SNAPSHOT_JS as SNAPSHOT_JS,
    _shape as shape_devices,
)
from midrop_cli.core.popup import pid_of


LYRA_LOG = r"C:\ProgramData\MI\AIoT\Log\smart_share_log.txt"


def _initial_from_log() -> list[dict[str, Any]] | None:
    """Read latest 'current lyra devices [HEX:[types...], ...]' from smart_share_log."""
    try:
        size = Path(LYRA_LOG).stat().st_size
        with open(LYRA_LOG, "rb") as f:
            f.seek(max(0, size - 400_000))
            data = f.read().decode("utf-8", "replace")
    except OSError:
        return None
    import re as _re

    pat = _re.compile(r"current lyra devices \[([^\]]*(?:\][^\]]*)*)\]")
    # last line matching
    last = None
    for line in data.splitlines():
        if "current lyra devices" in line:
            last = line
    if not last:
        return None
    # extract everything between the FIRST '[' after 'devices' and the matching final ']'
    idx = last.find("current lyra devices ")
    if idx < 0:
        return None
    tail = last[idx + len("current lyra devices ") :]
    if not tail.startswith("["):
        return None
    depth = 0
    end = -1
    for i, c in enumerate(tail):
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end < 0:
        return None
    body = tail[1 : end - 1]
    # body like "347FBBC5:[1, 3, 5], D16E4A0F:[1, 2, 3]"
    entries = []
    for m in _re.finditer(r"([0-9A-Fa-f]{8}):\[([0-9,\s]*)\]", body):
        id_hex = m.group(1).upper()
        types = [int(x.strip()) for x in m.group(2).split(",") if x.strip()]
        entries.append(
            {
                "id_hex": id_hex,
                "device_id": int(id_hex, 16),
                "types": types,
                "names": [],
            }
        )
    return entries

PROC_NAME = "XiaomiPcManager"

# Hook script: sits on the two DeviceMgr::OnLyraDisplayedFeatureAdd/Removed
# entries (via .pdata) and forwards {kind,id,arg2,arg3} to the daemon.
_HOOK_JS = r"""
"use strict";

var ADD_RVA = 0x37d830;
var REMOVED_RVA = 0x37e5e0;

function findMod() {
  var m = null;
  Process.enumerateModules().forEach(function (x) {
    if (x.name.toLowerCase() === "mismartsharedll.dll") m = x;
  });
  return m;
}

function readStdString(p) {
  try {
    if (p.isNull()) return null;
    var size = p.add(16).readU64().toNumber();
    var cap = p.add(24).readU64().toNumber();
    if (size < 0 || size > 200 || cap > 100000) return null;
    var dp = cap < 16 ? p : p.readPointer();
    return dp.readUtf8String(size);
  } catch (e) {
    return null;
  }
}

function main() {
  var mod = findMod();
  if (!mod) { send({ type: "error", msg: "MiSmartShareDLL.dll not loaded" }); return; }

  [
    [ADD_RVA, "add"],
    [REMOVED_RVA, "remove"]
  ].forEach(function (pair) {
    var rva = pair[0], kind = pair[1];
    Interceptor.attach(mod.base.add(rva), {
      onEnter: function (args) {
        // rcx=DeviceMgr this, rdx=std::string id (8 hex), r8=device_type int,
        // r9=feature_type int (5 = midrop)
        var id = readStdString(args[1]);
        var type_i = args[2].toInt32();
        var feature_i = args[3].toInt32();
        send({
          type: "event",
          kind: kind,
          id: id,
          device_type: type_i,
          feature: feature_i
        });
      }
    });
  });

  send({ type: "ready", base: String(mod.base) });
}

setImmediate(main);
"""


class DaemonState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        # id_hex -> dict
        self.devices: dict[str, dict[str, Any]] = {}
        self.last_write = 0.0

    def apply_snapshot(self, devices: list[dict[str, Any]]) -> None:
        with self.lock:
            self.devices.clear()
            now = time.time()
            for d in devices:
                id_hex = str(d.get("id_hex") or "").upper()
                if not id_hex:
                    continue
                did = int(d.get("device_id") or 0)
                self.devices[id_hex] = {
                    "id_hex": id_hex,
                    "device_id": did,
                    "types": sorted(set(d.get("types") or [])),
                    "name": d.get("name") or DEVICE_LABELS.get(did) or f"device_{id_hex}",
                    "last_seen": now,
                }

    def add_feature(self, id_hex: str, device_type: int, feature: int) -> None:
        id_hex = id_hex.upper()
        with self.lock:
            entry = self.devices.get(id_hex)
            now = time.time()
            did = int(id_hex, 16)
            if not entry:
                entry = {
                    "id_hex": id_hex,
                    "device_id": did,
                    "types": [],
                    "name": DEVICE_LABELS.get(did) or f"device_{id_hex}",
                    "last_seen": now,
                }
                self.devices[id_hex] = entry
            types = set(entry.get("types") or [])
            types.add(int(feature))
            entry["types"] = sorted(types)
            entry["device_type"] = int(device_type)
            entry["last_seen"] = now

    def remove_feature(self, id_hex: str, device_type: int, feature: int) -> None:
        id_hex = id_hex.upper()
        with self.lock:
            entry = self.devices.get(id_hex)
            if not entry:
                return
            types = set(entry.get("types") or [])
            types.discard(int(feature))
            if types:
                entry["types"] = sorted(types)
                entry["last_seen"] = time.time()
            else:
                # last feature gone -> device offline
                self.devices.pop(id_hex, None)

    def dump(self) -> dict[str, Any]:
        with self.lock:
            return {
                "timestamp": time.time(),
                "pid": None,
                "devices": list(self.devices.values()),
            }


def _state_path() -> Path:
    return config_dir() / STATE_FILE


def _write_state(state: DaemonState, pid: int) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = state.dump()
    data["pid"] = pid
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def run_daemon(refresh_every: float = 5.0, initial_snapshot: bool = True) -> int:
    """Run until signalled. Returns exit code."""
    try:
        import frida
    except Exception as e:
        print(f"frida not available: {e}", file=sys.stderr)
        return 2

    pid = pid_of(PROC_NAME)
    if not pid:
        print(f"{PROC_NAME} not running", file=sys.stderr)
        return 2

    state = DaemonState()
    stop = threading.Event()

    def handle_signal(signum, frame):
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, handle_signal)
        except (ValueError, AttributeError):
            pass

    session = frida.attach(pid)

    def on_msg(message, data):
        if message["type"] != "send":
            return
        p = message["payload"]
        if not isinstance(p, dict):
            return
        t = p.get("type")
        if t == "event":
            id_ = (p.get("id") or "").upper()
            if not id_:
                return
            if p.get("kind") == "add":
                state.add_feature(id_, int(p.get("device_type", 0)), int(p.get("feature", 0)))
            elif p.get("kind") == "remove":
                state.remove_feature(id_, int(p.get("device_type", 0)), int(p.get("feature", 0)))
            _write_state(state, pid)
            print(f"[daemon] event {p.get('kind')} id={id_} feature={p.get('feature')} type={p.get('device_type')} -> {len(state.devices)} online", flush=True)
        elif t == "ready":
            print(f"[daemon] attached pid={pid} base={p.get('base')}", flush=True)

    script = session.create_script(_HOOK_JS)
    script.on("message", on_msg)
    script.load()

    if initial_snapshot:
        # 1) Prefer smart_share_log last snapshot (authoritative & recent)
        seeded = False
        entries = _initial_from_log()
        if entries:
            state.apply_snapshot(shape_devices(entries))
            _write_state(state, pid)
            print(f"[daemon] initial from log: {len(entries)} device(s)", flush=True)
            seeded = True

        # 2) Fallback: try Frida snapshot script (may find residual heap strings)
        if not seeded:
            try:
                snap_script = session.create_script(SNAPSHOT_JS)
                snap_result: dict[str, Any] = {}

                def snap_on_msg(message, data):
                    if message["type"] != "send":
                        return
                    p = message["payload"]
                    if isinstance(p, dict) and p.get("type") == "result":
                        snap_result["r"] = p

                snap_script.on("message", snap_on_msg)
                snap_script.load()
                deadline = time.time() + 15
                while time.time() < deadline and "r" not in snap_result:
                    time.sleep(0.2)
                r = snap_result.get("r") or {}
                devices = shape_devices(r.get("devices") or [])
                if devices:
                    state.apply_snapshot(devices)
                    _write_state(state, pid)
                    print(f"[daemon] initial snapshot (heap): {len(devices)} device(s)", flush=True)
                snap_script.unload()
            except Exception as e:
                print(f"[daemon] initial snapshot failed: {e}", flush=True)

        if not state.devices:
            # ensure state file exists even if empty
            _write_state(state, pid)

    print(f"[daemon] running, state file: {_state_path()}", flush=True)
    last_beat = time.time()
    try:
        while not stop.wait(0.5):
            # keepalive: rewrite state so consumers see fresh timestamp
            if time.time() - last_beat >= max(1.0, float(refresh_every)):
                _write_state(state, pid)
                last_beat = time.time()
    finally:
        try:
            session.detach()
        except Exception:
            pass
        # final write with fresh timestamp
        try:
            _write_state(state, pid)
        except Exception:
            pass
        print("[daemon] stopped", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(run_daemon())
