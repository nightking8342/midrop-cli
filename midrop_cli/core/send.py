# -*- coding: utf-8 -*-
"""Send dispatcher: default silent, menu as fallback."""
from __future__ import annotations

from typing import Any

__all__ = ["send_file", "normalize_mode", "resolve_mode", "MODES", "ALIASES"]

MODES = ("silent", "menu")

# Historical names. ``noui`` predates silent, when "no UI" meant "we never click
# the picker" — it still flashes the window, so it is now called ``menu``.
# ``rpa``/``ui``/``legacy`` was the UIA-click path, deleted entirely; those
# configs fall forward to silent rather than erroring on load.
ALIASES = {"noui": "menu", "rpa": "silent", "ui": "silent", "legacy": "silent"}


def resolve_mode(mode: str | None) -> str | None:
    """Map a mode name (or historical alias) onto a supported one, else None."""
    m = (mode or "").strip().lower()
    m = ALIASES.get(m, m)
    return m if m in MODES else None


def normalize_mode(mode: str | None) -> str:
    """Like :func:`resolve_mode` but falls back to silent instead of None."""
    return resolve_mode(mode) or "silent"


def send_file(
    path: str,
    device_query: str,
    timeout: float = 12.0,
    hold: float = 8.0,
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
      - menu: Frida via OpenFromMenuWindow; flashes the picker. Fallback only.
    """
    if normalize_mode(mode) == "menu":
        import midrop_cli.core.menu as menu_mod

        return menu_mod.send_file_menu(
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
