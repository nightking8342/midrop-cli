# -*- coding: utf-8 -*-
"""
In-process invoke of midrop::MiDropBusinessMgr::HandleCreateSendTask
without UI click.

Usage:
  python frida_invoke_createsend.py <file> [device_hex|Fold|Pad]

Examples:
  python frida_invoke_createsend.py C:\\tmp\\a.txt Fold
  python frida_invoke_createsend.py C:\\tmp\\a.txt 0xD16E4A0F
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

import frida

FUNC_RVA = 0x1465F0
GET_BIZ_EXPORT = "?GetMiDropBusiness@midrop@@YAPEAVIMiDropBusiness@1@XZ"

DEVICE_ALIASES = {
    "fold": 0xD16E4A0F,
    "phone": 0xD16E4A0F,
    "mix": 0xD16E4A0F,
    "pad": 0x347FBBC5,
    "tablet": 0x347FBBC5,
}


def get_pid() -> int:
    out = subprocess.check_output(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "(Get-Process XiaomiPcManager | Select-Object -First 1).Id",
        ],
        text=True,
    ).strip()
    return int(out)


def parse_device(s: str) -> int:
    key = s.strip().lower()
    if key in DEVICE_ALIASES:
        return DEVICE_ALIASES[key]
    if key.startswith("0x"):
        return int(key, 16)
    return int(key, 0)


JS_TEMPLATE = r"""
"use strict";

var FUNC_RVA = __FUNC_RVA__;
var DEVICE_ID = __DEVICE_ID__;
var FILE_PATH = __FILE_PATH__;
var GET_BIZ = __GET_BIZ__;

// MSVC x64 std::wstring (32 bytes): SSO if capacity < 8 wchar_t
function allocWString(str) {
  var n = str.length;
  var mem = Memory.alloc(32);
  for (var zi = 0; zi < 32; zi++) mem.add(zi).writeU8(0);

  if (n < 8) {
    mem.writeUtf16String(str);
    mem.add(16).writeU64(n);
    mem.add(24).writeU64(7); // SSO capacity
  } else {
    var heap = Memory.alloc((n + 1) * 2);
    heap.writeUtf16String(str);
    mem.writePointer(heap);
    mem.add(16).writeU64(n);
    mem.add(24).writeU64(n < 8 ? 8 : n);
  }
  return mem;
}

// MSVC x64 std::list with one wstring element
// list object: { node* head; size_t size; } = 16 bytes
// node: { node* next; node* prev; wstring value; } = 16+32 = 48 bytes
function allocListOneWString(str) {
  var listObj = Memory.alloc(16);
  var head = Memory.alloc(48); // sentinel node (value unused)
  var node = Memory.alloc(48);

  // zero nodes
  for (var i = 0; i < 48; i++) { head.add(i).writeU8(0); node.add(i).writeU8(0); }

  // circular: head <-> node
  head.writePointer(node);          // head->_Next = node
  head.add(8).writePointer(node);   // head->_Prev = node
  node.writePointer(head);          // node->_Next = head
  node.add(8).writePointer(head);   // node->_Prev = head

  // value at node+16
  var ws = allocWString(str);
  // copy 32-byte wstring into node+16 (keep heap ptr alive via ws - pin later)
  Memory.copy(node.add(16), ws, 32);

  listObj.writePointer(head);
  listObj.add(8).writeU64(1);

  return { list: listObj, pins: [head, node, ws] };
}

function readStdWString(p) {
  try {
    var size = p.add(16).readU64().toNumber();
    var cap = p.add(24).readU64().toNumber();
    var dataPtr = cap < 8 ? p : p.readPointer();
    return dataPtr.readUtf16String(size);
  } catch (e) {
    return "<err " + e + ">";
  }
}

function dumpList(listPtr) {
  var head = listPtr.readPointer();
  var size = listPtr.add(8).readU64().toNumber();
  var out = [];
  var node = head.readPointer();
  for (var i = 0; i < size; i++) {
    out.push(readStdWString(node.add(16)));
    node = node.readPointer();
  }
  return { size: size, paths: out };
}

function findModule() {
  var mod = null;
  Process.enumerateModules().forEach(function (m) {
    if (m.name.toLowerCase() === "mismartsharedll.dll") mod = m;
  });
  return mod;
}

function resolveThis(mod) {
  // Prefer GetMiDropBusiness export
  var exp = null;
  try {
    exp = mod.getExportByName(GET_BIZ);
  } catch (e) {}
  if (exp) {
    var getBiz = new NativeFunction(exp, "pointer", []);
    var p = getBiz();
    send({ type: "log", msg: "GetMiDropBusiness() => " + p });
    if (!p.isNull()) return p;
  }
  send({ type: "log", msg: "GetMiDropBusiness failed, cannot resolve this" });
  return null;
}

