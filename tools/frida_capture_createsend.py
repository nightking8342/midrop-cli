# -*- coding: utf-8 -*-
"""Keep Frida session alive and capture HandleCreateSendTask args."""
from __future__ import annotations

import subprocess
import sys
import time

import frida

FUNC_RVA = 0x1465F0

JS = r"""
"use strict";
var FUNC_RVA = 0x1465f0;

function readStdWString(p) {
  try {
    if (p.isNull()) return "<null>";
    var size = p.add(16).readU64().toNumber();
    var capacity = p.add(24).readU64().toNumber();
    if (size > 0x10000) return "<bad size " + size + ">";
    var dataPtr = capacity < 8 ? p : p.readPointer();
    return dataPtr.readUtf16String(size);
  } catch (e) {
    return "<wstring err " + e + ">";
  }
}

function readStdListWString(listPtr) {
  var paths = [];
  try {
    var head = listPtr.readPointer();
    var size = listPtr.add(8).readU64().toNumber();
    send({type: "log", msg: "list head=" + head + " size=" + size});
    if (size > 64) return ["<list size crazy: " + size + ">"];
    var node = head.readPointer();
    for (var i = 0; i < size; i++) {
      paths.push(readStdWString(node.add(16)));
      node = node.readPointer();
    }
  } catch (e) {
    paths.push("<list err " + e + ">");
  }
  return paths;
}

var mod = null;
Process.enumerateModules().forEach(function (m) {
  if (m.name.toLowerCase() === "mismartsharedll.dll") mod = m;
});
if (!mod) {
  send({type: "error", msg: "MiSmartShareDLL.dll not loaded"});
} else {
  var addr = mod.base.add(FUNC_RVA);
  send({type: "log", msg: "base=" + mod.base + " HandleCreateSendTask=" + addr});
  send({type: "log", msg: "bytes=" + hexdump(addr, {length: 12, header: false, ansi: false})});
  Interceptor.attach(addr, {
    onEnter: function (args) {
      var dev = args[1].toInt32() >>> 0;
      var payload = {
        type: "createsend",
        this: String(args[0]),
        device_id: dev,
        device_hex: "0x" + dev.toString(16),
        r8: String(args[2]),
        r9: String(args[3]),
        paths_r8: readStdListWString(args[2]),
        paths_r9: readStdListWString(args[3]),
        rcx_u32: args[0].toInt32() >>> 0,
        stack: {}
      };
      try {
        var rsp = this.context.rsp;
        for (var off = 0x20; off <= 0x58; off += 8) {
          payload.stack["rsp+0x" + off.toString(16)] = String(rsp.add(off).readPointer());
        }
      } catch (e) {}
      send(payload);
    },
    onLeave: function (retval) {
      send({type: "log", msg: "LEAVE ret=" + retval});
    }
  });
  send({type: "ready"});
}
"""


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


def main() -> int:
    hold = float(sys.argv[1]) if len(sys.argv) > 1 else 90.0
    pid = get_pid()
    print(f"[*] attach pid={pid}, hold={hold}s", flush=True)
    session = frida.attach(pid)
    hits: list = []

    def on_message(message, data):
        if message["type"] == "send":
            payload = message["payload"]
            if isinstance(payload, dict) and payload.get("type") == "createsend":
                hits.append(payload)
                print("\n=== CAPTURED HandleCreateSendTask ===", flush=True)
                print(payload, flush=True)
            else:
                print("[js]", payload, flush=True)
        elif message["type"] == "error":
            print("[err]", message, flush=True)
        else:
            print(message, flush=True)

    script = session.create_script(JS)
    script.on("message", on_message)
    script.load()
    print("[*] hook loaded — trigger a send now", flush=True)
    t0 = time.time()
    try:
        while time.time() - t0 < hold:
            time.sleep(0.5)
            if hits:
                # keep a few more seconds for leave
                time.sleep(2)
                break
    finally:
        try:
            session.detach()
        except Exception:
            pass
    print(f"[*] done, hits={len(hits)}", flush=True)
    return 0 if hits else 1


if __name__ == "__main__":
    raise SystemExit(main())
