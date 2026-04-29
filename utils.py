# omega/utils.py
from __future__ import annotations

from PySide6.QtCore import QObject


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


def safe_find(win: QObject, name: str, klass):
    w = win.findChild(klass, name)
    if w is None:
        raise RuntimeError(f"Missing required widget objectName='{name}' ({klass.__name__})")
    return w


def find_optional(win: QObject, name: str, klass):
    return win.findChild(klass, name)


def log_optional(name: str, w: QObject | None):
    if w is None:
        print(f"[DEBUG] Optional widget missing: {name} (skipping)")
    else:
        print(f"[DEBUG] Optional widget found: {name} -> {type(w).__name__}")
