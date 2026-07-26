# -*- coding: utf-8 -*-
"""Environment checks for midrop CLI (Launch.exe, process, UIA, config)."""
from __future__ import annotations

import os
import subprocess
from typing import Any

from midrop_cli import config as cfg
from midrop_cli.core.popup import pid_of

_PROC_NAME = "XiaomiPcManager"


def _check_uia() -> tuple[str, str]:
    """Return (status, detail) for UIA assembly loadability via PowerShell."""
    script = (
        "try {"
        "  Add-Type -AssemblyName UIAutomationClient;"
        "  Add-Type -AssemblyName UIAutomationTypes;"
        "  $null = [System.Windows.Automation.AutomationElement]::RootElement;"
        "  Write-Output 'UIA_OK';"
        "} catch {"
        "  Write-Output ('UIA_FAIL ' + $_.Exception.Message);"
        "  exit 1"
        "}"
    )
    try:
        r = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8",
            errors="replace",
        )
        out = ((r.stdout or "") + (r.stderr or "")).replace("\r", "").strip()
        if r.returncode == 0 and "UIA_OK" in out:
            return "ok", "UIAutomation assemblies loadable"
        detail = out or f"powershell exit {r.returncode}"
        if len(detail) > 200:
            detail = detail[:200] + "..."
        return "fail", detail
    except Exception as e:
        return "fail", f"uia probe error: {e}"


def run_doctor(cfg_data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run environment checks. ``ok`` means the check ran; ``healthy`` means criticals pass."""
    from midrop_cli.core.send import normalize_mode

    data = dict(cfg_data) if cfg_data is not None else cfg.load()
    mode = normalize_mode(data.get("send_mode"))
    checks: list[dict[str, str]] = []

    launch_path = str(data.get("launch_path") or "")
    launch_ok = bool(launch_path) and os.path.isfile(launch_path)
    if launch_ok:
        checks.append({"name": "launch_path", "status": "ok", "detail": launch_path})
    else:
        # silent never shells out to Launch.exe; only menu needs it
        checks.append(
            {
                "name": "launch_path",
                "status": "fail" if mode == "menu" else "warn",
                "detail": (
                    f"not found: {launch_path or '(empty)'}"
                    + ("" if mode == "menu" else " (only needed by --mode menu)")
                ),
            }
        )

    pid = pid_of(_PROC_NAME)
    if pid:
        checks.append(
            {
                "name": "process",
                "status": "ok",
                "detail": f"{_PROC_NAME} pid={pid}",
            }
        )
        process_ok = True
    else:
        checks.append(
            {
                "name": "process",
                "status": "fail",
                "detail": f"{_PROC_NAME} not running",
            }
        )
        process_ok = False

    default_device = data.get("default_device") or ""
    if str(default_device).strip():
        checks.append(
            {
                "name": "default_device",
                "status": "ok",
                "detail": str(default_device),
            }
        )
    else:
        checks.append(
            {
                "name": "default_device",
                "status": "warn",
                "detail": "empty (set with: midrop config set default_device <keyword>)",
            }
        )

    uia_status, uia_detail = _check_uia()
    checks.append({"name": "uia", "status": uia_status, "detail": uia_detail})

    # Frida: required by both send modes
    try:
        from midrop_cli.core.silent import frida_available

        frida_ok, frida_detail = frida_available()
    except Exception as e:
        frida_ok, frida_detail = False, str(e)
    checks.append(
        {
            "name": "frida",
            "status": "ok" if frida_ok else "fail",
            "detail": frida_detail if frida_ok else f"not available: {frida_detail}",
        }
    )

    checks.append(
        {
            "name": "send_mode",
            "status": "ok",
            "detail": mode,
        }
    )

    conf_path = cfg.config_path()
    checks.append(
        {
            "name": "config_path",
            "status": "ok",
            "detail": str(conf_path),
        }
    )

    # silent needs only the manager + Frida; menu additionally shells out to Launch.exe.
    # UIA is never critical now — it backs `devices --source uia` alone.
    healthy = process_ok and frida_ok and (launch_ok or mode != "menu")
    return {
        "ok": True,
        "action": "doctor",
        "healthy": healthy,
        "checks": checks,
        "exit_code": 0 if healthy else 2,
    }
