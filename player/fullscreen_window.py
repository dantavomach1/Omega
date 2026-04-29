# =========================
# omega/player/fullscreen_window.py
# FINAL CANONICAL FULLSCREEN IMPLEMENTATION
# =========================

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QWidget

# We now use the advanced implementation from video_surface ONLY.
from omega.player.video_surface import FullscreenVideoWindow as _FullscreenVideoWindow


class FullscreenVideoWindow(_FullscreenVideoWindow):
    """
    Canonical fullscreen window.

    This class intentionally subclasses the advanced implementation
    from video_surface.py so there is only ONE fullscreen behavior
    in the entire application.

    Responsibilities:
    - True borderless fullscreen
    - Native video surface
    - Floating controls with activation zone
    - ESC + double-click exit
    - Clean mpv rebinding lifecycle

    Controller must call:

        fs = FullscreenVideoWindow()
        fs.showFullScreen()

        QTimer.singleShot(
            0,
            lambda: backend.set_wid(int(fs.videoSurface.winId()))
        )

    On exit:
        backend.set_wid(int(embedded_surface.winId()))
    """

    def showEvent(self, e):
        super().showEvent(e)
        self.setWindowState(self.windowState() | Qt.WindowFullScreen)
        self.activateWindow()
        self.raise_()

    def closeEvent(self, e):
        try:
            self.controls.close()
        except Exception:
            pass
        super().closeEvent(e)
