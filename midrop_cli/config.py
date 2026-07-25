# -*- coding: utf-8 -*-
"""midrop 配置：%LOCALAPPDATA%\\midrop\\config.json"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ALLOWED_KEYS = ("default_device", "launch_path", "hold_seconds")

DEFAULTS: dict[str, Any] = {
    "default_device": "",
    "launch_path": r"C:\Program Files\MI\XiaomiPCManager\Launch.exe",
    "hold_seconds": 8,
}


def config_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "midrop"


def config_path() -> Path:
    return config_dir() / "config.json"


def load() -> dict[str, Any]:
    path = config_path()
    data = dict(DEFAULTS)
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for k in ALLOWED_KEYS:
                    if k in raw:
                        data[k] = raw[k]
        except (OSError, json.JSONDecodeError):
            pass
    # 类型修正
    try:
        data["hold_seconds"] = int(data["hold_seconds"])
    except (TypeError, ValueError):
        data["hold_seconds"] = DEFAULTS["hold_seconds"]
    if data.get("default_device") is None:
        data["default_device"] = ""
    return data


def get(key: str) -> Any:
    if key not in ALLOWED_KEYS:
        raise ValueError(f"unknown config key: {key}")
    return load()[key]


def set_key(key: str, value: str) -> dict[str, Any]:
    if key not in ALLOWED_KEYS:
        raise ValueError(f"unknown config key: {key}")
    data = load()
    if key == "hold_seconds":
        data[key] = int(value)
    else:
        data[key] = value
    d = config_dir()
    d.mkdir(parents=True, exist_ok=True)
    config_path().write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return data
