# -*- coding: utf-8 -*-
"""
Silent MiDrop send: no shared memory, no Launch.exe, no popup.

``OpenFromMenuWindow`` (the trigger the older ``noui`` path borrows) merely runs
on the manager's UI thread, which also owns a message loop. So instead of staging
a menu flow just to reach it, we hook ``user32!GetMessageW``, poke that thread so
its loop takes another lap, and call ``HandleCreateSendTask`` when the hook fires.

The poke is not optional: an idle manager parks *inside* ``GetMessageW``, and a
hook on the function's entry cannot run until something makes it return. Early
versions omitted it and worked only while a MiDrop window happened to be driving
the UI — they timed out with the manager sitting in the tray. See ``poke_thread``.

A phone in deep sleep drops the first attempt with
``err_code=15033 "logical conn remote confirm timeout"``. That is a phone-side
wake problem, not a path problem — the popup route fails the same way. The
failed attempt wakes the device, so one retry normally lands.

Success is judged by the manager's own log (``OnTaskSucceed task_id N``), not by
the injected call returning.
"""
from __future__ import annotations

import ctypes
import json
import os
import re
import time
from ctypes import wintypes
from typing import Any

from midrop_cli.core.devices import resolve_device_id
from midrop_cli.core.live_devices import LYRA_LOG, _read_tail
from midrop_cli.core.popup import pid_of

NOTE = "PC 侧已发起（silent，无弹窗）；若手机需确认接收请在手机上同意"

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_ENV = 2
EXIT_TIMEOUT = 3
EXIT_CLICK = 4

# XiaomiPCManager 5.5.0.18 / MiSmartShareDLL.dll — re-calibrate after upgrade
CREATE_SEND_RVA = 0x1465F0
GET_BIZ = "?GetMiDropBusiness@midrop@@YAPEAVIMiDropBusiness@1@XZ"
PROC_NAME = "XiaomiPcManager"

# Window classes that never belong to the real UI thread
_HELPER_CLASSES = (
    "IME",
    "MSCTFIME UI",
    "GDI+ Hook Window Class",
    "PowerNotificationWindow",
    ".NET-BroadcastEventWindow",
)

_WM_NULL = 0x0000
# How often to re-poke while waiting for the hook to fire
_POKE_INTERVAL = 0.15

_TASK_CREATE_RE = re.compile(
    r"HandleCreateSendTask device_id (\d+)"
)
_TASK_CREATED_RE = re.compile(r"\[midrop\] task (\d+) created")
_SUCCEED_RE = re.compile(r"OnTaskSucceed task_id (\d+)")
_FAIL_RE = re.compile(r"OnTaskFail task ID (\d+), device_id \d+, error (\d+)")
_CHAN_FAIL_RE = re.compile(r"OnChannelCreateFailed .*?err_code=(\d+).*?MiContGetErrMsg=\"([^\"]*)\"")

_u = ctypes.WinDLL("user32", use_last_error=True)

