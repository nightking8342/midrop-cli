/**
 * Hook midrop::MiDropBusinessMgr::HandleCreateSendTask
 * RVA 0x1465F0 in MiSmartShareDLL.dll (5.5.0.18, verified via .pdata)
 *
 *   frida -p <XiaomiPcManager PID> -l frida_hook_createsend.js
 */
"use strict";

var FUNC_RVA = 0x1465f0;

function readStdWString(p) {
  try {
    if (p.isNull()) return "<null>";
    var size = p.add(16).readU64().toNumber();
    var capacity = p.add(24).readU64().toNumber();
    if (size > 0x10000) return "<bad size " + size + " cap=" + capacity + ">";
    var dataPtr = capacity < 8 ? p : p.readPointer();
    return dataPtr.readUtf16String(size);
  } catch (e) {
    return "<wstring err " + e + ">";
  }
}

function readStdListWString(listPtr) {
  var paths = [];
  try {
    // MSVC x64 std::list: { node* _Myhead; size_t _Mysize; } at start of object
    var head = listPtr.readPointer();
    var size = listPtr.add(8).readU64().toNumber();
    console.log("  list head=" + head + " size=" + size);
    if (size > 64) return ["<list size crazy: " + size + ">"];
    var node = head.readPointer(); // head->_Next
    for (var i = 0; i < size; i++) {
      // list node: _Next*0, _Prev*8, value at 16
      paths.push(readStdWString(node.add(16)));
      node = node.readPointer();
    }
  } catch (e) {
    paths.push("<list err " + e + ">");
  }
  return paths;
}

function hexdumpShort(p, n) {
  try {
    return hexdump(p, { length: n, ansi: false });
  } catch (e) {
    return "<hexdump err>";
  }
}

function main() {
  var mod = null;
  Process.enumerateModules().forEach(function (m) {
    if (m.name.toLowerCase() === "mismartsharedll.dll") mod = m;
  });
  if (!mod) {
    console.log("[-] MiSmartShareDLL.dll not loaded in process");
    return;
  }
  var addr = mod.base.add(FUNC_RVA);
  console.log("[+] MiSmartShareDLL base=" + mod.base);
  console.log("[+] HandleCreateSendTask @ " + addr + " (base+0x" + FUNC_RVA.toString(16) + ")");
  console.log("[+] first bytes: " + addr.readByteArray(16));

  Interceptor.attach(addr, {
    onEnter: function (args) {
      console.log("\n========== HandleCreateSendTask ENTER ==========");
      // MSVC x64 method: rcx=this, rdx=arg1, r8=arg2, r9=arg3, stack more
      var thiz = args[0];
      var a1 = args[1];
      var a2 = args[2];
      var a3 = args[3];
      console.log("this  rcx=" + thiz);
      console.log("arg1  rdx=" + a1 + " u32=" + (a1.toInt32() >>> 0) + " hex=0x" + (a1.toInt32() >>> 0).toString(16));
      console.log("arg2  r8 =" + a2);
      console.log("arg3  r9 =" + a3);

      var dev = a1.toInt32() >>> 0;
      console.log("[*] device_id (assuming rdx) = " + dev + " (0x" + dev.toString(16) + ")");
      if (dev === 0xd16e4a0f) console.log("    -> Xiaomi MIX Fold 3");
      if (dev === 0x347fbbc5) console.log("    -> Xiaomi Pad 7S Pro");

      console.log("[*] try paths list at r8 (arg2):");
      console.log(JSON.stringify(readStdListWString(a2), null, 2));
      console.log("[*] try paths list at r9 (arg3):");
      console.log(JSON.stringify(readStdListWString(a3), null, 2));

      // If list is passed by value on stack (unlikely for list), dump stack
      var rsp = this.context.rsp;
      console.log("rsp=" + rsp);
      for (var off = 0x20; off <= 0x50; off += 8) {
        try {
          var v = rsp.add(off).readPointer();
          console.log("  [rsp+0x" + off.toString(16) + "]=" + v);
        } catch (e) {}
      }
      console.log("r8 mem:\n" + hexdumpShort(a2, 64));
      console.log("================================================\n");
    },
    onLeave: function (retval) {
      console.log("[*] HandleCreateSendTask LEAVE ret=" + retval);
    }
  });
  console.log("[+] hook ready — trigger midrop send / click device");
}

setImmediate(main);
