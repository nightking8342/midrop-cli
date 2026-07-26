# -*- coding: utf-8 -*-
"""Resolve device query string to MiDrop device_id (uint32 / Lyra hex)."""
from __future__ import annotations

import json
from typing import Any

# Measured on this machine (XiaomiPCManager 5.5.x). Override via config device_map JSON.
DEFAULT_DEVICE_MAP: dict[str, int] = {
    "fold": 0xD16E4A0F,
    "phone": 0xD16E4A0F,
    "mix": 0xD16E4A0F,
    "pad": 0x347FBBC5,
    "tablet": 0x347FBBC5,
}

DEVICE_LABELS: dict[int, str] = {
    0xD16E4A0F: "Xiaomi MIX Fold 3",
    0x347FBBC5: "Xiaomi Pad 7S Pro",
}


def _parse_id(value: str | int) -> int:
    if isinstance(value, int):
        return value & 0xFFFFFFFF
    s = str(value).strip()
    if s.lower().startswith("0x"):
        return int(s, 16) & 0xFFFFFFFF
    if s.isdigit() or (s.startswith("-") and s[1:].isdigit()):
        return int(s, 10) & 0xFFFFFFFF
    # bare hex without 0x (e.g. D16E4A0F)
    try:
        return int(s, 16) & 0xFFFFFFFF
    except ValueError as e:
        raise ValueError(f"invalid device id: {value!r}") from e


def load_device_map(cfg_data: dict[str, Any] | None = None) -> dict[str, int]:
    """Merge defaults with optional config device_map JSON string."""
    out = dict(DEFAULT_DEVICE_MAP)
    if not cfg_data:
        return out
    raw = cfg_data.get("device_map") or ""
    if not str(raw).strip():
        return out
    try:
        obj = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(obj, dict):
            for k, v in obj.items():
                out[str(k).strip().lower()] = _parse_id(v)
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    return out


def resolve_device_id(
    query: str,
    cfg_data: dict[str, Any] | None = None,
) -> tuple[int, str]:
    """
    Return (device_id, label).

    Accepts: alias (Fold/Pad), 0xHEX, decimal, bare hex.
    """
    q = (query or "").strip()
    if not q:
        raise ValueError("empty device query")
    key = q.lower()
    m = load_device_map(cfg_data)
    if key in m:
        did = m[key]
        return did, DEVICE_LABELS.get(did, q)
    # substring alias match (e.g. "MIX Fold" contains fold)
    for alias, did in m.items():
        if alias in key or key in alias:
            return did, DEVICE_LABELS.get(did, q)
    did = _parse_id(q)
    return did, DEVICE_LABELS.get(did, f"0x{did:X}")
