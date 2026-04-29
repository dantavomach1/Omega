# omega/widgets/clickable_surface.py
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget


class ClickableVideoSurface(QWidget):
    """
    Simple QWidget that emits clicked / doubleClicked.
    Useful for embedded MPV video surfaces and later mini-player.
    """
    clicked = Signal()
    doubleClicked = Signal()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.doubleClicked.emit()
        super().mouseDoubleClickEvent(e)
