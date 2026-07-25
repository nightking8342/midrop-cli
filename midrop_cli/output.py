# -*- coding: utf-8 -*-
"""统一 JSON / text 输出（防 GBK 控制台炸）。"""
from __future__ import annotations

import json
import sys
from typing import Any


def default_format() -> str:
    try:
        return "text" if sys.stdout.isatty() else "json"
    except Exception:
        return "json"


def _safe_print(s: str) -> None:
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        sys.stdout.write(s)
        if not s.endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.flush()
    except UnicodeEncodeError:
        sys.stdout.buffer.write((s + "\n").encode(enc, errors="replace"))
        sys.stdout.flush()


def emit(data: dict[str, Any], fmt: str) -> None:
    if fmt == "json":
        _safe_print(json.dumps(data, ensure_ascii=False, indent=2))
        return
    # text
    if data.get("ok"):
        action = data.get("action", "")
        if action == "send":
            parts = [f"[ok] send {data.get('file', '')}"]
            if data.get("device_matched"):
                parts.append(f"device={data['device_matched']}")
            if data.get("clicked") is True:
                parts.append("clicked")
            elif data.get("clicked") is False:
                parts.append("no-click")
            _safe_print(" ".join(parts))
            if data.get("note"):
                _safe_print(str(data["note"]))
        elif action == "devices":
            devs = data.get("devices") or []
            _safe_print(f"[ok] devices ({len(devs)})")
            for d in devs:
                name = d.get("name", d) if isinstance(d, dict) else d
                _safe_print(f"  - {name}")
        elif action == "doctor":
            _safe_print(f"[ok] doctor healthy={data.get('healthy')}")
            for c in data.get("checks") or []:
                _safe_print(f"  [{c.get('status')}] {c.get('name')}: {c.get('detail', '')}")
        elif action == "config":
            _safe_print(f"[ok] config {data.get('op', '')}")
            if "path" in data:
                _safe_print(str(data["path"]))
            if "config" in data:
                _safe_print(json.dumps(data["config"], ensure_ascii=False, indent=2))
            if "key" in data:
                _safe_print(f"{data['key']}={data.get('value')}")
        else:
            _safe_print(json.dumps(data, ensure_ascii=False))
    else:
        msg = data.get("message") or data.get("error") or "failed"
        _safe_print(f"[x] {data.get('error', 'error')}: {msg}")
        cands = data.get("candidates")
        if cands:
            _safe_print("candidates: " + ", ".join(str(c) for c in cands))
