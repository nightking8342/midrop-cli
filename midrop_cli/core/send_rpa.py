# -*- coding: utf-8 -*-
"""
Legacy RPA send path (popup + UIA click).

Preserved as fallback: midrop send --mode rpa
Do not delete — noui is default but RPA remains supported.
"""
from __future__ import annotations

import os
import time
from typing import Any

from midrop_cli.core.launch import trigger_dropfile
from midrop_cli.core.mapping import hold_mapping
from midrop_cli.core.popup import close_popup, ensure_dpi_aware, find_popup
from midrop_cli.core.uia import click_device, list_devices

NOTE = "PC 侧已发起；若手机需确认接收请在手机上同意"

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_ENV = 2
EXIT_TIMEOUT = 3
EXIT_CLICK = 4


def _elapsed_ms(t0: float) -> int:
    return int((time.time() - t0) * 1000)


def send_file_rpa(
    path: str,
    device_query: str,
    timeout: float = 12.0,
    hold: float = 8.0,
    no_click: bool = False,
    launch_path: str = "",
) -> dict[str, Any]:
    """Trigger MiDrop picker and optionally click a matching device (UIA)."""
    t0 = time.time()
    path = os.path.abspath(path)
    base: dict[str, Any] = {
        "action": "send",
        "mode": "rpa",
        "file": path,
        "device_query": device_query,
        "popup_found": False,
        "clicked": False,
    }

    ensure_dpi_aware()
    close_popup()

    try:
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

            if no_click:
                deadline = time.time() + max(0.0, float(timeout))
                popup = None
                while time.time() < deadline:
                    popup = find_popup()
                    if popup:
                        break
                    time.sleep(0.4)
                if popup:
                    time.sleep(max(0.0, float(hold)))
                    return {
                        **base,
                        "ok": True,
                        "popup_found": True,
                        "clicked": False,
                        "elapsed_ms": _elapsed_ms(t0),
                        "exit_code": EXIT_OK,
                    }
                return {
                    **base,
                    "ok": False,
                    "error": "popup_timeout",
                    "message": f"popup not found within {timeout}s",
                    "elapsed_ms": _elapsed_ms(t0),
                    "exit_code": EXIT_TIMEOUT,
                }

            cr = click_device(str(device_query), timeout=float(timeout))
            if cr.get("ok"):
                time.sleep(max(0.0, float(hold)))
                return {
                    **base,
                    "ok": True,
                    "device_matched": cr.get("name"),
                    "popup_found": True,
                    "clicked": True,
                    "elapsed_ms": _elapsed_ms(t0),
                    "note": NOTE,
                    "exit_code": EXIT_OK,
                }

            err = cr.get("error") or "click_failed"
            candidates = list(cr.get("candidates") or [])
            if err == "device_not_found" and candidates:
                time.sleep(max(0.0, float(hold)))

            if err == "device_not_found":
                return {
                    **base,
                    "ok": False,
                    "popup_found": bool(candidates),
                    "error": "device_not_found",
                    "message": cr.get("message")
                    or f"no device matching keyword {device_query!r}",
                    "candidates": candidates,
                    "elapsed_ms": _elapsed_ms(t0),
                    "exit_code": EXIT_TIMEOUT,
                }
            if err == "no_proc":
                return {
                    **base,
                    "ok": False,
                    "error": "environment",
                    "message": cr.get("message")
                    or "XiaomiPcManager process not running",
                    "elapsed_ms": _elapsed_ms(t0),
                    "exit_code": EXIT_ENV,
                }
            return {
                **base,
                "ok": False,
                "popup_found": bool(candidates),
                "error": "click_failed",
                "message": cr.get("message") or "click failed",
                "candidates": candidates,
                "elapsed_ms": _elapsed_ms(t0),
                "exit_code": EXIT_CLICK,
            }
    except OSError as e:
        return {
            **base,
            "ok": False,
            "error": "environment",
            "message": str(e),
            "elapsed_ms": _elapsed_ms(t0),
            "exit_code": EXIT_ENV,
        }


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
