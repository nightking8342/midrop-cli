# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import os
from typing import Any

from midrop_cli import __version__
from midrop_cli import config as cfg
from midrop_cli.output import default_format, emit

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_ENV = 2
EXIT_TIMEOUT = 3
EXIT_CLICK = 4


def build_parser() -> argparse.ArgumentParser:
    fmt = argparse.ArgumentParser(add_help=False)
    fmt.add_argument("--format", choices=("json", "text"), default=None)

    p = argparse.ArgumentParser(prog="midrop", description="Xiaomi MiDrop CLI")
    p.add_argument("--version", action="version", version=f"midrop {__version__}")
    p.add_argument("--format", choices=("json", "text"), default=None)
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("send", help="Send file via MiDrop (default: noui)", parents=[fmt])
    s.add_argument("path")
    s.add_argument("--device", default=None, help="alias Fold/Pad, 0xHEX, or decimal id")
    s.add_argument(
        "--mode",
        choices=("noui", "rpa"),
        default=None,
        help="noui=Frida in-process (default); rpa=legacy UIA click",
    )
    s.add_argument("--timeout", type=float, default=12.0)
    s.add_argument("--hold", type=float, default=None)
    s.add_argument(
        "--no-click",
        action="store_true",
        help="rpa only: show picker without clicking",
    )

    d = sub.add_parser(
        "devices",
        help="List devices with ids (live) or UIA names",
        parents=[fmt],
    )
    d.add_argument("--timeout", type=float, default=12.0)
    d.add_argument(
        "--source",
        choices=("live", "uia"),
        default="live",
        help="live=Frida in-process ids (default); uia=popup names only",
    )

    sub.add_parser("doctor", help="Check environment", parents=[fmt])

    dae = sub.add_parser(
        "daemon",
        help="Stay attached to XiaomiPcManager and maintain live device state",
        parents=[fmt],
    )
    dae.add_argument("--refresh", type=float, default=5.0, help="state heartbeat seconds")

    c = sub.add_parser("config", help="Manage config", parents=[fmt])
    csub = c.add_subparsers(dest="config_op", required=True)
    csub.add_parser("path", parents=[fmt])
    csub.add_parser("list", parents=[fmt])
    g = csub.add_parser("get", parents=[fmt])
    g.add_argument("key")
    st = csub.add_parser("set", parents=[fmt])
    st.add_argument("key")
    st.add_argument("value")
    return p


def _fmt(args) -> str:
    return args.format or default_format()


def cmd_config(args) -> int:
    op = args.config_op
    if op == "path":
        emit({"ok": True, "action": "config", "op": "path", "path": str(cfg.config_path())}, _fmt(args))
        return EXIT_OK
    if op == "list":
        emit({"ok": True, "action": "config", "op": "list", "config": cfg.load()}, _fmt(args))
        return EXIT_OK
    if op == "get":
        try:
            val = cfg.get(args.key)
        except ValueError as e:
            emit({"ok": False, "action": "config", "error": "config_error", "message": str(e)}, _fmt(args))
            return EXIT_ERROR
        emit({"ok": True, "action": "config", "op": "get", "key": args.key, "value": val}, _fmt(args))
        return EXIT_OK
    if op == "set":
        try:
            data = cfg.set_key(args.key, args.value)
        except (ValueError, TypeError) as e:
            emit({"ok": False, "action": "config", "error": "config_error", "message": str(e)}, _fmt(args))
            return EXIT_ERROR
        emit(
            {
                "ok": True,
                "action": "config",
                "op": "set",
                "key": args.key,
                "value": data[args.key],
                "config": data,
            },
            _fmt(args),
        )
        return EXIT_OK
    return EXIT_ERROR


def cmd_send(args) -> int:
    path = os.path.abspath(args.path)
    conf = cfg.load()
    if not os.path.isfile(path):
        emit(
            {
                "ok": False,
                "action": "send",
                "error": "file_not_found",
                "message": f"file not found: {path}",
                "file": path,
            },
            _fmt(args),
        )
        return EXIT_ERROR
    device = args.device if args.device is not None else conf.get("default_device") or ""
    if not str(device).strip():
        emit(
            {
                "ok": False,
                "action": "send",
                "error": "device_required",
                "message": "pass --device or set default_device",
                "file": path,
            },
            _fmt(args),
        )
        return EXIT_ERROR

    mode = args.mode if args.mode is not None else conf.get("send_mode") or "noui"

    try:
        from midrop_cli.core import send as send_mod
    except ImportError:
        emit(
            {
                "ok": False,
                "action": "send",
                "error": "not_implemented",
                "message": "core.send not ready",
                "file": path,
            },
            _fmt(args),
        )
        return EXIT_ERROR

    result = send_mod.send_file(
        path,
        device_query=str(device),
        timeout=args.timeout,
        hold=args.hold if args.hold is not None else float(conf["hold_seconds"]),
        no_click=bool(args.no_click),
        launch_path=conf["launch_path"],
        mode=str(mode),
        cfg_data=conf,
    )
    emit(result, _fmt(args))
    return int(result.get("exit_code", EXIT_ERROR if not result.get("ok") else EXIT_OK))


def cmd_devices(args) -> int:
    source = getattr(args, "source", None) or "live"
    if source == "uia":
        try:
            from midrop_cli.core import send as send_mod
        except ImportError:
            emit(
                {
                    "ok": False,
                    "action": "devices",
                    "error": "not_implemented",
                    "message": "core not ready",
                },
                _fmt(args),
            )
            return EXIT_ERROR
        result = send_mod.list_devices_flow(
            timeout=args.timeout,
            launch_path=cfg.load()["launch_path"],
        )
        if isinstance(result, dict):
            result.setdefault("source", "uia")
    else:
        try:
            from midrop_cli.core.live_devices import list_devices_live
        except ImportError:
            emit(
                {
                    "ok": False,
                    "action": "devices",
                    "source": "live",
                    "error": "not_implemented",
                    "message": "live_devices not ready",
                },
                _fmt(args),
            )
            return EXIT_ERROR
        result = list_devices_live(timeout=args.timeout)
    emit(result, _fmt(args))
    return int(result.get("exit_code", EXIT_ERROR if not result.get("ok") else EXIT_OK))


def cmd_doctor(args) -> int:
    try:
        from midrop_cli.core.doctor import run_doctor
    except ImportError:
        emit({"ok": False, "action": "doctor", "error": "not_implemented", "message": "doctor not ready"}, _fmt(args))
        return EXIT_ERROR
    result = run_doctor(cfg.load())
    emit(result, _fmt(args))
    return EXIT_OK if result.get("ok") and result.get("healthy") else EXIT_ENV


def cmd_daemon(args) -> int:
    try:
        from midrop_cli.core.daemon import run_daemon
    except ImportError as e:
        emit(
            {
                "ok": False,
                "action": "daemon",
                "error": "environment",
                "message": f"daemon not ready: {e}",
            },
            _fmt(args),
        )
        return EXIT_ERROR
    return run_daemon(refresh_every=float(args.refresh))


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "config":
        return cmd_config(args)
    if args.command == "send":
        return cmd_send(args)
    if args.command == "devices":
        return cmd_devices(args)
    if args.command == "doctor":
        return cmd_doctor(args)
    if args.command == "daemon":
        return cmd_daemon(args)
    return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
