# =========================
# omega/widgets/rail_shell.py
# =========================
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import shiboken6
from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRect, Qt, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QWidget,
)


@dataclass
class SnapConfig:
    """
    Simple snap configuration for horizontal rail scrolling.

    step_px:
        How many pixels count as one card step.

    page_steps:
        How many steps to move on a chevron click.
    """

    step_px: int = 320
    page_steps: int = 6


class RailShell(QWidget):
    """
    Lightweight horizontal rail wrapper used by omega/player/controller.py.

    The controller owns the inner card content. RailShell adds the polish layer:
    - left/right chevrons
    - edge fades
    - overflow detection
    - snap paging
    - gentle animated movement

    The class is careful about teardown because Home rebuilds can delete these
    trees while queued Qt callbacks still exist.
    """

    def __init__(
        self,
        sc: QScrollArea,
        *,
        gutter_px: int = 0,
        fade_px: int = 48,
        snap: Optional[SnapConfig] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)

        self.sc = sc
        self.sc.setParent(self)

        self.rail_id: str = f"rail_{id(self) & 0xFFFF:04x}"

        self._gutter_px = int(max(0, gutter_px))
        self._fade_px = int(max(0, fade_px))
        self._snap = snap or SnapConfig()
        self._overlay_left_inset_px = 0
        self._overlay_right_inset_px = 0
        self._overlay_signature: Optional[Tuple[int, int, int, int, int, int]] = None
        self._overflow_state: Optional[Tuple[bool, bool, bool]] = None
        self._dead = False

        self.destroyed.connect(lambda *_: self._mark_dead())

        root = QHBoxLayout(self)
        root.setContentsMargins(self._gutter_px, 0, self._gutter_px, 0)
        root.setSpacing(0)
        root.addWidget(self.sc, 1)

        self.setObjectName("railShell")
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._btn_left = QToolButton(self)
        self._btn_left.setObjectName("railChevronLeft")
        self._btn_right = QToolButton(self)
        self._btn_right.setObjectName("railChevronRight")

        for button in (self._btn_left, self._btn_right):
            button.setAutoRaise(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setFocusPolicy(Qt.StrongFocus)
            button.setFixedSize(52, 78)
            button.hide()

        self._btn_left.setText("<")
        self._btn_right.setText(">")

        self._btn_left.clicked.connect(self.page_left)
        self._btn_right.clicked.connect(self.page_right)

        self._fade_left = QWidget(self)
        self._fade_left.setObjectName("railEdgeFadeLeft")
        self._fade_left.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._fade_left.hide()

        self._fade_right = QWidget(self)
        self._fade_right.setObjectName("railEdgeFadeRight")
        self._fade_right.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._fade_right.hide()

        self._overflow_refresh_timer = QTimer(self)
        self._overflow_refresh_timer.setSingleShot(True)
        self._overflow_refresh_timer.timeout.connect(self.refresh_overflow_ui)

        # Animation lives on the scroll bar so repeated paging feels smooth.
        self._scroll_anim = QPropertyAnimation(self)
        self._scroll_anim.setTargetObject(self.sc.horizontalScrollBar())
        self._scroll_anim.setPropertyName(b"value")
        self._scroll_anim.setDuration(190)
        self._scroll_anim.setEasingCurve(QEasingCurve.OutCubic)

        self._apply_default_styles()

        self._sb = self.sc.horizontalScrollBar()
        self._sb.valueChanged.connect(lambda *_: self.request_overflow_refresh())
        self._sb.rangeChanged.connect(lambda *_: self.request_overflow_refresh())

        self.request_overflow_refresh()

    # ------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------

    def _mark_dead(self) -> None:
        self._dead = True

    def _is_valid(self, obj) -> bool:
        try:
            return (obj is not None) and shiboken6.isValid(obj)
        except Exception:
            return False

    # ------------------------------------------------------------
    # Public API used by controller
    # ------------------------------------------------------------

    def apply_palette(
        self,
        *,
        primary_hex: str = "#5CA0FF",
        secondary_hex: str = "",
        text_rgba: str = "rgb(245,247,251)",
        opaque: bool = False,
        bg_hex: str = "#05070B",
    ) -> None:
        """
        Let the controller push the active accent color into the rail shell.
        """

        from PySide6.QtGui import QColor

        accent = QColor(str(primary_hex or "#5CA0FF"))
        if not accent.isValid():
            accent = QColor("#5CA0FF")
        accent_rgb = (accent.red(), accent.green(), accent.blue())
        secondary = QColor(str(secondary_hex or primary_hex or "#4FD4B3"))
        if not secondary.isValid():
            secondary = QColor("#4FD4B3")
        secondary_rgb = (secondary.red(), secondary.green(), secondary.blue())
        text = str(text_rgba or "rgba(245,247,251,0.96)")

        bg = QColor(str(bg_hex or "#05070B"))
        if not bg.isValid():
            bg = QColor("#05070B")
        bg_r, bg_g, bg_b = bg.red(), bg.green(), bg.blue()
        btn_bg = f"rgba({bg_r},{bg_g},{bg_b},255)" if opaque else f"rgba({bg_r},{bg_g},{bg_b},176)"

        self._btn_left.setStyleSheet(
            f"""
            QToolButton {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                    stop:0 {btn_bg},
                    stop:1 rgba({bg_r},{bg_g},{bg_b},{255 if opaque else 206}));
                color: {text};
                font-size: 20px;
                font-weight: 900;
                border: 1px solid rgba({accent_rgb[0]}, {accent_rgb[1]}, {accent_rgb[2]}, 78);
                border-radius: 16px;
            }}
            QToolButton:hover, QToolButton:focus {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                    stop:0 rgba({accent_rgb[0]}, {accent_rgb[1]}, {accent_rgb[2]}, 102),
                    stop:1 rgba({secondary_rgb[0]}, {secondary_rgb[1]}, {secondary_rgb[2]}, 84));
                border: 1px solid rgba({accent_rgb[0]}, {accent_rgb[1]}, {accent_rgb[2]}, 225);
            }}
            QToolButton:pressed {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                    stop:0 rgba({accent_rgb[0]}, {accent_rgb[1]}, {accent_rgb[2]}, 136),
                    stop:1 rgba({secondary_rgb[0]}, {secondary_rgb[1]}, {secondary_rgb[2]}, 118));
            }}
            """
        )
        self._btn_right.setStyleSheet(self._btn_left.styleSheet())

        if self._fade_px > 0:
            if opaque:
                fade_start = f"rgba({bg_r},{bg_g},{bg_b},255)"
            else:
                fade_start = "rgba(3,5,10,196)"
            self._fade_left.setStyleSheet(
                f"background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
                f"stop:0 {fade_start},"
                f"stop:0.28 rgba({accent_rgb[0]}, {accent_rgb[1]}, {accent_rgb[2]}, 26),"
                f"stop:0.55 rgba({secondary_rgb[0]}, {secondary_rgb[1]}, {secondary_rgb[2]}, 16),"
                f"stop:1 rgba(0,0,0,0));"
            )
            self._fade_right.setStyleSheet(
                f"background: qlineargradient(x1:1,y1:0,x2:0,y2:0,"
                f"stop:0 {fade_start},"
                f"stop:0.28 rgba({accent_rgb[0]}, {accent_rgb[1]}, {accent_rgb[2]}, 26),"
                f"stop:0.55 rgba({secondary_rgb[0]}, {secondary_rgb[1]}, {secondary_rgb[2]}, 16),"
                f"stop:1 rgba(0,0,0,0));"
            )

    def set_gutter(self, gutter_px: int) -> None:
        self._gutter_px = int(max(0, gutter_px))
        lay = self.layout()
        if lay is not None:
            lay.setContentsMargins(self._gutter_px, 0, self._gutter_px, 0)
        self._overlay_signature = None
        self._overflow_state = None
        self._reposition_overlays()
        self.request_overflow_refresh()

    def set_overlay_insets(self, *, left_px: int = 0, right_px: int = 0) -> None:
        left_px = int(max(0, left_px))
        right_px = int(max(0, right_px))
        if left_px == int(self._overlay_left_inset_px) and right_px == int(self._overlay_right_inset_px):
            return
        self._overlay_left_inset_px = left_px
        self._overlay_right_inset_px = right_px
        self._overlay_signature = None
        self._overflow_state = None
        self._reposition_overlays()
        self.request_overflow_refresh()

    def request_overflow_refresh(self, delay_ms: int = 0) -> None:
        if self._dead or (not self._is_valid(self)):
            return
        timer = getattr(self, "_overflow_refresh_timer", None)
        if not self._is_valid(timer):
            return
        delay = max(0, int(delay_ms))
        if timer.isActive():
            remaining = timer.remainingTime()
            if remaining >= 0 and remaining <= delay:
                return
            timer.stop()
        timer.start(delay)

    def refresh_overflow_ui(self) -> None:
        """
        Show chevrons and fades only when the rail can actually scroll.
        """

        if self._dead or (not self._is_valid(self)):
            return
        if not self._is_valid(getattr(self, "sc", None)):
            return
        if not self._is_valid(getattr(self, "_btn_left", None)):
            return
        if not self._is_valid(getattr(self, "_btn_right", None)):
            return
        if not self._is_valid(getattr(self, "_fade_left", None)):
            return
        if not self._is_valid(getattr(self, "_fade_right", None)):
            return

        try:
            overlay_signature = (
                int(self.width()),
                int(self.height()),
                int(self._gutter_px),
                int(self._fade_px),
                int(self._overlay_left_inset_px),
                int(self._overlay_right_inset_px),
            )
            if overlay_signature != self._overlay_signature:
                self._reposition_overlays()
                self._overlay_signature = overlay_signature

            sb = self.sc.horizontalScrollBar()
            has_overflow = (sb.maximum() - sb.minimum()) > 0
            if not has_overflow:
                state = (False, True, True)
            else:
                at_left = sb.value() <= sb.minimum()
                at_right = sb.value() >= sb.maximum()
                state = (True, bool(at_left), bool(at_right))
            if state == self._overflow_state:
                return
            self._overflow_state = state

            if not has_overflow:
                self._btn_left.hide()
                self._btn_right.hide()
                self._fade_left.hide()
                self._fade_right.hide()
                return

            _has_overflow, at_left, at_right = state
            self._btn_left.setVisible(not at_left)
            self._btn_right.setVisible(not at_right)
            self._fade_left.setVisible((not at_left) and (self._fade_px > 0))
            self._fade_right.setVisible((not at_right) and (self._fade_px > 0))
        except Exception:
            self._overlay_signature = None
            self._overflow_state = None
            if self._is_valid(getattr(self, "_btn_left", None)):
                self._btn_left.hide()
            if self._is_valid(getattr(self, "_btn_right", None)):
                self._btn_right.hide()
            if self._is_valid(getattr(self, "_fade_left", None)):
                self._fade_left.hide()
            if self._is_valid(getattr(self, "_fade_right", None)):
                self._fade_right.hide()

    def page_left(self) -> None:
        self._scroll_steps(-int(self._snap.page_steps))

    def page_right(self) -> None:
        self._scroll_steps(int(self._snap.page_steps))

    def step_left(self) -> None:
        self._scroll_steps(-1)

    def step_right(self) -> None:
        self._scroll_steps(1)

    # ------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------

    def _apply_default_styles(self) -> None:
        self.apply_palette()

    def _scroll_steps(self, steps: int) -> None:
        if self._dead or (not self._is_valid(getattr(self, "sc", None))):
            return
        sb = self.sc.horizontalScrollBar()
        step_px = int(max(1, self._snap.step_px))
        target = int(sb.value() + (steps * step_px))
        target = max(sb.minimum(), min(sb.maximum(), target))

        anim = getattr(self, "_scroll_anim", None)
        if self._is_valid(anim) and self._is_valid(sb):
            try:
                anim.stop()
                anim.setTargetObject(sb)
                anim.setStartValue(int(sb.value()))
                anim.setEndValue(int(target))
                anim.start()
                return
            except Exception:
                pass
        sb.setValue(target)

    def _reposition_overlays(self) -> None:
        if self._dead or (not self._is_valid(self)):
            return
        if not self._is_valid(getattr(self, "_btn_left", None)):
            return
        if not self._is_valid(getattr(self, "_btn_right", None)):
            return
        if not self._is_valid(getattr(self, "_fade_left", None)):
            return
        if not self._is_valid(getattr(self, "_fade_right", None)):
            return

        r: QRect = self.rect()
        h = r.height()

        btn_w = self._btn_left.width()
        btn_h = self._btn_left.height()
        y = max(0, (h - btn_h) // 2)

        left_x = max(0, int(self._gutter_px * 0.35) + int(self._overlay_left_inset_px))
        right_x = max(
            left_x,
            r.width() - btn_w - int(self._gutter_px * 0.35) - int(self._overlay_right_inset_px),
        )

        self._btn_left.move(left_x, y)
        self._btn_right.move(right_x, y)

        if self._fade_px > 0:
            left_fade_x = max(0, int(self._overlay_left_inset_px))
            right_fade_x = max(left_fade_x, r.width() - self._fade_px - int(self._overlay_right_inset_px))
            self._fade_left.setGeometry(left_fade_x, 0, self._fade_px, h)
            self._fade_right.setGeometry(right_fade_x, 0, self._fade_px, h)

        self._btn_left.raise_()
        self._btn_right.raise_()
        self._fade_left.raise_()
        self._fade_right.raise_()

    # ------------------------------------------------------------
    # Qt events
    # ------------------------------------------------------------

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._overlay_signature = None
        self._reposition_overlays()
        self._overflow_state = None
        self.request_overflow_refresh()

    def keyPressEvent(self, event) -> None:
        key = int(event.key())
        if key in {int(Qt.Key_Left), int(Qt.Key_A)}:
            self.page_left()
            event.accept()
            return
        if key in {int(Qt.Key_Right), int(Qt.Key_D)}:
            self.page_right()
            event.accept()
            return
        super().keyPressEvent(event)
