# -*- coding: utf-8 -*-
"""UIA helpers: list MiDrop devices and click a target by keyword."""
from __future__ import annotations

import os
import re
import subprocess
import time
from typing import Any

from midrop_cli.core.popup import ensure_dpi_aware

_FOUND_RE = re.compile(
    r"FOUND\s+name=(?P<name>.*?)\s+click=\((?P<x>-?\d+)\s*,\s*(?P<y>-?\d+)\)"
)

# PowerShell: enumerate device TextBlocks under XiaomiPcManager popup
_UIA_LIST = r"""
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$pidMi = (Get-Process XiaomiPcManager -ErrorAction SilentlyContinue | Select-Object -First 1).Id
if (-not $pidMi) { Write-Output "NO_PROC"; exit 2 }
$root = [System.Windows.Automation.AutomationElement]::RootElement
$pcond = New-Object System.Windows.Automation.PropertyCondition(
  [System.Windows.Automation.AutomationElement]::ProcessIdProperty, [int]$pidMi)
$wins = $root.FindAll([System.Windows.Automation.TreeScope]::Children, $pcond)
$seen = New-Object 'System.Collections.Generic.HashSet[string]'
foreach ($w in $wins) {
  $b = $w.Current.BoundingRectangle
  if ($b.Width -lt 200 -or $b.Height -lt 250 -or $b.Width -gt 700) { continue }
  $all = $w.FindAll([System.Windows.Automation.TreeScope]::Descendants,
    [System.Windows.Automation.Condition]::TrueCondition)
  foreach ($e in $all) {
    $n = $e.Current.Name
    if (-not $n) { continue }
    if ($n -notmatch 'Xiaomi|我的') { continue }
    if ($seen.Add($n)) {
      Write-Output ("DEVICE`t{0}" -f $n)
    }
  }
}
"""

# PowerShell: find device TextBlock by keyword and click center (physical pixels)
_UIA_CLICK = r"""
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class MidropMouse {
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint x, uint y, uint d, UIntPtr e);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("shcore.dll")] public static extern int SetProcessDpiAwareness(int v);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  public const uint LEFTDOWN=0x0002, LEFTUP=0x0004;
}
"@
try { [void][MidropMouse]::SetProcessDpiAwareness(2) } catch {
  try { [void][MidropMouse]::SetProcessDPIAware() } catch {}
}
$keyword = $env:MIDROP_DEVICE
$pidMi = (Get-Process XiaomiPcManager -ErrorAction SilentlyContinue | Select-Object -First 1).Id
if (-not $pidMi) { Write-Output "NO_PROC"; exit 2 }
$root = [System.Windows.Automation.AutomationElement]::RootElement
$pcond = New-Object System.Windows.Automation.PropertyCondition(
  [System.Windows.Automation.AutomationElement]::ProcessIdProperty, [int]$pidMi)
$wins = $root.FindAll([System.Windows.Automation.TreeScope]::Children, $pcond)
$target = $null
$winHwnd = [IntPtr]::Zero
foreach ($w in $wins) {
  $b = $w.Current.BoundingRectangle
  if ($b.Width -lt 200 -or $b.Height -lt 250 -or $b.Width -gt 700) { continue }
  $all = $w.FindAll([System.Windows.Automation.TreeScope]::Descendants,
    [System.Windows.Automation.Condition]::TrueCondition)
  foreach ($e in $all) {
    $n = $e.Current.Name
    if ($n -and ($n -like "*$keyword*")) {
      $target = $e
      $winHwnd = [IntPtr]$w.Current.NativeWindowHandle
      break
    }
  }
  if ($target) { break }
}
if (-not $target) { Write-Output "NOT_FOUND"; exit 3 }
$r = $target.Current.BoundingRectangle
$cx = [int]($r.X + $r.Width/2)
$cy = [int]($r.Y + $r.Height/2)
Write-Output ("FOUND name={0} click=({1},{2})" -f $target.Current.Name, $cx, $cy)
if ($winHwnd -ne [IntPtr]::Zero) { [void][MidropMouse]::SetForegroundWindow($winHwnd) }
Start-Sleep -Milliseconds 300
[void][MidropMouse]::SetCursorPos($cx, $cy)
Start-Sleep -Milliseconds 80
[MidropMouse]::mouse_event([MidropMouse]::LEFTDOWN,0,0,0,[UIntPtr]::Zero)
Start-Sleep -Milliseconds 50
[MidropMouse]::mouse_event([MidropMouse]::LEFTUP,0,0,0,[UIntPtr]::Zero)
Write-Output "CLICKED"
"""


