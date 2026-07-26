# -*- coding: utf-8 -*-
"""Send dispatcher: default silent, optional noui / rpa fallbacks."""
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
    mode: str = "silent",
    cfg_data: dict[str, Any] | None = None,
    retry: int = 1,
    confirm: bool = True,
) -> dict[str, Any]:
    """
    Send file via MiDrop.

    mode:
      - silent (default): Frida on the UI-thread message pump; no popup at all
      - noui: Frida via OpenFromMenuWindow; briefly shows the picker
      - rpa: legacy popup + UIA click
    no_click only applies to rpa (forces picker-only).
    """
    m = (mode or "silent").strip().lower()

    if m in ("rpa", "ui", "legacy"):
        return send_file_rpa(
            path,
            device_query=device_query,
            timeout=timeout,
            hold=hold,
            no_click=no_click,
            launch_path=launch_path,
        )

    if m == "noui":
        # noui ignores no_click (never clicks)
        import midrop_cli.core.noui as noui_mod

        return noui_mod.send_file_noui(
            path,
            device_query=device_query,
            timeout=timeout,
            hold=hold,
            launch_path=launch_path,
            cfg_data=cfg_data,
        )

    import midrop_cli.core.silent as silent_mod

    return silent_mod.send_file_silent(
        path,
        device_query=device_query,
        timeout=timeout,
        hold=hold,
        launch_path=launch_path,
        cfg_data=cfg_data,
        retry=retry,
        confirm=confirm,
    )
