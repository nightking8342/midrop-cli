# -*- coding: utf-8 -*-
"""Mode dispatch: silent is default; noui/rpa still reachable."""
from __future__ import annotations

import midrop_cli.core.send as send_mod


def _stub(monkeypatch, calls):
    def fake_silent(path, **kw):
        calls.append(("silent", path, kw))
        return {"ok": True, "mode": "silent", "exit_code": 0}

    def fake_noui(path, **kw):
        calls.append(("noui", path, kw))
        return {"ok": True, "mode": "noui", "exit_code": 0}

    def fake_rpa(path, **kw):
        calls.append(("rpa", path, kw))
        return {"ok": True, "mode": "rpa", "exit_code": 0}

    import midrop_cli.core.noui as noui_mod
    import midrop_cli.core.silent as silent_mod

    monkeypatch.setattr(silent_mod, "send_file_silent", fake_silent)
    monkeypatch.setattr(noui_mod, "send_file_noui", fake_noui)
    monkeypatch.setattr(send_mod, "send_file_rpa", fake_rpa)


def test_default_mode_is_silent(monkeypatch):
    calls = []
    _stub(monkeypatch, calls)
    out = send_mod.send_file("a.txt", device_query="Fold")
    assert out["mode"] == "silent"
    assert calls[0][0] == "silent"


def test_explicit_noui_still_works(monkeypatch):
    calls = []
    _stub(monkeypatch, calls)
    out = send_mod.send_file("a.txt", device_query="Fold", mode="noui")
    assert out["mode"] == "noui"


def test_explicit_rpa_still_works(monkeypatch):
    calls = []
    _stub(monkeypatch, calls)
    out = send_mod.send_file("a.txt", device_query="Fold", mode="rpa")
    assert out["mode"] == "rpa"


def test_legacy_mode_aliases_map_to_rpa(monkeypatch):
    for alias in ("ui", "legacy"):
        calls = []
        _stub(monkeypatch, calls)
        out = send_mod.send_file("a.txt", device_query="Fold", mode=alias)
        assert out["mode"] == "rpa", alias


def test_unknown_mode_falls_back_to_silent(monkeypatch):
    calls = []
    _stub(monkeypatch, calls)
    out = send_mod.send_file("a.txt", device_query="Fold", mode="bogus")
    assert out["mode"] == "silent"


def test_silent_receives_retry_and_confirm_args(monkeypatch):
    calls = []
    _stub(monkeypatch, calls)
    send_mod.send_file("a.txt", device_query="Fold", mode="silent", retry=3)
    kw = calls[0][2]
    assert kw["retry"] == 3
