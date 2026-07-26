# -*- coding: utf-8 -*-
"""Mode dispatch: silent is default, menu is the fallback, old names map forward."""
from __future__ import annotations

import pytest

import midrop_cli.core.send as send_mod
from midrop_cli.core.send import MODES, normalize_mode, resolve_mode


def _stub(monkeypatch, calls):
    def fake_silent(path, **kw):
        calls.append(("silent", path, kw))
        return {"ok": True, "mode": "silent", "exit_code": 0}

    def fake_menu(path, **kw):
        calls.append(("menu", path, kw))
        return {"ok": True, "mode": "menu", "exit_code": 0}

    import midrop_cli.core.menu as menu_mod
    import midrop_cli.core.silent as silent_mod

    monkeypatch.setattr(silent_mod, "send_file_silent", fake_silent)
    monkeypatch.setattr(menu_mod, "send_file_menu", fake_menu)


def test_default_mode_is_silent(monkeypatch):
    calls = []
    _stub(monkeypatch, calls)
    assert send_mod.send_file("a.txt", device_query="Fold")["mode"] == "silent"
    assert calls[0][0] == "silent"


def test_explicit_menu(monkeypatch):
    calls = []
    _stub(monkeypatch, calls)
    assert send_mod.send_file("a.txt", device_query="Fold", mode="menu")["mode"] == "menu"


def test_noui_is_accepted_as_menu_alias(monkeypatch):
    calls = []
    _stub(monkeypatch, calls)
    out = send_mod.send_file("a.txt", device_query="Fold", mode="noui")
    assert out["mode"] == "menu"


@pytest.mark.parametrize("dead", ["rpa", "ui", "legacy"])
def test_removed_rpa_names_fall_forward_to_silent(monkeypatch, dead):
    """rpa is gone; configs still naming it must not crash — they get silent."""
    calls = []
    _stub(monkeypatch, calls)
    assert send_mod.send_file("a.txt", device_query="Fold", mode=dead)["mode"] == "silent"


def test_unknown_mode_falls_back_to_silent(monkeypatch):
    calls = []
    _stub(monkeypatch, calls)
    assert send_mod.send_file("a.txt", device_query="Fold", mode="bogus")["mode"] == "silent"


def test_silent_receives_retry_arg(monkeypatch):
    calls = []
    _stub(monkeypatch, calls)
    send_mod.send_file("a.txt", device_query="Fold", mode="silent", retry=3)
    assert calls[0][2]["retry"] == 3


# --------------------------------------------------------------- mode names

def test_modes_are_exactly_silent_and_menu():
    assert MODES == ("silent", "menu")


def test_resolve_mode_rejects_unknown():
    assert resolve_mode("bogus") is None
    assert resolve_mode("") is None
    assert resolve_mode(None) is None


def test_resolve_mode_maps_aliases():
    assert resolve_mode("noui") == "menu"
    assert resolve_mode("rpa") == "silent"


def test_resolve_mode_is_case_and_space_insensitive():
    assert resolve_mode("  MENU  ") == "menu"
    assert resolve_mode("NoUI") == "menu"


def test_normalize_mode_never_returns_none():
    assert normalize_mode("bogus") == "silent"
    assert normalize_mode(None) == "silent"
