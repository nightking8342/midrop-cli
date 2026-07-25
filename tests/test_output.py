# -*- coding: utf-8 -*-
import json
from midrop_cli.output import emit

def test_emit_json(capsys):
    emit({"ok": True, "action": "send", "device_matched": "我的Xiaomi MIX Fold 3"}, "json")
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["ok"] is True
    assert "Fold" in data["device_matched"]

def test_emit_text_success(capsys):
    emit({"ok": True, "action": "send", "file": "a.txt", "device_matched": "Fold", "clicked": True}, "text")
    out = capsys.readouterr().out
    assert "ok" in out.lower() or "成功" in out or "send" in out
