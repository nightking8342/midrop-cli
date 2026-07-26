# -*- coding: utf-8 -*-
"""
Live device enumeration by tailing MiDrop's own online snapshot log line.

Xiaomi PC Manager already writes the authoritative online device set to
smart_share_log.txt on every add/remove:

    [smart_share][device_mgr][lyra] current lyra devices [<HEX>:[types...], ...], ui valid 1

Reading the last such line gives seconds-old truth with no injection, no
popup, no daemon. If the log line is stale (device state changed after the
last write) the caller will discover it on the next real interaction.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any

from midrop_cli.core.devices import DEVICE_LABELS as _CORE_LABELS

EXIT_OK = 0
EXIT_ENV = 2
EXIT_TIMEOUT = 3

DEVICE_LABELS = dict(_CORE_LABELS)

LYRA_LOG = r"C:\ProgramData\MI\AIoT\Log\smart_share_log.txt"
# Tail window in bytes when reading the log. Large enough to always contain
# the last 'current lyra devices' entry even in busy periods.
_TAIL_BYTES = 400_000
_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
_ENTRY_RE = re.compile(r"([0-9A-Fa-f]{8}):\[([0-9,\s]*)\]")


def _elapsed_ms(t0: float) -> int:
    return int((time.time() - t0) * 1000)


def _read_tail(path: str, nbytes: int = _TAIL_BYTES) -> str:
    try:
        size = os.path.getsize(path)
    except OSError:
        return ""
    with open(path, "rb") as f:
        f.seek(max(0, size - nbytes))
        return f.read().decode("utf-8", "replace")


def _parse_line_ts(line: str) -> float | None:
    m = _TS_RE.match(line)
    if not m:
        return None
    try:
        return time.mktime(time.strptime(m.group(1), "%Y-%m-%d %H:%M:%S"))
    except (ValueError, OverflowError):
        return None


def _find_last_snapshot(tail: str) -> tuple[str, float | None] | None:
    """Return (body_inside_outer_brackets, unix_timestamp) of the last snapshot."""
    last: tuple[str, float | None] | None = None
    for line in tail.splitlines():
        idx = line.find("current lyra devices ")
        if idx < 0:
            continue
        rest = line[idx + len("current lyra devices ") :]
        if not rest.startswith("["):
            continue
        depth = 0
        end = -1
        for i, c in enumerate(rest):
            if c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end <= 1:
            continue
        body = rest[1 : end - 1]
        last = (body, _parse_line_ts(line))
    return last


def _parse_devices(body: str) -> list[dict[str, Any]]:
    devices: list[dict[str, Any]] = []
    for m in _ENTRY_RE.finditer(body):
        id_hex = m.group(1).upper()
        types_str = m.group(2)
        types = [int(x.strip()) for x in types_str.split(",") if x.strip()]
        did = int(id_hex, 16)
        devices.append(
            {
                "name": DEVICE_LABELS.get(did) or f"device_{id_hex}",
                "id_hex": id_hex,
                "device_id": did,
                "types": types,
            }
        )
    devices.sort(key=lambda x: (x["device_id"] not in DEVICE_LABELS, x["device_id"]))
    return devices


def list_devices_live(timeout: float = 5.0) -> dict[str, Any]:
    """
    Read the last 'current lyra devices [...]' line from smart_share_log.txt
    and parse it into a live device list.
    """
    t0 = time.time()
    if not Path(LYRA_LOG).is_file():
        return {
            "ok": False,
            "action": "devices",
            "source": "log",
            "devices": [],
            "error": "environment",
            "message": f"log not found: {LYRA_LOG}",
            "elapsed_ms": _elapsed_ms(t0),
            "exit_code": EXIT_ENV,
        }
    try:
        tail = _read_tail(LYRA_LOG)
    except OSError as e:
        return {
            "ok": False,
            "action": "devices",
            "source": "log",
            "devices": [],
            "error": "environment",
            "message": f"cannot read log: {e}",
            "elapsed_ms": _elapsed_ms(t0),
            "exit_code": EXIT_ENV,
        }
    snap = _find_last_snapshot(tail)
    if not snap:
        return {
            "ok": False,
            "action": "devices",
            "source": "log",
            "devices": [],
            "error": "device_not_found",
            "message": "no 'current lyra devices' entry in log tail",
            "elapsed_ms": _elapsed_ms(t0),
            "exit_code": EXIT_TIMEOUT,
        }
    body, ts = snap
    devices = _parse_devices(body)
    age = round(time.time() - ts, 1) if ts is not None else None
    return {
        "ok": True,
        "action": "devices",
        "source": "log",
        "snapshot_body": body,
        "snapshot_age_sec": age,
        "devices": devices,
        "elapsed_ms": _elapsed_ms(t0),
        "exit_code": EXIT_OK,
    }
