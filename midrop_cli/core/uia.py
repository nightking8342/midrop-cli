# -*- coding: utf-8 -*-
"""
UIA device listing, behind ``midrop devices --source uia``.

Legacy: opens the real picker with a probe file and scrapes display names, so
it flashes a window and yields names only — no device ids. ``--source live``
(reading the manager's own log) supersedes it for every normal use; this
remains only as a cross-check when the log snapshot looks stale.

The UIA *click* path was deleted along with the rpa send mode.
"""
from __future__ import annotations

import os
import subprocess
import time
from typing import Any

from midrop_cli.core.launch import trigger_dropfile
from midrop_cli.core.mapping import hold_mapping
from midrop_cli.core.popup import close_popup, ensure_dpi_aware, find_popup

EXIT_OK = 0
EXIT_ENV = 2
EXIT_TIMEOUT = 3

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


def _elapsed_ms(t0: float) -> int:
    return int((time.time() - t0) * 1000)


def list_devices_flow(
    timeout: float = 12.0,
    launch_path: str = "",
) -> dict[str, Any]:
    """Open picker with a probe file, list devices, then close the popup."""
    t0 = time.time()
    ensure_dpi_aware()
    close_popup()

    temp_dir = os.environ.get("TEMP") or os.environ.get("TMP") or os.getcwd()
    probe = os.path.join(temp_dir, "midrop-devices-probe.txt")
    try:
        with open(probe, "w", encoding="utf-8") as f:
            f.write("midrop devices probe\n")
    except OSError as e:
        return {
            "ok": False,
            "action": "devices",
            "devices": [],
            "error": "environment",
            "message": f"cannot write probe file: {e}",
            "elapsed_ms": _elapsed_ms(t0),
            "exit_code": EXIT_ENV,
        }

    try:
        with hold_mapping(probe):
            try:
                trigger_dropfile(launch_path)
            except FileNotFoundError:
                close_popup()
                return {
                    "ok": False,
                    "action": "devices",
                    "devices": [],
                    "error": "environment",
                    "message": f"Launch.exe not found: {launch_path}",
                    "elapsed_ms": _elapsed_ms(t0),
                    "exit_code": EXIT_ENV,
                }

            names = list_devices(timeout=float(timeout))
            had_popup = find_popup() is not None
            close_popup()

            if not names:
                err = "popup_timeout" if not had_popup else "device_not_found"
                return {
                    "ok": False,
                    "action": "devices",
                    "devices": [],
                    "error": err,
                    "message": (
                        f"no devices within {timeout}s"
                        if err == "device_not_found"
                        else f"popup not found / no devices within {timeout}s"
                    ),
                    "elapsed_ms": _elapsed_ms(t0),
                    "exit_code": EXIT_TIMEOUT,
                }

            return {
                "ok": True,
                "action": "devices",
                "devices": [{"name": n} for n in names],
                "elapsed_ms": _elapsed_ms(t0),
                "exit_code": EXIT_OK,
            }
    except OSError as e:
        close_popup()
        return {
            "ok": False,
            "action": "devices",
            "devices": [],
            "error": "environment",
            "message": str(e),
            "elapsed_ms": _elapsed_ms(t0),
            "exit_code": EXIT_ENV,
        }
