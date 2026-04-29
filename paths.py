# omega/paths.py
from __future__ import annotations

import os
from pathlib import Path

# omega/paths.py is inside /omega, so project root is parent of that folder
APP_ROOT = Path(__file__).resolve().parents[1]

UI_PATH = APP_ROOT / "ui" / "main_v2.ui"
MEDIA_DIR = APP_ROOT / "Media"
SHOWS_DIR = MEDIA_DIR / "Shows"

CONFIG_DIR = APP_ROOT / "config"
SOURCES_PATH = CONFIG_DIR / "sources.json"


def ensure_mpv_dll_on_path():
    root = str(APP_ROOT.resolve())

    # Remove empty / relative entries that confuse ctypes.find_library
    parts = []
    for p in os.environ.get("PATH", "").split(os.pathsep):
        p = (p or "").strip()
        if not p:
            continue
        if p in (".",):
            continue
        parts.append(p)

    os.environ["PATH"] = root + os.pathsep + os.pathsep.join(parts)

    # On Windows + Python 3.8+, this helps DLL resolution a lot
    if hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(root)
        except Exception:
            pass