def _decode_ps(data: bytes) -> str:
    """Decode PowerShell capture; console often emits system ANSI (GBK on zh-CN)."""
    if not data:
        return ""
    for enc in ("utf-8-sig", "utf-8", "gbk", "gb18030", "cp936"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _run_ps(script: str, env: dict[str, str] | None = None) -> tuple[int, str]:
    """Run PowerShell -Command script; return (returncode, combined stdout+stderr)."""
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    # Prefix forces UTF-8 for hosts that honor OutputEncoding; _decode_ps still
    # falls back to GBK when the console code page is used instead.
    wrapped = (
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
        "$OutputEncoding = [System.Text.Encoding]::UTF8; "
        + script
    )
    r = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            wrapped,
        ],
        capture_output=True,
        env=run_env,
    )
    out = (_decode_ps(r.stdout or b"") + _decode_ps(r.stderr or b"")).replace("\r", "")
    return r.returncode, out


def _parse_device_lines(out: str) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith("DEVICE"):
            continue
        # DEVICE\tname  (or DEVICE + whitespace + name)
        if "\t" in line:
            name = line.split("\t", 1)[1].strip()
        else:
            parts = line.split(None, 1)
            name = parts[1].strip() if len(parts) > 1 else ""
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def _parse_found(out: str) -> tuple[str, list[int]] | None:
    for line in out.splitlines():
        m = _FOUND_RE.search(line.strip())
        if m:
            return m.group("name"), [int(m.group("x")), int(m.group("y"))]
    return None


def _list_once() -> tuple[str | None, list[str]]:
    """Single UIA list pass. Returns (error|None, devices).

    error is 'no_proc' when XiaomiPcManager is not running.
    """
    _code, out = _run_ps(_UIA_LIST)
    if "NO_PROC" in out:
        return "no_proc", []
    return None, _parse_device_lines(out)


def list_devices(timeout: float = 12.0) -> list[str]:
    """Poll UIA until devices appear or timeout; return names (may be empty)."""
    ensure_dpi_aware()
    deadline = time.time() + max(0.0, float(timeout))
    last: list[str] = []
    while True:
        err, names = _list_once()
        if names:
            return names
        if err == "no_proc":
            # Process gone: keep polling until timeout (may start later)
            last = []
        else:
            last = names
        if time.time() >= deadline:
            return last
        time.sleep(0.4)


def click_device(keyword: str, timeout: float = 12.0) -> dict[str, Any]:
    """Find and click a device whose Name contains *keyword*.

    Success: ``{"ok": True, "name": "...", "click": [x, y]}``
    Failure: ``{"ok": False, "error": ..., "candidates": [...], "message": "..."}``
    """
    ensure_dpi_aware()
    kw = (keyword or "").strip()
    if not kw:
        return {
            "ok": False,
            "error": "device_not_found",
            "candidates": [],
            "message": "empty device keyword",
        }

    deadline = time.time() + max(0.0, float(timeout))
    saw_no_proc = False
    last_out = ""

    while time.time() < deadline:
        _code, out = _run_ps(_UIA_CLICK, env={"MIDROP_DEVICE": kw})
        last_out = out.strip()
        if "CLICKED" in out:
            parsed = _parse_found(out)
            if parsed:
                name, click = parsed
                return {"ok": True, "name": name, "click": click}
            # Clicked but FOUND line missing/unparseable
            return {
                "ok": False,
                "error": "click_failed",
                "candidates": [],
                "message": f"clicked but could not parse FOUND line: {last_out}",
            }
        if "NO_PROC" in out:
            saw_no_proc = True
            time.sleep(0.4)
            continue
        if "NOT_FOUND" in out:
            saw_no_proc = False
            time.sleep(0.4)
            continue
        # Unexpected output — brief backoff then retry
        time.sleep(0.4)

    # Timed out: gather candidates for diagnostics
    err, candidates = _list_once()
    if err == "no_proc" and saw_no_proc:
        return {
            "ok": False,
            "error": "no_proc",
            "candidates": [],
            "message": "XiaomiPcManager process not running",
        }
    if err == "no_proc" and not candidates:
        # Ended with no process and never saw a successful scan
        if saw_no_proc:
            return {
                "ok": False,
                "error": "no_proc",
                "candidates": [],
                "message": "XiaomiPcManager process not running",
            }

    return {
        "ok": False,
        "error": "device_not_found",
        "candidates": candidates,
        "message": f"no device matching keyword {kw!r} within {timeout}s",
    }
