# -*- coding: utf-8 -*-
"""Find / close Xiaomi MiDrop device-picker popup windows."""
from __future__ import annotations

import ctypes
import subprocess
import time
from ctypes import wintypes
from typing import Any

_u = ctypes.WinDLL("user32", use_last_error=True)

_WM_CLOSE = 0x0010
_WINUI_CLASS = "WinUIDesktopWin32WindowClass"
_DEFAULT_PROC = "XiaomiPcManager"
# Small device-picker size band (physical pixels when DPI-aware)
_W_MIN, _W_MAX = 250, 480
_H_MIN, _H_MAX = 300, 560


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def ensure_dpi_aware() -> None:
    """Prefer per-monitor DPI awareness so window rects match UIA physical pixels."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            _u.SetProcessDPIAware()
        except Exception:
            pass


def pid_of(name: str) -> int | None:
    """Return first process id for *name*, or None if not running."""
    try:
        out = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"(Get-Process {name} -ErrorAction SilentlyContinue | "
                f"Select-Object -First 1 -ExpandProperty Id)",
            ],
            text=True,
        ).strip()
        return int(out) if out else None
    except Exception:
        return None


def _enum_windows() -> list[tuple[int, int, str, str, int, int, int, int]]:
    """Return [(hwnd, pid, class, title, left, top, w, h), ...] for visible windows."""
    res: list[tuple[int, int, str, str, int, int, int, int]] = []
    CB = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, ctypes.c_void_p)

    def cb(hwnd, _lp):
        if _u.IsWindowVisible(hwnd):
            pid = wintypes.DWORD()
            _u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            c = ctypes.create_unicode_buffer(128)
            _u.GetClassNameW(hwnd, c, 128)
            t = ctypes.create_unicode_buffer(256)
            _u.GetWindowTextW(hwnd, t, 256)
            r = RECT()
            _u.GetWindowRect(hwnd, ctypes.byref(r))
            res.append(
                (
                    int(hwnd),
                    int(pid.value),
                    c.value,
                    t.value,
                    int(r.left),
                    int(r.top),
                    int(r.right - r.left),
                    int(r.bottom - r.top),
                )
            )
        return True

    _u.EnumWindows(CB(cb), None)
    return res


def _is_small_winui(cls: str, w: int, h: int) -> bool:
    return (
        cls == _WINUI_CLASS
        and _W_MIN <= w <= _W_MAX
        and _H_MIN <= h <= _H_MAX
    )


def _is_visible_winui(cls: str, w: int, h: int) -> bool:
    # Title-match band: real pickers may be larger than the "small" band
    # (observed ~549x709 on some XiaomiPCManager builds; midrop_auto used w<700).
    return cls == _WINUI_CLASS and w >= 200 and h >= 200 and w <= 900 and h <= 1000


def _to_dict(
    hwnd: int, title: str, l: int, t: int, w: int, h: int
) -> dict[str, Any]:
    return {"hwnd": hwnd, "title": title, "l": l, "t": t, "w": w, "h": h}


def find_popup(pid: int | None = None) -> dict[str, Any] | None:
    """Find MiDrop device-picker popup.

    Prefer WinUI window whose title contains 「互传」.
    Fallback: exactly one small WinUI window under the process.
    """
    if pid is None:
        pid = pid_of(_DEFAULT_PROC)
    if not pid:
        return None

    small: list[tuple[int, str, int, int, int, int]] = []
    titled: list[tuple[int, str, int, int, int, int]] = []

    for hwnd, p, cls, title, l, t, w, h in _enum_windows():
        if p != pid:
            continue
        item = (hwnd, title, l, t, w, h)
        if _is_visible_winui(cls, w, h) and "互传" in (title or ""):
            titled.append(item)
        if _is_small_winui(cls, w, h):
            small.append(item)

    if titled:
        hwnd, title, l, t, w, h = titled[0]
        return _to_dict(hwnd, title, l, t, w, h)
    if len(small) == 1:
        hwnd, title, l, t, w, h = small[0]
        return _to_dict(hwnd, title, l, t, w, h)
    return None


def close_popup(pid: int | None = None) -> bool:
    """Close device-picker popup via WM_CLOSE. Returns True if a popup was found."""
    popup = find_popup(pid)
    if not popup:
        return False
    _u.PostMessageW(popup["hwnd"], _WM_CLOSE, 0, 0)
    time.sleep(0.6)
    return True
