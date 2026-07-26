# -*- coding: utf-8 -*-
"""
Real-time device enumeration via Frida daemon + on-demand snapshot.

Two strategies combined:

1. **Daemon** (``midrop daemon``): stays attached to XiaomiPcManager, hooks
   OnLyraDisplayedFeatureAdd / Removed to maintain an authoritative online
   set (device_id -> {name, types, last_seen}). Exposes a snapshot via a
   small file cache at ``%LOCALAPPDATA%\\midrop\\lyra_state.json``.
2. **CLI query**: reads that snapshot file if fresh; otherwise falls back
   to a one-shot Frida attach that captures the manager's own
   ``current lyra devices`` snapshot string right after toggling discovery.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from midrop_cli.config import config_dir
from midrop_cli.core.devices import DEVICE_LABELS as _CORE_LABELS
from midrop_cli.core.popup import pid_of

PROC_NAME = "XiaomiPcManager"

EXIT_OK = 0
EXIT_ENV = 2
EXIT_TIMEOUT = 3

STATE_FILE = "lyra_state.json"
STATE_FRESH_SECONDS = 30.0

DEVICE_LABELS = dict(_CORE_LABELS)


def state_path() -> Path:
    return config_dir() / STATE_FILE


# Snapshot script: capture a fresh 'current lyra devices' string.
# We toggle discovery to trigger OnLyraDisplayedFeatureAdd/Removed which
# print such strings to std::string temporaries that linger on the heap.
_SNAPSHOT_JS = r"""
"use strict";

function toPat(s) {
  var o = [];
  for (var i = 0; i < s.length; i++) o.push(("0" + s.charCodeAt(i).toString(16)).slice(-2));
  return o.join(" ");
}

function findMod() {
  var m = null;
  Process.enumerateModules().forEach(function (x) {
    if (x.name.toLowerCase() === "mismartsharedll.dll") m = x;
  });
  return m;
}

function toggleDiscovery(mod) {
  try {
    var expName = "?GetMiDropBusiness@midrop@@YAPEAVIMiDropBusiness@1@XZ";
    var getBiz = new NativeFunction(mod.getExportByName(expName), "pointer", []);
    var biz = getBiz();
    if (biz.isNull()) return;
    var vtbl = biz.readPointer();
    var sw = new NativeFunction(
      vtbl.add(8).readPointer(),
      "void",
      ["pointer", "bool", "bool"],
      "win64"
    );
    try { sw(biz, 0, 0); } catch (e) {}
    try { sw(biz, 1, 1); } catch (e) {}
  } catch (e) {}
}

