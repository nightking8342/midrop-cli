# -*- coding: utf-8 -*-
import json
import os
from pathlib import Path

import pytest

# 测试前把配置目录指到临时路径
@pytest.fixture
def conf_env(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    # 重新导入以吃到 env（config 模块应在函数内读 env，或提供 config_dir 覆盖）
    import importlib
    import midrop_cli.config as cfg
    importlib.reload(cfg)
    return cfg, tmp_path

def test_load_missing_returns_defaults(conf_env):
    cfg, _ = conf_env
    data = cfg.load()
    assert data["default_device"] == ""
    assert data["hold_seconds"] == 8
    assert "XiaomiPCManager" in data["launch_path"]

def test_set_and_get(conf_env):
    cfg, tmp = conf_env
    cfg.set_key("default_device", "Fold")
    assert cfg.get("default_device") == "Fold"
    p = cfg.config_path()
    assert p.exists()
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert raw["default_device"] == "Fold"

def test_set_hold_seconds_int(conf_env):
    cfg, _ = conf_env
    cfg.set_key("hold_seconds", "10")
    assert cfg.get("hold_seconds") == 10

def test_set_unknown_key_raises(conf_env):
    cfg, _ = conf_env
    with pytest.raises(ValueError):
        cfg.set_key("nope", "x")
