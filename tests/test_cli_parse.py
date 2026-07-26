# -*- coding: utf-8 -*-
import json
import os
from pathlib import Path

import pytest

@pytest.fixture
def conf_env(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    import importlib
    import midrop_cli.config as cfg
    importlib.reload(cfg)
    import midrop_cli.cli as cli
    importlib.reload(cli)
    return cli

def test_config_set_get_roundtrip(conf_env, capsys):
    cli = conf_env
    code = cli.main(["config", "set", "default_device", "Fold", "--format", "json"])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    code = cli.main(["config", "get", "default_device", "--format", "json"])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["value"] == "Fold"

def test_config_path(conf_env, capsys, tmp_path):
    cli = conf_env
    code = cli.main(["config", "path", "--format", "json"])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert "midrop" in out["path"].replace("\\", "/")

def test_send_missing_file(conf_env, capsys):
    cli = conf_env
    # 先设 default 避免 device_required
    cli.main(["config", "set", "default_device", "Fold", "--format", "json"])
    capsys.readouterr()
    code = cli.main(["send", "Z:\\no_such_midrop_file_zzz.dat", "--format", "json"])
    assert code == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False
    assert out["error"] == "file_not_found"

def test_send_device_required(conf_env, capsys, tmp_path):
    cli = conf_env
    f = tmp_path / "a.txt"
    f.write_text("x", encoding="utf-8")
    code = cli.main(["send", str(f), "--format", "json"])
    assert code == 1
    out = json.loads(capsys.readouterr().out)
    assert out["error"] == "device_required"


def test_config_send_mode(conf_env, capsys):
    cli = conf_env
    code = cli.main(["config", "set", "send_mode", "rpa", "--format", "json"])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["value"] == "rpa"
    code = cli.main(["config", "get", "send_mode", "--format", "json"])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["value"] == "rpa"
