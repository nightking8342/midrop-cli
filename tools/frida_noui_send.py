# -*- coding: utf-8 -*-
"""
No-UI MiDrop send PoC:
  1) Write FileMapping + Launch.exe (open menu path, no click)
  2) Frida: on OpenFromMenuWindow return (UI thread), call HandleCreateSendTask

Usage:
  python frida_noui_send.py <file> [Fold|Pad|0xHEX]
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes

import frida

CREATE_SEND_RVA = 0x1465F0
OPEN_MENU_RVA = 0x148260
GET_BIZ = "?GetMiDropBusiness@midrop@@YAPEAVIMiDropBusiness@1@XZ"
LAUNCH = r"C:\Program Files\MI\XiaomiPCManager\Launch.exe"
MAP_NAME = r"Local\MiDropFileMappingObject"

DEVICE_ALIASES = {
    "fold": 0xD16E4A0F,
    "phone": 0xD16E4A0F,
    "mix": 0xD16E4A0F,
    "pad": 0x347FBBC5,
    "tablet": 0x347FBBC5,
}

_k = ctypes.WinDLL("kernel32", use_last_error=True)
_k.CreateFileMappingW.restype = wintypes.HANDLE
_k.CreateFileMappingW.argtypes = [
    wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
    wintypes.DWORD, wintypes.DWORD, wintypes.LPCWSTR,
]
_k.MapViewOfFile.restype = wintypes.LPVOID
_k.MapViewOfFile.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
    wintypes.DWORD, ctypes.c_size_t,
]


def parse_device(s: str) -> int:
    k = s.strip().lower()
    if k in DEVICE_ALIASES:
        return DEVICE_ALIASES[k]
    return int(k, 0)


def get_pid() -> int:
    out = subprocess.check_output(
        ["powershell", "-NoProfile", "-Command",
         "(Get-Process XiaomiPcManager | Select-Object -First 1).Id"],
        text=True,
    ).strip()
    return int(out)


def write_mapping(path: str):
    wide = path + "\x00"
    nb = len(wide) * 2
    h = _k.CreateFileMappingW(ctypes.c_void_p(-1).value, None, 0x04, 0, nb, MAP_NAME)
    if not h:
        raise OSError(f"CreateFileMappingW {ctypes.get_last_error()}")
    v = _k.MapViewOfFile(h, 0xF001F, 0, 0, nb)
    if not v:
        raise OSError(f"MapViewOfFile {ctypes.get_last_error()}")
    ctypes.memmove(v, wide.encode("utf-16-le"), nb)
    return h, v


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

// MSVC x64 wstring: 32 bytes. Empty: size=0, cap=7. Long: heap ptr, size, cap>=8.
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
  // match runtime style: capacity >= size, typically >= 8
  var cap = n;
  if (cap < 8) cap = 8;
  // bump to look like real (layout_ok used 31 for size 28)
  if (cap < 31) cap = 31;
  mem.add(24).writeU64(cap);
  return { obj: mem, pin: heap };
}

// list with one wstring — layout from live capture
function allocListOne(str) {
  var listObj = zalloc(16);
  var head = zalloc(48); // sentinel
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
    return { size: listPtr.add(8).readU64().toNumber(), path: dp.readUtf16String(sz), w_size: sz, w_cap: cap };
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
    send({ type: "error", msg: "null this" });
    return;
  }
  var built = allocListOne(FILE_PATH);
  var parent = allocWString("");
  globalThis.__pins = built.pins.concat([parent.obj, parent.pin].filter(Boolean));
  var chk = readPathFromList(built.list);
  send({ type: "log", msg: "list check " + JSON.stringify(chk) });

  var fnAddr = mod.base.add(CREATE_RVA);
  var fn = new NativeFunction(fnAddr, "void", ["pointer", "uint32", "pointer", "pointer"], "win64");
  send({
    type: "log",
    msg: "UI-thread invoke CreateSend this=" + thiz + " dev=" + DEVICE_ID + " path=" + FILE_PATH
  });
  try {
    fn(thiz, DEVICE_ID, built.list, parent.obj);
    send({ type: "ok", msg: "CreateSend returned" });
  } catch (e) {
    send({ type: "error", msg: "CreateSend threw: " + e });
  }
}

function main() {
  var mod = findMod();
  if (!mod) {
    send({ type: "error", msg: "dll not loaded" });
    return;
  }
  var openAddr = mod.base.add(OPEN_RVA);
  send({ type: "log", msg: "OpenFromMenuWindow @ " + openAddr });
  send({ type: "log", msg: "CreateSend @ " + mod.base.add(CREATE_RVA) });

  Interceptor.attach(openAddr, {
    onEnter: function () {
      send({ type: "log", msg: "OpenFromMenuWindow ENTER" });
    },
    onLeave: function (retval) {
      send({ type: "log", msg: "OpenFromMenuWindow LEAVE — invoking CreateSend on UI thread" });
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


def build_js(path: str, device_id: int) -> str:
    return (
        JS.replace("__CREATE_RVA__", hex(CREATE_SEND_RVA))
        .replace("__OPEN_RVA__", hex(OPEN_MENU_RVA))
        .replace("__DEVICE_ID__", str(int(device_id)))
        .replace("__FILE_PATH__", json.dumps(path))
        .replace("__GET_BIZ__", json.dumps(GET_BIZ))
    )


def safe_print(x):
    s = str(x)
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    print(s.encode(enc, "replace").decode(enc, "replace"), flush=True)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    path = os.path.abspath(sys.argv[1])
    if not os.path.isfile(path):
        print("[x] missing file", path)
        return 1
    device_id = parse_device(sys.argv[2] if len(sys.argv) > 2 else "Fold")
    pid = get_pid()
    safe_print(f"[*] pid={pid} file={path} device=0x{device_id:X}")

    session = frida.attach(pid)
    done = {"ok": False, "err": None}

    def on_message(message, data):
        if message["type"] == "send":
            p = message["payload"]
            safe_print(f"[js] {p}")
            if isinstance(p, dict):
                if p.get("type") == "ok":
                    done["ok"] = True
                if p.get("type") == "error":
                    done["err"] = p.get("msg")
        else:
            safe_print(message)

    script = session.create_script(build_js(path, device_id))
    script.on("message", on_message)
    script.load()

    # wait ready
    time.sleep(1)

    # Trigger menu path without UIA click
    refs = write_mapping(path)
    subprocess.Popen([LAUNCH, "--contextmenu_dropfile=1"])
    safe_print("[*] triggered Launch --contextmenu_dropfile=1")

    t0 = time.time()
    while time.time() - t0 < 25:
        if done["ok"] or done["err"]:
            break
        time.sleep(0.3)

    # hold mapping for transfer
    time.sleep(10)
    try:
        session.detach()
    except Exception:
        pass
    _ = refs

    if done["err"]:
        safe_print(f"[x] {done['err']}")
        return 1
    if done["ok"]:
        safe_print("[+] no-UI invoke finished — check device + smart_share_log")
        return 0
    safe_print("[!] timeout waiting for OpenFromMenuWindow / CreateSend")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