JS = r"""
"use strict";
var CREATE_RVA = __CREATE_RVA__;
var DEVICE_ID = __DEVICE_ID__;
var FILE_PATH = __FILE_PATH__;
var UI_TID = __UI_TID__;
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
  mem.add(24).writeU64(n < 31 ? 31 : n);
  return { obj: mem, pin: heap };
}

function allocListOne(str) {
  var listObj = zalloc(16), head = zalloc(48), node = zalloc(48);
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
    return { size: listPtr.add(8).readU64().toNumber(), path: dp.readUtf16String(sz) };
  } catch (e) {
    return { err: String(e) };
  }
}

var mod = null;
Process.enumerateModules().forEach(function (m) {
  if (m.name.toLowerCase() === "mismartsharedll.dll") mod = m;
});

var done = false;
var listener = null;

function doCreateSend() {
  if (done) return;
  done = true;
  try { if (listener) listener.detach(); } catch (e) {}

  var thiz = new NativeFunction(mod.getExportByName(GET_BIZ), "pointer", [])();
  if (thiz.isNull()) {
    send({ type: "error", msg: "null this from GetMiDropBusiness" });
    return;
  }
  var built = allocListOne(FILE_PATH);
  var parent = allocWString("");
  // keep allocations alive past this frame; the manager reads them async
  globalThis.__pins = built.pins.concat([parent.obj, parent.pin].filter(Boolean));

  var chk = readPathFromList(built.list);
  if (chk.path && chk.path !== FILE_PATH) {
    send({ type: "error", msg: "path layout mismatch: " + chk.path });
    return;
  }
  send({ type: "log", msg: "CreateSend this=" + thiz + " tid=" + Process.getCurrentThreadId() });

  var fn = new NativeFunction(mod.base.add(CREATE_RVA), "void",
      ["pointer", "uint32", "pointer", "pointer"], "win64");
  try {
    fn(thiz, DEVICE_ID, built.list, parent.obj);
    send({ type: "ok", msg: "CreateSend returned" });
  } catch (e) {
    // Observed: can throw after successfully scheduling; log is the real verdict
    send({ type: "soft_ok", msg: "CreateSend threw after invoke: " + e });
  }
}

function main() {
  if (!mod) {
    send({ type: "error", msg: "MiSmartShareDLL.dll not loaded" });
    return;
  }
  var u32 = Process.getModuleByName("user32.dll");
  listener = Interceptor.attach(u32.getExportByName("GetMessageW"), {
    onEnter: function () {
      if (done) return;
      if (Process.getCurrentThreadId() !== UI_TID) return;
      try {
        doCreateSend();
      } catch (e) {
        send({ type: "error", msg: "pump: " + e });
      }
    }
  });
  send({ type: "ready" });
}

setImmediate(main);
"""


def _elapsed_ms(t0: float) -> int:
    return int((time.time() - t0) * 1000)


# ------------------------------------------------------------------ threads


def enum_windows(pid: int) -> list[dict[str, Any]]:
    """Return [{hwnd, tid, class, title}] for every window owned by *pid*."""
    out: list[dict[str, Any]] = []
    CB = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, ctypes.c_void_p)

    def cb(hwnd, _lp):
        p = wintypes.DWORD()
        tid = _u.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid:
            c = ctypes.create_unicode_buffer(128)
            _u.GetClassNameW(hwnd, c, 128)
            t = ctypes.create_unicode_buffer(256)
            _u.GetWindowTextW(hwnd, t, 256)
            out.append({"hwnd": int(hwnd), "tid": int(tid), "class": c.value, "title": t.value})
        return True

    _u.EnumWindows(CB(cb), None)
    return out


def pick_ui_thread(windows: list[dict[str, Any]]) -> int | None:
    """
    Pick the thread hosting the manager's real UI.

    The UI thread owns the WinUI/manager windows; helper threads only own IME,
    GDI+ and broadcast sinks. Chooses the thread owning the most non-helper
    windows. Returns None when nothing credible is present.
    """
    scores: dict[int, int] = {}
    for w in windows:
        cls = str(w.get("class") or "")
        if any(cls.startswith(h) for h in _HELPER_CLASSES):
            continue
        tid = int(w["tid"])
        scores[tid] = scores.get(tid, 0) + 1
    if not scores:
        return None
    # highest window count wins; tie -> lowest tid for determinism
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def resolve_ui_thread(pid: int) -> int | None:
    return pick_ui_thread(enum_windows(pid))


def thread_hwnds(windows: list[dict[str, Any]], tid: int) -> list[int]:
    """Window handles owned by *tid*, used as targets for the wake-up poke."""
    return [int(w["hwnd"]) for w in windows if int(w["tid"]) == int(tid)]


def poke_thread(hwnds: list[int], tid: int) -> None:
    """
    Nudge a UI thread so its message loop takes another lap.

    An idle manager blocks *inside* ``GetMessageW`` waiting for input, and a hook
    on that function's entry cannot fire while the thread is parked in it. Posting
    a harmless ``WM_NULL`` makes ``GetMessageW`` return; the loop dispatches it and
    calls ``GetMessageW`` again, which is when the hook finally runs.

    Without this, silent sends only worked while something else happened to be
    driving the UI (an open MiDrop window, an animation), and timed out whenever
    the manager sat quietly in the tray.
    """
    for h in hwnds:
        _u.PostMessageW(wintypes.HWND(int(h)), _WM_NULL, 0, 0)
    _u.PostThreadMessageW(wintypes.DWORD(int(tid)), _WM_NULL, 0, 0)


# --------------------------------------------------------------- log verdict


