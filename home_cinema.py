# omega/home_cinema.py
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QMainWindow, QWidget

from omega.paths import APP_ROOT


def _pick_bg_image() -> Path | None:
    candidates = [
        APP_ROOT / "ui" / "home_bg.jpg",
        APP_ROOT / "ui" / "home_bg.png",
        APP_ROOT / "ui" / "bg.jpg",
        APP_ROOT / "ui" / "bg.png",
        APP_ROOT / "assets" / "home_bg.jpg",
        APP_ROOT / "assets" / "home_bg.png",
        APP_ROOT / "assets" / "bg.jpg",
        APP_ROOT / "assets" / "bg.png",
    ]
    for p in candidates:
        if p.exists() and p.is_file():
            return p
    return None


def apply_home_cinema_blackout(win: QMainWindow) -> None:
    """
    Goal:
      - No grey chrome / panels on Home.
      - Background image (if present).
      - Cards sit over the background.
      - Do NOT accidentally hide navigation buttons.
    """
    # Force true black window background at palette level
    pal = win.palette()
    pal.setColor(QPalette.Window, QColor(0, 0, 0))
    pal.setColor(QPalette.Base, QColor(0, 0, 0))
    win.setPalette(pal)

    bg = _pick_bg_image()
    bg_css = ""
    if bg:
        # Use forward slashes for Qt stylesheets
        bg_url = str(bg).replace("\\", "/")
        bg_css = f"""
            QWidget#homeRoot {{
                border-image: url("{bg_url}") 0 0 0 0 stretch stretch;
            }}
        """

    # VERY IMPORTANT: avoid broad "QPushButton { color: transparent; }" type rules
    # We keep the blackout narrow and focused to containers.
    win.setStyleSheet(
        (win.styleSheet() or "")
        + f"""
        QMainWindow {{
            background: black;
        }}

        /* Make core container areas transparent/black */
        QWidget#pages,
        QStackedWidget#pages {{
            background: transparent;
        }}

        QWidget#homeRoot,
        QWidget#libraryRoot,
        QWidget#searchRoot,
        QWidget#settingsRoot {{
            background: transparent;
        }}

        /* Scroll areas should not show grey frames */
        QScrollArea {{
            background: transparent;
            border: none;
        }}
        QScrollArea > QWidget > QWidget {{
            background: transparent;
        }}

        /* Frames/panels default to transparent unless explicitly styled */
        QFrame {{
            background: transparent;
            border: none;
        }}

        /* Labels: readable over a background */
        QLabel {{
            color: rgba(255,255,255,210);
            background: transparent;
        }}

        {bg_css}
        """
    )

    # Make sure we didn't hide nav buttons by accident in code somewhere
    for name in ("navHomeBtn", "navLibraryBtn", "navSearchBtn", "navSettingsBtn"):
        b = win.findChild(QWidget, name)
        if b:
            try:
                b.setVisible(True)
            except Exception:
                pass