function main() {
  var mod = findModule();
  if (!mod) {
    send({ type: "error", msg: "MiSmartShareDLL.dll not loaded" });
    return;
  }
  var fnAddr = mod.base.add(FUNC_RVA);
  send({ type: "log", msg: "HandleCreateSendTask @ " + fnAddr });

  var thiz = resolveThis(mod);
  if (!thiz || thiz.isNull()) {
    send({ type: "error", msg: "null this pointer" });
    return;
  }

  var built = allocListOneWString(FILE_PATH);
  var listPtr = built.list;
  // keep pins alive
  globalThis.__midrop_pins = built.pins;
  globalThis.__midrop_list = listPtr;

  // r9 = selected_parent_dir as std::wstring (disasm: cmp [r9+0x18], 8 = capacity)
  // logs show empty parent_dir for CLI-triggered sends
  var parentDir = allocWString("");
  globalThis.__midrop_pins = built.pins.concat([parentDir]);
  globalThis.__midrop_list = listPtr;

  var dump = dumpList(listPtr);
  send({ type: "log", msg: "built list size=" + dump.size + " paths0=" + (dump.paths[0] || "") });
  send({ type: "log", msg: "invoke device_id=" + DEVICE_ID + " file=" + FILE_PATH });

  // void HandleCreateSendTask(this, uint device_id, list*, wstring* parent_dir)
  // Call on a NEW OS thread so we do not block Frida's JS thread (deadlock risk).
  var fn = new NativeFunction(
    fnAddr,
    "void",
    ["pointer", "uint32", "pointer", "pointer"],
    "win64"
  );

  var CreateThread = new NativeFunction(
    Process.getModuleByName("kernel32.dll").getExportByName("CreateThread"),
    "pointer",
    ["pointer", "size_t", "pointer", "pointer", "uint32", "pointer"]
  );
  var WaitForSingleObject = new NativeFunction(
    Process.getModuleByName("kernel32.dll").getExportByName("WaitForSingleObject"),
    "uint32",
    ["pointer", "uint32"]
  );
  var CloseHandle = new NativeFunction(
    Process.getModuleByName("kernel32.dll").getExportByName("CloseHandle"),
    "int",
    ["pointer"]
  );

  var argsBuf = Memory.alloc(32);
  argsBuf.writePointer(thiz);
  argsBuf.add(8).writeU32(DEVICE_ID);
  argsBuf.add(16).writePointer(listPtr);
  argsBuf.add(24).writePointer(parentDir);
  globalThis.__midrop_args = argsBuf;

  var stub = new NativeCallback(
    function (param) {
      try {
        var t = param.readPointer();
        var dev = param.add(8).readU32();
        var lst = param.add(16).readPointer();
        var par = param.add(24).readPointer();
        send({ type: "log", msg: "worker thread calling CreateSend dev=" + dev });
        fn(t, dev, lst, par);
        send({ type: "ok", msg: "worker returned" });
      } catch (e) {
        send({ type: "error", msg: "worker threw: " + e });
      }
      return 0;
    },
    "uint32",
    ["pointer"]
  );
  globalThis.__midrop_stub = stub;

  var threadId = Memory.alloc(8);
  var h = CreateThread(ptr(0), 0, stub, argsBuf, 0, threadId);
  send({ type: "log", msg: "CreateThread handle=" + h + " tid=" + threadId.readU32() });
  if (h.isNull()) {
    send({ type: "error", msg: "CreateThread failed" });
    return;
  }
  // wait up to 20s
  var wr = WaitForSingleObject(h, 20000);
  send({ type: "log", msg: "WaitForSingleObject=" + wr + " (0=signaled, 258=timeout)" });
  CloseHandle(h);
  if (wr === 258) {
    send({ type: "error", msg: "invoke timed out (possible UI-thread requirement or deadlock)" });
  }
}

setImmediate(main);
"""


def build_js(file_path: str, device_id: int) -> str:
    # JSON-escape for embedding
    import json

    return (
        JS_TEMPLATE.replace("__FUNC_RVA__", hex(FUNC_RVA))
        .replace("__DEVICE_ID__", str(int(device_id)))
        .replace("__FILE_PATH__", json.dumps(file_path))
        .replace("__GET_BIZ__", json.dumps(GET_BIZ_EXPORT))
    )


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    path = os.path.abspath(sys.argv[1])
    if not os.path.isfile(path):
        print(f"[x] file not found: {path}")
        return 1
    device_id = parse_device(sys.argv[2] if len(sys.argv) > 2 else "Fold")

    pid = get_pid()
    print(f"[*] pid={pid} file={path} device_id={device_id} (0x{device_id:X})")

    session = frida.attach(pid)
    done = {"ok": False, "err": None}

    def on_message(message, data):
        def safe(x):
            s = str(x)
            enc = getattr(sys.stdout, "encoding", None) or "utf-8"
            return s.encode(enc, "replace").decode(enc, "replace")

        if message["type"] == "send":
            p = message["payload"]
            print("[js]", safe(p), flush=True)
            if isinstance(p, dict):
                if p.get("type") == "ok":
                    done["ok"] = True
                if p.get("type") == "error":
                    done["err"] = p.get("msg")
        else:
            print(safe(message), flush=True)

    script = session.create_script(build_js(path, device_id))
    script.on("message", on_message)
    script.load()

    # wait for invoke
    t0 = time.time()
    while time.time() - t0 < 15:
        if done["ok"] or done["err"]:
            break
        time.sleep(0.2)

    # hold process a bit so async send can start
    time.sleep(8)
    try:
        session.detach()
    except Exception:
        pass

    if done["err"]:
        print("[x]", done["err"])
        return 1
    if done["ok"]:
        print("[+] invoke completed — check phone/pad and smart_share_log for CreateSend/OnTaskSucceed")
        return 0
    print("[!] no result from script")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