def _parse_task_id(tail: str, device_id: int) -> int | None:
    """
    Find the task id the manager assigned to our CreateSend call.

    The manager logs ``HandleCreateSendTask device_id N`` then, on the very next
    line, ``task <id> created``. Returns the last such id for *device_id*.
    """
    found: int | None = None
    lines = tail.splitlines()
    for i, line in enumerate(lines):
        m = _TASK_CREATE_RE.search(line)
        if not m or int(m.group(1)) != device_id:
            continue
        for nxt in lines[i + 1 : i + 4]:
            m2 = _TASK_CREATED_RE.search(nxt)
            if m2:
                found = int(m2.group(1))
                break
    return found


def confirm_task_from_log(tail: str, task_id: int) -> tuple[str, str]:
    """
    Judge a task from the manager's log.

    Returns (state, detail) where state is succeeded | failed | pending.
    """
    last_chan_fail = ""
    for line in tail.splitlines():
        m = _CHAN_FAIL_RE.search(line)
        if m:
            last_chan_fail = f"err_code={m.group(1)} {m.group(2)}"
        m = _SUCCEED_RE.search(line)
        if m and int(m.group(1)) == task_id:
            return "succeeded", f"OnTaskSucceed task_id {task_id}"
        m = _FAIL_RE.search(line)
        if m and int(m.group(1)) == task_id:
            detail = f"OnTaskFail task_id {task_id}, error {m.group(2)}"
            if last_chan_fail:
                detail += f"; {last_chan_fail}"
            return "failed", detail
    return "pending", ""


def _await_verdict(device_id: int, since: int, wait_s: float) -> tuple[str, str, int | None]:
    """Poll the manager log until the task reaches a terminal state."""
    deadline = time.time() + wait_s
    task_id: int | None = None
    detail = ""
    while time.time() < deadline:
        tail = _read_tail(LYRA_LOG)
        fresh = tail[since:] if since and len(tail) > since else tail
        if task_id is None:
            task_id = _parse_task_id(fresh, device_id)
        if task_id is not None:
            state, detail = confirm_task_from_log(fresh, task_id)
            if state in ("succeeded", "failed"):
                return state, detail, task_id
        time.sleep(0.3)
    return "pending", detail, task_id


# ------------------------------------------------------------------- attempt


def _build_js(path: str, device_id: int, ui_tid: int) -> str:
    return (
        JS.replace("__CREATE_RVA__", hex(CREATE_SEND_RVA))
        .replace("__DEVICE_ID__", str(int(device_id) & 0xFFFFFFFF))
        .replace("__FILE_PATH__", json.dumps(path))
        .replace("__UI_TID__", str(int(ui_tid)))
        .replace("__GET_BIZ__", json.dumps(GET_BIZ))
    )


def _invoke_once(
    pid: int,
    path: str,
    device_id: int,
    ui_tid: int,
    timeout: float,
    hwnds: list[int] | None = None,
) -> tuple[bool, str, list[str]]:
    """Attach, fire CreateSend on the UI pump, detach. Returns (invoked, err, logs)."""
    import frida

    state: dict[str, Any] = {"ok": False, "err": None, "logs": []}

    def on_message(message, _data):
        if message["type"] != "send":
            return
        p = message["payload"]
        if not isinstance(p, dict):
            return
        t = p.get("type")
        if t in ("log", "ready"):
            state["logs"].append(str(p.get("msg", t)))
        elif t in ("ok", "soft_ok"):
            state["ok"] = True
            state["logs"].append(str(p.get("msg", t)))
        elif t == "error":
            state["err"] = p.get("msg")

    session = frida.attach(pid)
    try:
        script = session.create_script(_build_js(path, device_id, ui_tid))
        script.on("message", on_message)
        script.load()
        deadline = time.time() + max(3.0, float(timeout))
        while time.time() < deadline:
            if state["ok"] or state["err"]:
                break
            # The pump may be parked inside GetMessageW; keep nudging it so the
            # hook gets a chance to run. Harmless when the thread is already busy.
            poke_thread(hwnds or [], ui_tid)
            time.sleep(_POKE_INTERVAL)
    finally:
        try:
            session.detach()
        except Exception:
            pass
    return bool(state["ok"]), str(state["err"] or ""), state["logs"]


