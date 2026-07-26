# -*- coding: utf-8 -*-
"""midrop 配置：%LOCALAPPDATA%\\midrop\\config.json"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ALLOWED_KEYS = (
    "default_device",
    "launch_path",
    "hold_seconds",
    "send_mode",
    "device_map",
)

DEFAULTS: dict[str, Any] = {
    "default_device": "",
    "launch_path": r"C:\Program Files\MI\XiaomiPCManager\Launch.exe",
    "hold_seconds": 8,
    "send_mode": "noui",  # noui | rpa
    "device_map": "",  # optional JSON object alias->id
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
    try:
        data["hold_seconds"] = int(data["hold_seconds"])
    except (TypeError, ValueError):
        data["hold_seconds"] = DEFAULTS["hold_seconds"]
    if data.get("default_device") is None:
        data["default_device"] = ""
    mode = str(data.get("send_mode") or "noui").strip().lower()
    if mode not in ("noui", "rpa", "ui", "legacy"):
        mode = "noui"
    if mode in ("ui", "legacy"):
        mode = "rpa"
    data["send_mode"] = mode
    if data.get("device_map") is None:
        data["device_map"] = ""
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
    elif key == "send_mode":
        m = value.strip().lower()
        if m in ("ui", "legacy"):
            m = "rpa"
        if m not in ("noui", "rpa"):
            raise ValueError("send_mode must be noui or rpa")
        data[key] = m
    else:
        data[key] = value
    d = config_dir()
    d.mkdir(parents=True, exist_ok=True)
    config_path().write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return data
