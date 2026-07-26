# -*- coding: utf-8 -*-
"""Real-time device enumeration via Frida process memory (not log files)."""
from __future__ import annotations

import json
import re
import time
from typing import Any

from midrop_cli.core.devices import DEVICE_LABELS, load_device_map
from midrop_cli.core.popup import pid_of

PROC_NAME = "XiaomiPcManager"
EXIT_OK = 0
EXIT_ENV = 2
EXIT_TIMEOUT = 3

_JS_TEMPLATE = r"""
"use strict";
var KNOWN = __KNOWN__;

function toPat(s) {
  var out = [];
  for (var i = 0; i < s.length; i++) {
    out.push(("0" + s.charCodeAt(i).toString(16)).slice(-2));
  }
  return out.join(" ");
}
function noiseId(hex) {
  if (/^20[0-9]{6}$/.test(hex)) return true;
  var n = parseInt(hex, 16) >>> 0;
  if (n < 0x1000000) return true;
  return false;
}
function readNearbyNames(addr) {
  var names = [];
  var seen = {};
  function add(n) {
    if (!n) return;
    n = String(n).split(String.fromCharCode(0)).join(" ").replace(/\s+/g, " ").trim();
    n = n.replace(/\s*device_type:.*$/i, "").trim();
    if (n.length < 5 || n.length > 80) return;
    if (n.indexOf("Xiaomi") < 0 && n.indexOf("MIX") < 0 && n.indexOf("Pad") < 0) return;
    if (n.indexOf("Window") >= 0) return;
    if (seen[n]) return;
    seen[n] = 1;
    names.push(n);
  }
  for (var d = -64; d <= 64; d += 2) {
    try { add(addr.add(d).readUtf16String(40)); } catch (e) {}
  }
  try {
    var base = addr.sub(100);
    var buf = new Uint8Array(base.readByteArray(240));
    var asc = "";
    for (var j = 0; j < buf.length; j++) {
      var c = buf[j];
      asc += c >= 0x20 && c < 0x7f ? String.fromCharCode(c) : " ";
    }
    var m = /([^\s|{}]{0,6}Xiaomi[ A-Za-z0-9.]{2,40})/.exec(asc);
    if (m) add(m[1]);
  } catch (e) {}
  return names;
}
function scanId(id, ranges) {
  var pat = toPat(id);
  var hits = 0;
  var names = {};
  for (var i = 0; i < ranges.length; i++) {
    var r = ranges[i];
    if (r.size > 40 * 1024 * 1024 || r.size < 8) continue;
    try {
      Memory.scanSync(r.base, r.size, pat).forEach(function (m) {
        hits++;
        if (hits > 50) return;
        readNearbyNames(m.address).forEach(function (n) { names[n] = 1; });
      });
    } catch (e) {}
  }
  return { hits: hits, names: Object.keys(names) };
}
var ranges = Process.enumerateRanges("r--");
var devices = [];
var seen = {};
KNOWN.forEach(function (k) {
  var id = String(k.id_hex).toUpperCase();
  if (seen[id]) return;
  var r = scanId(id, ranges);
  if (r.hits <= 0) return;
  seen[id] = 1;
  var label = r.names.length ? r.names[0] : (k.label || ("device_" + id));
  devices.push({
    id_hex: id,
    device_id: k.device_id,
    name: label,
    names: r.names,
    hits: r.hits,
    known: true
  });
});
devices.sort(function (a, b) { return (b.known - a.known) || (b.hits - a.hits); });
send({ type: "result", devices: devices });
"""


def _elapsed_ms(t0: float) -> int:
    return int((time.time() - t0) * 1000)


def _known_list(cfg_data: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    m = load_device_map(cfg_data)
    by_id: dict[int, dict[str, Any]] = {}
    for alias, did in m.items():
        did = int(did) & 0xFFFFFFFF
        if did not in by_id:
            by_id[did] = {
                "id_hex": f"{did:08X}",
                "device_id": did,
                "label": DEVICE_LABELS.get(did, alias),
            }
    return list(by_id.values())


def list_devices_live(
    timeout: float = 45.0,
    cfg_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    t0 = time.time()
    try:
        import frida
    except Exception as e:
        return {
            "ok": False,
            "action": "devices",
            "source": "live",
            "devices": [],
            "error": "environment",
            "message": f"frida not available: {e}",
            "elapsed_ms": _elapsed_ms(t0),
            "exit_code": EXIT_ENV,
        }

    pid = pid_of(PROC_NAME)
    if not pid:
        return {
            "ok": False,
            "action": "devices",
            "source": "live",
            "devices": [],
            "error": "environment",
            "message": f"{PROC_NAME} not running",
            "elapsed_ms": _elapsed_ms(t0),
            "exit_code": EXIT_ENV,
        }

    known = _known_list(cfg_data)
    js = _JS_TEMPLATE.replace("__KNOWN__", json.dumps(known, ensure_ascii=True))
    holder: dict[str, Any] = {}

    def on_message(message, data):
        if message["type"] == "send":
            p = message["payload"]
            if isinstance(p, dict) and p.get("type") == "result":
                holder["result"] = p

    try:
        session = frida.attach(pid)
        script = session.create_script(js)
        script.on("message", on_message)
        script.load()
        deadline = time.time() + max(10.0, float(timeout))
        while time.time() < deadline and "result" not in holder:
            time.sleep(0.2)
        try:
            session.detach()
        except Exception:
            pass
    except Exception as e:
        return {
            "ok": False,
            "action": "devices",
            "source": "live",
            "devices": [],
            "error": "environment",
            "message": f"live scan failed: {e}",
            "elapsed_ms": _elapsed_ms(t0),
            "exit_code": EXIT_ENV,
        }

    raw_list = list((holder.get("result") or {}).get("devices") or [])
    devices: list[dict[str, Any]] = []
    for d in raw_list:
        names = list(d.get("names") or [])
        did = d.get("device_id")
        # Prefer stable label for known ids; memory names are often log fragments.
        if isinstance(did, int) and did in DEVICE_LABELS:
            name = DEVICE_LABELS[did]
        else:
            name = d.get("name") or (names[0] if names else f"device_{d.get('id_hex')}")
            name = re.sub(r"\s*device_type:.*$", "", str(name), flags=re.I).strip()
            # drop junk path-like names
            if "Lyra/" in name or "\\" in name or name.endswith(" device"):
                name = names[0] if names else f"device_{d.get('id_hex')}"
                name = re.sub(r"\s*device_type:.*$", "", str(name), flags=re.I).strip()
        devices.append(
            {
                "name": name,
                "id_hex": d.get("id_hex"),
                "device_id": did,
                "names": names,
                "hits": d.get("hits"),
                "online": True,
            }
        )

    if not devices:
        return {
            "ok": False,
            "action": "devices",
            "source": "live",
            "devices": [],
            "error": "device_not_found",
            "message": "no known devices present in process memory",
            "elapsed_ms": _elapsed_ms(t0),
            "exit_code": EXIT_TIMEOUT,
        }

    return {
        "ok": True,
        "action": "devices",
        "source": "live",
        "devices": devices,
        "elapsed_ms": _elapsed_ms(t0),
        "exit_code": EXIT_OK,
    }