def frida_available() -> tuple[bool, str]:
    try:
        import frida  # noqa: F401

        return True, f"frida {frida.__version__}"
    except Exception as e:
        return False, str(e)


def send_file_silent(
    path: str,
    device_query: str,
    timeout: float = 25.0,
    hold: float = 8.0,
    launch_path: str = "",  # unused; kept for dispatcher signature parity
    cfg_data: dict[str, Any] | None = None,
    retry: int = 1,
    confirm: bool = True,
) -> dict[str, Any]:
    """
    Send with no popup at all.

    A sleeping phone times out the first logical connection; that attempt wakes
    it, so ``retry`` re-fires once by default.
    """
    t0 = time.time()
    path = os.path.abspath(path)
    base: dict[str, Any] = {
        "action": "send",
        "mode": "silent",
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

    windows = enum_windows(pid)
    ui_tid = pick_ui_thread(windows)
    if not ui_tid:
        return {
            **base,
            "ok": False,
            "error": "environment",
            "message": (
                "no UI thread found in XiaomiPcManager; "
                "open the manager window once, or use --mode menu"
            ),
            "elapsed_ms": _elapsed_ms(t0),
            "exit_code": EXIT_ENV,
        }
    base["ui_tid"] = ui_tid
    hwnds = thread_hwnds(windows, ui_tid)

    attempts = max(1, int(retry) + 1)
    logs: list[str] = []
    last_detail = ""
    task_id: int | None = None

    for i in range(attempts):
        since = len(_read_tail(LYRA_LOG)) if confirm else 0
        try:
            invoked, err, alogs = _invoke_once(
                pid, path, device_id, ui_tid, timeout, hwnds
            )
        except Exception as e:
            return {
                **base,
                "ok": False,
                "error": "environment",
                "message": f"silent send failed: {e}",
                "elapsed_ms": _elapsed_ms(t0),
                "exit_code": EXIT_ENV,
                "logs": logs[-8:],
            }
        logs.extend(alogs)

        if not invoked:
            if err:
                return {
                    **base,
                    "ok": False,
                    "error": "click_failed",
                    "message": err,
                    "elapsed_ms": _elapsed_ms(t0),
                    "exit_code": EXIT_CLICK,
                    "logs": logs[-8:],
                }
            continue

        if not confirm:
            time.sleep(max(0.0, float(hold)))
            return {
                **base,
                "ok": True,
                "silent_invoked": True,
                "attempts": i + 1,
                "confirmed": False,
                "elapsed_ms": _elapsed_ms(t0),
                "note": NOTE,
                "exit_code": EXIT_OK,
                "logs": logs[-8:],
            }

        state, detail, task_id = _await_verdict(device_id, since, max(20.0, float(timeout)))
        last_detail = detail
        if state == "succeeded":
            return {
                **base,
                "ok": True,
                "silent_invoked": True,
                "attempts": i + 1,
                "confirmed": True,
                "task_id": task_id,
                "elapsed_ms": _elapsed_ms(t0),
                "note": "手机已确认接收（OnTaskSucceed）",
                "exit_code": EXIT_OK,
                "logs": logs[-8:],
            }
        if state == "failed" and i + 1 < attempts:
            logs.append(f"attempt {i + 1} failed ({detail}); retrying — device likely woke up")
            continue
        if state == "pending" and i + 1 < attempts:
            logs.append(f"attempt {i + 1} unconfirmed; retrying")
            continue

        return {
            **base,
            "ok": False,
            "error": "send_failed" if state == "failed" else "confirm_timeout",
            "message": (
                detail
                or "task did not reach a terminal state in the manager log; "
                "the phone may be asleep or out of range"
            ),
            "attempts": i + 1,
            "task_id": task_id,
            "elapsed_ms": _elapsed_ms(t0),
            "exit_code": EXIT_CLICK if state == "failed" else EXIT_TIMEOUT,
            "logs": logs[-8:],
        }

    return {
        **base,
        "ok": False,
        "error": "confirm_timeout",
        "message": last_detail or "CreateSend never reached the UI thread pump",
        "attempts": attempts,
        "task_id": task_id,
        "elapsed_ms": _elapsed_ms(t0),
        "exit_code": EXIT_TIMEOUT,
        "logs": logs[-8:],
    }