function scanSnapshots() {
  var results = [];
  var frags = [":[1,", ":[2,", ":[3,", ":[5,", ":[1]", ":[2]", ":[3]", ":[5]", ":[1, ", ":[3, "];
  Process.enumerateRanges("rw-").forEach(function (r) {
    if (r.size > 8 * 1024 * 1024 || r.size < 16) return;
    frags.forEach(function (frag) {
      try {
        Memory.scanSync(r.base, r.size, toPat(frag)).forEach(function (m) {
          if (results.length > 100) return;
          try {
            var start = m.address;
            for (var b = 0; b < 200; b++) {
              if (start.sub(b).readU8() === 0x5b) { start = start.sub(b); break; }
            }
            var s = start.readAnsiString(400);
            if (s && /^\[[0-9A-F]{8}:\[/.test(s)) {
              var depth = 0, end = -1;
              for (var i = 0; i < s.length; i++) {
                var c = s.charAt(i);
                if (c === "[") depth++;
                else if (c === "]") {
                  depth--;
                  if (depth === 0) { end = i + 1; break; }
                }
              }
              if (end > 0) results.push(s.substring(0, end));
            }
          } catch (e) {}
        });
      } catch (e) {}
    });
  });
  var seen = {}, uniq = [];
  results.forEach(function (x) { if (!seen[x]) { seen[x] = 1; uniq.push(x); } });
  return uniq;
}

function nearestName(id_hex) {
  var pat = toPat(id_hex);
  var names = {};
  Process.enumerateRanges("r--").forEach(function (r) {
    if (r.size > 8 * 1024 * 1024 || r.size < 16) return;
    try {
      Memory.scanSync(r.base, r.size, pat).forEach(function (m) {
        try {
          for (var d = -160; d <= 160; d += 2) {
            try {
              var w = m.address.add(d).readUtf16String(48);
              if (!w) continue;
              w = w.trim();
              if (w.length > 3 && w.length < 60 &&
                  (w.indexOf("Xiaomi") >= 0 || w.indexOf("MIX") >= 0 || w.indexOf("Pad") >= 0)) {
                names[w] = (names[w] || 0) + 1;
                break;
              }
            } catch (e) {}
          }
        } catch (e) {}
      });
    } catch (e) {}
  });
  var arr = Object.keys(names).map(function (k) { return { name: k, hits: names[k] }; });
  arr.sort(function (a, b) { return b.hits - a.hits; });
  return arr.slice(0, 3).map(function (x) { return x.name; });
}

function main() {
  var mod = findMod();
  if (!mod) { send({ type: "error", msg: "MiSmartShareDLL.dll not loaded" }); return; }
  toggleDiscovery(mod);
  Thread.sleep(0.8);
  var snaps = scanSnapshots();
  toggleDiscovery(mod);
  Thread.sleep(0.5);
  var snaps2 = scanSnapshots();
  var all = snaps.concat(snaps2);
  var seen = {}, uniq = [];
  all.forEach(function (x) { if (!seen[x]) { seen[x] = 1; uniq.push(x); } });
  uniq.sort(function (a, b) { return b.length - a.length; });
  var chosen = uniq[0] || null;

  var devices = [];
  if (chosen) {
    var re = /([0-9A-F]{8}):\[([0-9,\s]*)\]/g;
    var mm;
    while ((mm = re.exec(chosen)) !== null) {
      var id_hex = mm[1];
      var types = mm[2].split(",")
        .map(function (x) { return x.trim(); })
        .filter(Boolean)
        .map(Number);
      var names = nearestName(id_hex);
      devices.push({
        id_hex: id_hex,
        device_id: parseInt(id_hex, 16),
        types: types,
        names: names
      });
    }
  }
  send({ type: "result", snapshots: uniq.slice(0, 5), chosen: chosen, devices: devices });
}

setImmediate(main);
"""


def _elapsed_ms(t0: float) -> int:
    return int((time.time() - t0) * 1000)


def _read_state_file(max_age: float = STATE_FRESH_SECONDS) -> dict[str, Any] | None:
    p = state_path()
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    ts = data.get("timestamp")
    if not isinstance(ts, (int, float)):
        return None
    if (time.time() - float(ts)) > max_age:
        return None
    return data


def _query_snapshot(timeout: float = 20.0) -> dict[str, Any]:
    """Single-shot Frida attach: force a snapshot and parse it."""
    t0 = time.time()
    try:
        import frida
    except Exception as e:
        return {"ok": False, "error": "environment", "message": f"frida not available: {e}"}

    pid = pid_of(PROC_NAME)
    if not pid:
        return {"ok": False, "error": "environment", "message": f"{PROC_NAME} not running"}

    result: dict[str, Any] = {}

    def on_message(message, data):
        if message["type"] == "send":
            p = message["payload"]
            if isinstance(p, dict) and p.get("type") == "result":
                result["result"] = p

    session = None
    try:
        session = frida.attach(pid)
        script = session.create_script(_SNAPSHOT_JS)
        script.on("message", on_message)
        script.load()
        deadline = time.time() + max(3.0, float(timeout))
        while time.time() < deadline and "result" not in result:
            time.sleep(0.2)
    except Exception as e:
        if session:
            try:
                session.detach()
            except Exception:
                pass
        return {"ok": False, "error": "environment", "message": f"frida attach failed: {e}"}
    finally:
        if session:
            try:
                session.detach()
            except Exception:
                pass

    raw = result.get("result")
    if not raw:
        return {
            "ok": False,
            "error": "timeout",
            "message": f"no snapshot within {timeout}s",
            "elapsed_ms": _elapsed_ms(t0),
        }
    return {"ok": True, "raw": raw, "elapsed_ms": _elapsed_ms(t0)}


def _shape(raw_devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for d in raw_devices:
        did = int(d.get("device_id") or 0)
        id_hex = d.get("id_hex") or ""
        types = list(d.get("types") or [])
        names = list(d.get("names") or [])
        label = DEVICE_LABELS.get(did) or (names[0] if names else f"device_{id_hex}")
        label = re.sub(r"^name[:\s]*", "", label, flags=re.I).strip()
        out.append(
            {
                "name": label,
                "id_hex": id_hex,
                "device_id": did,
                "types": types,
                "names": names,
            }
        )
    out.sort(key=lambda x: (x["device_id"] not in DEVICE_LABELS, x["device_id"]))
    return out


def list_devices_live(timeout: float = 30.0) -> dict[str, Any]:
    """Live device list. Prefers daemon state file; falls back to on-demand snapshot."""
    t0 = time.time()

    state = _read_state_file()
    if state:
        devices_in = state.get("devices") or []
        shaped: list[dict[str, Any]] = []
        for d in devices_in:
            did = int(d.get("device_id") or 0)
            id_hex = d.get("id_hex") or ""
            shaped.append(
                {
                    "name": d.get("name") or DEVICE_LABELS.get(did) or f"device_{id_hex}",
                    "id_hex": id_hex,
                    "device_id": did,
                    "types": list(d.get("types") or []),
                    "last_seen": d.get("last_seen"),
                }
            )
        shaped.sort(key=lambda x: (x["device_id"] not in DEVICE_LABELS, x["device_id"]))
        return {
            "ok": True,
            "action": "devices",
            "source": "daemon",
            "state_age_sec": round(time.time() - float(state.get("timestamp") or 0), 3),
            "devices": shaped,
            "elapsed_ms": _elapsed_ms(t0),
            "exit_code": EXIT_OK,
        }

    r = _query_snapshot(timeout=timeout)
    if not r.get("ok"):
        return {
            "ok": False,
            "action": "devices",
            "source": "snapshot",
            "devices": [],
            "error": r.get("error") or "environment",
            "message": r.get("message") or "snapshot failed",
            "elapsed_ms": _elapsed_ms(t0),
            "exit_code": EXIT_ENV if r.get("error") == "environment" else EXIT_TIMEOUT,
        }

    raw = r["raw"]
    devices = _shape(raw.get("devices") or [])
    if not devices:
        return {
            "ok": False,
            "action": "devices",
            "source": "snapshot",
            "devices": [],
            "error": "device_not_found",
            "message": (
                "no live devices in current 'current lyra devices' snapshot; "
                "start `midrop daemon` for continuous tracking"
            ),
            "snapshots": raw.get("snapshots") or [],
            "elapsed_ms": _elapsed_ms(t0),
            "exit_code": EXIT_TIMEOUT,
        }

    return {
        "ok": True,
        "action": "devices",
        "source": "snapshot",
        "snapshot": raw.get("chosen"),
        "devices": devices,
        "elapsed_ms": _elapsed_ms(t0),
        "exit_code": EXIT_OK,
    }
