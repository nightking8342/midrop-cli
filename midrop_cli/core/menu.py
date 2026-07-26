# -*- coding: utf-8 -*-
"""
Menu-window MiDrop send: FileMapping + Launch + Frida UI-thread CreateSend.

Staged fallback for ``core/silent.py``. Reaches the manager's UI thread by
triggering the real context-menu flow and hooking ``OpenFromMenuWindow``, so
the device picker **does flash on screen** — it was called ``noui`` back when
"no UI" meant "we never click the picker", which stopped being a useful
distinction once silent removed the window entirely.

Prefer silent. Use this only when silent breaks (e.g. the manager changes how
its UI thread pumps messages).

Requires: frida package, XiaomiPcManager running, version-matched RVAs.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from typing import Any

from midrop_cli.core.devices import resolve_device_id
from midrop_cli.core.launch import trigger_dropfile
from midrop_cli.core.mapping import hold_mapping
from midrop_cli.core.popup import pid_of

NOTE = "PC 侧已发起（menu）；若手机需确认接收请在手机上同意"

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_ENV = 2
EXIT_TIMEOUT = 3
EXIT_CLICK = 4

# XiaomiPCManager 5.5.0.18 / MiSmartShareDLL.dll — re-calibrate after upgrade
CREATE_SEND_RVA = 0x1465F0
OPEN_MENU_RVA = 0x148260
GET_BIZ = "?GetMiDropBusiness@midrop@@YAPEAVIMiDropBusiness@1@XZ"
PROC_NAME = "XiaomiPcManager"

JS = r"""
"use strict";
var CREATE_RVA = __CREATE_RVA__;
var OPEN_RVA = __OPEN_RVA__;
var DEVICE_ID = __DEVICE_ID__;
var FILE_PATH = __FILE_PATH__;
var GET_BIZ = __GET_BIZ__;

function zalloc(n) {
  var p = Memory.alloc(n);
  for (var i = 0; i < n; i++) p.add(i).writeU8(0);
  return p;
}

function allocWString(str) {
  var n = str.length;
  var mem = zalloc(32);
  if (n === 0) {
    mem.add(16).writeU64(0);
    mem.add(24).writeU64(7);
    return { obj: mem, pin: null };
  }
  if (n < 8) {
    mem.writeUtf16String(str);
    mem.add(16).writeU64(n);
    mem.add(24).writeU64(7);
    return { obj: mem, pin: null };
  }
  var heap = Memory.alloc((n + 1) * 2);
  heap.writeUtf16String(str);
  mem.writePointer(heap);
  mem.add(16).writeU64(n);
  var cap = n < 8 ? 8 : n;
  if (cap < 31) cap = 31;
  mem.add(24).writeU64(cap);
  return { obj: mem, pin: heap };
}

function allocListOne(str) {
  var listObj = zalloc(16);
  var head = zalloc(48);
  var node = zalloc(48);
  head.writePointer(node);
  head.add(8).writePointer(node);
  node.writePointer(head);
  node.add(8).writePointer(head);
  var ws = allocWString(str);
  Memory.copy(node.add(16), ws.obj, 32);
  listObj.writePointer(head);
  listObj.add(8).writeU64(1);
  return { list: listObj, pins: [head, node, ws.obj, ws.pin].filter(Boolean) };
}

function readPathFromList(listPtr) {
  try {
    var head = listPtr.readPointer();
    var node = head.readPointer();
    var w = node.add(16);
    var sz = w.add(16).readU64().toNumber();
    var cap = w.add(24).readU64().toNumber();
    var dp = cap < 8 ? w : w.readPointer();
    return {
      size: listPtr.add(8).readU64().toNumber(),
      path: dp.readUtf16String(sz),
      w_size: sz,
      w_cap: cap
    };
  } catch (e) {
    return { err: String(e) };
  }
}

function findMod() {
  var mod = null;
  Process.enumerateModules().forEach(function (m) {
    if (m.name.toLowerCase() === "mismartsharedll.dll") mod = m;
  });
  return mod;
}

function getThis(mod) {
  try {
    var exp = mod.getExportByName(GET_BIZ);
    var fn = new NativeFunction(exp, "pointer", []);
    return fn();
  } catch (e) {
    send({ type: "error", msg: "GetMiDropBusiness: " + e });
    return NULL;
  }
}

