# -*- coding: utf-8 -*-
from midrop_cli.core.devices import resolve_device_id


def test_resolve_fold_alias():
    did, label = resolve_device_id("Fold")
    assert did == 0xD16E4A0F
    assert "Fold" in label or "MIX" in label


def test_resolve_pad_alias():
    did, _ = resolve_device_id("Pad")
    assert did == 0x347FBBC5


def test_resolve_hex():
    did, _ = resolve_device_id("0xD16E4A0F")
    assert did == 0xD16E4A0F


def test_resolve_decimal():
    did, _ = resolve_device_id(str(0x347FBBC5))
    assert did == 0x347FBBC5
