# -*- coding: utf-8 -*-
"""Send dispatcher: default noui, optional rpa fallback."""
from __future__ import annotations

from typing import Any

from midrop_cli.core.send_rpa import list_devices_flow, send_file_rpa

# re-export for devices command
__all__ = ["send_file", "list_devices_flow", "send_file_rpa"]


def send_file(
    path: str,
    device_query: str,
    timeout: float = 12.0,
    hold: float = 8.0,
    no_click: bool = False,
    launch_path: str = "",
    mode: str = "noui",
    cfg_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Send file via MiDrop.

    mode:
      - noui (default): Frida UI-thread HandleCreateSendTask
      - rpa: legacy popup + UIA click
    no_click only applies to rpa (forces picker-only).
    """
    m = (mode or "noui").strip().lower()
    if m in ("rpa", "ui", "legacy"):
        return send_file_rpa(
            path,
            device_query=device_query,
            timeout=timeout,
            hold=hold,
            no_click=no_click,
            launch_path=launch_path,
        )
    # noui ignores no_click (never clicks)
    from midrop_cli.core.noui import send_file_noui

    return send_file_noui(
        path,
        device_query=device_query,
        timeout=timeout,
        hold=hold,
        launch_path=launch_path,
        cfg_data=cfg_data,
    )