var invoked = false;

function doCreateSend(mod) {
  if (invoked) return;
  invoked = true;
  var thiz = getThis(mod);
  if (thiz.isNull()) {
    send({ type: "error", msg: "null this from GetMiDropBusiness" });
    return;
  }
  var built = allocListOne(FILE_PATH);
  var parent = allocWString("");
  globalThis.__pins = built.pins.concat([parent.obj, parent.pin].filter(Boolean));
  var chk = readPathFromList(built.list);
  send({ type: "log", msg: "list_check " + JSON.stringify(chk) });
  if (chk.path && chk.path !== FILE_PATH) {
    send({ type: "error", msg: "path layout mismatch: " + chk.path });
    return;
  }
  var fnAddr = mod.base.add(CREATE_RVA);
  var fn = new NativeFunction(
    fnAddr,
    "void",
    ["pointer", "uint32", "pointer", "pointer"],
    "win64"
  );
  send({
    type: "log",
    msg: "CreateSend this=" + thiz + " dev=" + DEVICE_ID + " path=" + FILE_PATH
  });
  try {
    fn(thiz, DEVICE_ID, built.list, parent.obj);
    // Some builds throw system error after successful schedule; treat as ok if no crash path
    send({ type: "ok", msg: "CreateSend returned" });
  } catch (e) {
    // Live tests: throw can still mean OnTaskSucceed — report soft_ok
    send({ type: "soft_ok", msg: "CreateSend threw after invoke: " + e });
  }
}

function main() {
  var mod = findMod();
  if (!mod) {
    send({ type: "error", msg: "MiSmartShareDLL.dll not loaded" });
    return;
  }
  var openAddr = mod.base.add(OPEN_RVA);
  send({ type: "log", msg: "OpenFromMenuWindow @ " + openAddr });
  send({ type: "log", msg: "CreateSend @ " + mod.base.add(CREATE_RVA) });
  Interceptor.attach(openAddr, {
    onEnter: function () {
      send({ type: "log", msg: "OpenFromMenuWindow ENTER" });
    },
    onLeave: function () {
      send({ type: "log", msg: "OpenFromMenuWindow LEAVE — CreateSend on UI thread" });
      try {
        doCreateSend(mod);
      } catch (e) {
        send({ type: "error", msg: "onLeave: " + e });
      }
    }
  });
  send({ type: "ready" });
}

