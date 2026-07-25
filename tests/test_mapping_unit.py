# -*- coding: utf-8 -*-
"""Unit tests for core.mapping / core.launch (no live Xiaomi manager required)."""
from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import pytest


def test_map_name_constant():
    from midrop_cli.core import mapping

    assert mapping.MAP_NAME == r"Local\MiDropFileMappingObject"


def test_hold_mapping_yields_abspath(tmp_path):
    from midrop_cli.core.mapping import hold_mapping

    f = tmp_path / "a.txt"
    f.write_text("x", encoding="utf-8")
    # CreateFileMapping is real on Windows; only assert path normalization.
    with hold_mapping(str(f.name) if False else str(f)) as path:
        assert os.path.isabs(path)
        assert Path(path).resolve() == f.resolve()


def test_hold_mapping_normalizes_relative(tmp_path, monkeypatch):
    from midrop_cli.core.mapping import hold_mapping

    monkeypatch.chdir(tmp_path)
    f = tmp_path / "rel.txt"
    f.write_text("y", encoding="utf-8")
    with hold_mapping("rel.txt") as path:
        assert path == str(f.resolve()) or path == os.path.abspath("rel.txt")
        assert os.path.isabs(path)
        assert os.path.basename(path) == "rel.txt"


def test_trigger_dropfile_missing_raises():
    from midrop_cli.core.launch import trigger_dropfile

    with pytest.raises(FileNotFoundError):
        trigger_dropfile(r"C:\definitely\not\exist\Launch.exe")


def test_trigger_dropfile_calls_popen(tmp_path, monkeypatch):
    from midrop_cli.core import launch

    exe = tmp_path / "Launch.exe"
    exe.write_bytes(b"MZ")
    calls = []

    def fake_popen(args, **kwargs):
        calls.append(args)
        return mock.Mock()

    monkeypatch.setattr(launch.subprocess, "Popen", fake_popen)
    launch.trigger_dropfile(str(exe))
    assert calls == [[str(exe), "--contextmenu_dropfile=1"]]


def test_popup_exports():
    from midrop_cli.core import popup

    assert callable(popup.pid_of)
    assert callable(popup.find_popup)
    assert callable(popup.close_popup)
    assert callable(popup.ensure_dpi_aware)
