# omega/ui/qt_utils.py
from __future__ import annotations

from typing import Optional, Type, Any

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QWidget


def dprint(*args) -> None:
    print("[DEBUG]", *args)


def safe_find(parent: QObject, name: str, cls=None, required: bool = False):
    """
    Find a Qt child widget by objectName safely.

    If required=True and missing:
      - raise immediately so you discover UI mismatch fast
    """
    w = parent.findChild(cls or QWidget, name)
    if w is None and required:
        raise RuntimeError(f"Required widget not found: {name}")
    return w


def fmt_ms(ms: int) -> str:
    if ms < 0:
        ms = 0
    sec = ms // 1000
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"
