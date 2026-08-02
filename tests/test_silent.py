# -*- coding: utf-8 -*-
"""Unit tests for silent-send helpers (pure logic; no Frida, no manager)."""
from __future__ import annotations

import pytest

from midrop_cli.core.silent import (
    _parse_task_id,
    confirm_task_from_log,
    pick_ui_thread,
    thread_hwnds,
)

# ---------------------------------------------------------------- task id

CREATE_LINE = (
    "2026-07-27 02:00:00,453 DEBUG 18956 midrop_business_mgr.cpp 160: "
    "[midrop] HandleCreateSendTask device_id 3513666063, "
    "selected_parent_dir , size 1, TaskFromType 796381760"
)
CREATED_LINE = (
    "2026-07-27 02:00:00,453 DEBUG 18956 task.cpp 641: [midrop] task 25738 created"
)


def test_parse_task_id_from_created_line():
    assert _parse_task_id(CREATE_LINE + "\n" + CREATED_LINE, 3513666063) == 25738


def test_parse_task_id_picks_last_for_device():
    tail = "\n".join(
        [
            CREATE_LINE,
            "2026-07-27 02:00:00,453 DEBUG 18956 task.cpp 641: [midrop] task 111 created",
            CREATE_LINE,
            "2026-07-27 02:01:11,389 DEBUG 18956 task.cpp 641: [midrop] task 222 created",
        ]
    )
    assert _parse_task_id(tail, 3513666063) == 222


def test_parse_task_id_ignores_other_device():
    tail = (
        "2026-07-27 02:00:00,453 DEBUG 18956 midrop_business_mgr.cpp 160: "
        "[midrop] HandleCreateSendTask device_id 880786373, "
        "selected_parent_dir , size 1, TaskFromType 1\n" + CREATED_LINE
    )
    assert _parse_task_id(tail, 3513666063) is None


def test_parse_task_id_none_when_absent():
    assert _parse_task_id("nothing here\n", 3513666063) is None


# ---------------------------------------------------------- confirm task

SUCCESS_TAIL = (
    "2026-07-27 02:00:17,604 INFO 18828 task.cpp 492: "
    "[midrop] task_id 25738 set state 12, kDone\n"
    "2026-07-27 02:00:17,605 DEBUG 16240 midrop_business_mgr.cpp 468: "
    "[midrop] OnTaskSucceed task_id 25738, device_id 3513666063\n"
)
FAIL_TAIL = (
    "2026-07-27 01:58:42,710 DEBUG 17164 midrop_by_lyra_business_mgr.cpp 937: "
    "[midrop][lyra]OnChannelCreateFailed device_id=D16E4A0F "
    'channel_id=696 err_code=15033 MiContGetErrMsg="logical conn remote confirm timeout"\n'
    "2026-07-27 01:58:42,723 INFO 16240 midrop_business_mgr.cpp 487: "
    "[midrop] OnTaskFail task ID 2857, device_id 3513666063, error 404\n"
)


def test_confirm_task_success():
    state, detail = confirm_task_from_log(SUCCESS_TAIL, 25738)
    assert state == "succeeded"
    assert "25738" in detail


def test_confirm_task_failure_reports_error_code():
    state, detail = confirm_task_from_log(FAIL_TAIL, 2857)
    assert state == "failed"
    assert "404" in detail


def test_confirm_task_failure_surfaces_remote_timeout():
    state, detail = confirm_task_from_log(FAIL_TAIL, 2857)
    assert state == "failed"
    assert "15033" in detail or "timeout" in detail.lower()


def test_confirm_task_pending_when_no_terminal_event():
    state, _ = confirm_task_from_log(
        "2026-07-27 02:00:00,453 DEBUG 18956 task.cpp 641: [midrop] task 25738 created\n",
        25738,
    )
    assert state == "pending"


def test_confirm_task_ignores_other_task_id():
    state, _ = confirm_task_from_log(SUCCESS_TAIL, 99999)
    assert state == "pending"


# ------------------------------------------------------------- ui thread

def test_pick_ui_thread_prefers_thread_owning_most_midrop_windows():
    wins = [
        {"tid": 18956, "class": "WinUIDesktopWin32WindowClass", "title": "小米互传"},
        {"tid": 18956, "class": "XiaomiPCManagerTray", "title": ""},
        {"tid": 18956, "class": "WinUIDesktopWin32WindowClass", "title": "小米电脑管家"},
        {"tid": 4092, "class": ".NET-BroadcastEventWindow.3d893c.0", "title": "x"},
        {"tid": 32252, "class": "GDI+ Hook Window Class", "title": "GDI+ Window"},
    ]
    assert pick_ui_thread(wins) == 18956


def test_pick_ui_thread_skips_helper_window_classes():
    # Only helper/IME windows -> no credible UI thread
    wins = [
        {"tid": 4092, "class": "IME", "title": "Default IME"},
        {"tid": 32252, "class": "GDI+ Hook Window Class", "title": "GDI+ Window"},
        {"tid": 36540, "class": "PowerNotificationWindow", "title": ""},
    ]
    assert pick_ui_thread(wins) is None


def test_pick_ui_thread_empty():
    assert pick_ui_thread([]) is None


def test_pick_ui_thread_single_winui():
    wins = [{"tid": 777, "class": "WinUIDesktopWin32WindowClass", "title": "小米互传"}]
    assert pick_ui_thread(wins) == 777


# ------------------------------------------------------- waking the pump

def test_thread_hwnds_filters_by_thread():
    wins = [
        {"hwnd": 1, "tid": 100, "class": "WinUIDesktopWin32WindowClass", "title": "a"},
        {"hwnd": 2, "tid": 100, "class": "XiaomiPCManagerTray", "title": ""},
        {"hwnd": 3, "tid": 999, "class": "IME", "title": "Default IME"},
    ]
    assert thread_hwnds(wins, 100) == [1, 2]


def test_thread_hwnds_empty_for_unknown_thread():
    wins = [{"hwnd": 1, "tid": 100, "class": "X", "title": ""}]
    assert thread_hwnds(wins, 42) == []


def test_pick_ui_thread_still_prefers_real_windows_when_idle():
    """Regression: an idle manager (no visible MiDrop window) must still resolve."""
    wins = [
        {"tid": 7320, "class": "WinUIDesktopWin32WindowClass", "title": "XiaomiPcControlCenterWindow"},
        {"tid": 7320, "class": "XiaomiPCManager", "title": ""},
        {"tid": 7320, "class": "XiaomiPCManagerTray", "title": ""},
        {"tid": 7320, "class": "PowerManage", "title": "PowerManageWindow"},
        {"tid": 7320, "class": "MSCTFIME UI", "title": "MSCTFIME UI"},
        {"tid": 2872, "class": "GDI+ Hook Window Class", "title": "GDI+ Window"},
        {"tid": 10924, "class": ".NET-BroadcastEventWindow.3d893c.0", "title": "x"},
        {"tid": 21708, "class": "PowerNotificationWindow", "title": ""},
    ]
    assert pick_ui_thread(wins) == 7320
