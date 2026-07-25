# -*- coding: utf-8 -*-
"""Shared-memory file mapping for Xiaomi MiDrop dropfile protocol."""
from __future__ import annotations

import ctypes
import os
from contextlib import contextmanager
from ctypes import wintypes
from typing import Iterator

MAP_NAME = r"Local\MiDropFileMappingObject"
_PAGE_READWRITE = 0x04
_FILE_MAP_ALL_ACCESS = 0xF001F

_k = ctypes.WinDLL("kernel32", use_last_error=True)
_k.CreateFileMappingW.restype = wintypes.HANDLE
_k.CreateFileMappingW.argtypes = [
    wintypes.HANDLE,
    wintypes.LPVOID,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.LPCWSTR,
]
_k.MapViewOfFile.restype = wintypes.LPVOID
_k.MapViewOfFile.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.c_size_t,
]


@contextmanager
def hold_mapping(filepath: str) -> Iterator[str]:
    """Write absolute path into MiDrop shared memory and keep handles alive in the block."""
    path = os.path.abspath(filepath)
    wide = path + "\x00"
    nbytes = len(wide) * 2
    hmap = _k.CreateFileMappingW(
        ctypes.c_void_p(-1).value, None, _PAGE_READWRITE, 0, nbytes, MAP_NAME
    )
    if not hmap:
        raise OSError(f"CreateFileMappingW failed err={ctypes.get_last_error()}")
    view = _k.MapViewOfFile(hmap, _FILE_MAP_ALL_ACCESS, 0, 0, nbytes)
    if not view:
        raise OSError(f"MapViewOfFile failed err={ctypes.get_last_error()}")
    ctypes.memmove(view, wide.encode("utf-16-le"), nbytes)
    try:
        yield path
    finally:
        # Intentionally keep mapping alive for the whole with-block; drop refs on exit.
        # Explicit UnmapViewOfFile/CloseHandle not required for MiDrop protocol.
        _ = (hmap, view)