setImmediate(main);
"""


def _elapsed_ms(t0: float) -> int:
    return int((time.time() - t0) * 1000)


def _build_js(path: str, device_id: int) -> str:
    return (
        JS.replace("__CREATE_RVA__", hex(CREATE_SEND_RVA))
        .replace("__OPEN_RVA__", hex(OPEN_MENU_RVA))
        .replace("__DEVICE_ID__", str(int(device_id) & 0xFFFFFFFF))
        .replace("__FILE_PATH__", json.dumps(path))
        .replace("__GET_BIZ__", json.dumps(GET_BIZ))
    )


def frida_available() -> tuple[bool, str]:
    try:
        import frida  # noqa: F401

        return True, f"frida {frida.__version__}"
    except Exception as e:
        return False, str(e)


def send_file_menu(
    path: str,
    device_query: str,
    timeout: float = 25.0,
    hold: float = 8.0,
    launch_path: str = "",
    cfg_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Send via Frida UI-thread CreateSend. Flashes the picker; never clicks it."""
    t0 = time.time()
    path = os.path.abspath(path)
    base: dict[str, Any] = {
        "action": "send",
        "mode": "menu",
        "file": path,
        "device_query": device_query,
        "popup_found": False,
        "clicked": False,
    }

    ok_frida, frida_detail = frida_available()
    if not ok_frida:
        return {
            **base,
            "ok": False,
            "error": "environment",
            "message": f"frida not available: {frida_detail}",
            "elapsed_ms": _elapsed_ms(t0),
            "exit_code": EXIT_ENV,
        }

    import frida

    pid = pid_of(PROC_NAME)
    if not pid:
        return {
            **base,
            "ok": False,
            "error": "environment",
            "message": f"{PROC_NAME} not running",
            "elapsed_ms": _elapsed_ms(t0),
            "exit_code": EXIT_ENV,
        }

    try:
        device_id, label = resolve_device_id(device_query, cfg_data)
    except ValueError as e:
        return {
            **base,
            "ok": False,
            "error": "device_not_found",
            "message": str(e),
            "elapsed_ms": _elapsed_ms(t0),
            "exit_code": EXIT_TIMEOUT,
        }

    base["device_id"] = device_id
    base["device_hex"] = f"0x{device_id:X}"
    base["device_matched"] = label

    if not launch_path or not os.path.isfile(launch_path):
        return {
            **base,
            "ok": False,
            "error": "environment",
            "message": f"Launch.exe not found: {launch_path}",
            "elapsed_ms": _elapsed_ms(t0),
            "exit_code": EXIT_ENV,
        }

    done: dict[str, Any] = {"ok": False, "soft_ok": False, "err": None, "logs": []}

    def on_message(message, data):
        if message["type"] != "send":
            return
        p = message["payload"]
        if not isinstance(p, dict):
            return
        t = p.get("type")
        if t == "log":
            done["logs"].append(str(p.get("msg", "")))
        elif t == "ok":
            done["ok"] = True
        elif t == "soft_ok":
            done["soft_ok"] = True
            done["logs"].append(str(p.get("msg", "")))
        elif t == "error":
            done["err"] = p.get("msg")
        elif t == "ready":
            done["logs"].append("ready")

    try:
        session = frida.attach(pid)
    except Exception as e:
        return {
            **base,
            "ok": False,
            "error": "environment",
            "message": f"frida attach failed: {e}",
            "elapsed_ms": _elapsed_ms(t0),
            "exit_code": EXIT_ENV,
        }

    try:
        script = session.create_script(_build_js(path, device_id))
        script.on("message", on_message)
        script.load()
        # wait ready
        deadline_ready = time.time() + 5
        while time.time() < deadline_ready and "ready" not in done["logs"]:
            if done["err"]:
                break
            time.sleep(0.05)

        if done["err"] and not done["ok"]:
            return {
                **base,
                "ok": False,
                "error": "environment",
                "message": str(done["err"]),
                "elapsed_ms": _elapsed_ms(t0),
                "exit_code": EXIT_ENV,
            }

        with hold_mapping(path):
            try:
                trigger_dropfile(launch_path)
            except FileNotFoundError:
                return {
                    **base,
                    "ok": False,
                    "error": "environment",
                    "message": f"Launch.exe not found: {launch_path}",
                    "elapsed_ms": _elapsed_ms(t0),
                    "exit_code": EXIT_ENV,
                }

            wait_s = max(5.0, float(timeout))
            deadline = time.time() + wait_s
            while time.time() < deadline:
                if done["ok"] or done["soft_ok"] or done["err"]:
                    break
                time.sleep(0.2)

            # hold mapping for transfer handshake
            time.sleep(max(0.0, float(hold)))
    except Exception as e:
        return {
            **base,
            "ok": False,
            "error": "environment",
            "message": f"menu send failed: {e}",
            "elapsed_ms": _elapsed_ms(t0),
            "exit_code": EXIT_ENV,
        }
    finally:
        try:
            session.detach()
        except Exception:
            pass

    if done["ok"] or done["soft_ok"]:
        return {
            **base,
            "ok": True,
            "popup_found": True,
            "clicked": False,
            "menu_invoked": True,
            "elapsed_ms": _elapsed_ms(t0),
            "note": NOTE,
            "exit_code": EXIT_OK,
            "logs": done["logs"][-8:],
        }

    if done["err"]:
        return {
            **base,
            "ok": False,
            "error": "click_failed",
            "message": str(done["err"]),
            "elapsed_ms": _elapsed_ms(t0),
            "exit_code": EXIT_CLICK,
            "logs": done["logs"][-8:],
        }

    return {
        **base,
        "ok": False,
        "error": "popup_timeout",
        "message": f"OpenFromMenuWindow/CreateSend not completed within {timeout}s",
        "elapsed_ms": _elapsed_ms(t0),
        "exit_code": EXIT_TIMEOUT,
        "logs": done["logs"][-8:],
    }
