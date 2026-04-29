from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QFileDialog,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from omega.ui.layout_engine import (
    GRID_SCHEMA_VERSION,
    content_bounds,
    grow_canvas_rows_to_items,
    layout_debug_report,
    normalize_layout_items,
    rects_overlap,
    resolve_grid_items,
    validate_layout,
)


DEFAULT_COLORS: Dict[str, str] = {
    "primary": "#5CA0FF",
    "secondary": "#8E7DFF",
    "background": "#07111B",
    "background_alt": "#112033",
    "text": "#F5F8FF",
    "muted_text": "#B7C6D9",
    "card": "#142334",
    "overlay": "#0A1017",
    "highlight": "#C6E4FF",
    "border": "#2E4C67",
    "glow": "#4C8DFF",
    "surface_soft": "#132235",
    "surface_strong": "#0C1521",
    "chip": "#173149",
    "success": "#42D38C",
    "warning": "#F4B35E",
    "danger": "#F36767",
}

DISCOVER_LABELS = {
    "discovered": "Discovered",
    "verified": "Verified",
    "details": "Details",
    "library_hq": "Library Dashboard",
}

DISCOVER_SLOT_LABELS = {
    "top": "Top",
    "left": "Left",
    "right": "Right",
    "bottom": "Bottom",
}

DISCOVER_ACCENTS = {
    "discovered": "#5CA0FF",
    "verified": "#42D38C",
    "details": "#F4B35E",
    "library_hq": "#6D8BFF",
    "session_director": "#F06FB7",
    "search_controls": "#4CC9F0",
}
DISCOVER_CANVAS_COLS = 24
DISCOVER_CANVAS_ROWS = 18


def _discover_label(key: str) -> str:
    token = str(key or "").strip()
    if token.startswith("spacer_"):
        suffix = token.split("_", 1)[1].strip() or "?"
        return f"Spacer {suffix}"
    return DISCOVER_LABELS.get(token, token.replace("_", " ").title())


def _discover_is_spacer(key: str) -> bool:
    return str(key or "").strip().startswith("spacer_")


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _norm_hex(value: Any, fallback: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return fallback
    if not raw.startswith("#"):
        raw = "#" + raw
    if len(raw) != 7:
        return fallback
    try:
        int(raw[1:], 16)
        return raw.upper()
    except Exception:
        return fallback


def _color(value: Any, fallback: str) -> QColor:
    return QColor(_norm_hex(value, fallback))


def _alpha(color: QColor, alpha: int) -> QColor:
    out = QColor(color)
    out.setAlpha(int(_clamp(alpha, 0, 255)))
    return out


def _mix(a: QColor, b: QColor, ratio: float) -> QColor:
    t = _clamp(ratio, 0.0, 1.0)
    return QColor(
        int(round((a.red() * (1.0 - t)) + (b.red() * t))),
        int(round((a.green() * (1.0 - t)) + (b.green() * t))),
        int(round((a.blue() * (1.0 - t)) + (b.blue() * t))),
        int(round((a.alpha() * (1.0 - t)) + (b.alpha() * t))),
    )


def _colors(raw: Dict[str, Any] | None) -> Dict[str, QColor]:
    payload = dict(DEFAULT_COLORS)
    if isinstance(raw, dict):
        for key, value in raw.items():
            payload[str(key)] = _norm_hex(value, payload.get(str(key), "#FFFFFF"))
    return {key: QColor(value) for key, value in payload.items()}


def _rounded_rect_path(rect: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


class ReorderableStripList(QListWidget):
    orderChanged = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setViewMode(QListView.ListMode)
        self.setFlow(QListView.LeftToRight)
        self.setWrapping(False)
        self.setMovement(QListView.Snap)
        self.setResizeMode(QListView.Adjust)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setSpacing(10)
        self.setMinimumHeight(88)

    def dropEvent(self, event) -> None:  # type: ignore[override]
        super().dropEvent(event)
        self.orderChanged.emit()


class _SuffixSafeMixin:
    def _select_value_without_suffix(self) -> None:
        edit = self.lineEdit()
        if edit is None:
            return
        raw = str(edit.text() or "")
        prefix = str(self.prefix() or "")
        suffix = str(self.suffix() or "")
        start = min(len(prefix), len(raw))
        end = max(start, len(raw) - len(suffix))
        length = max(0, end - start)
        if length > 0:
            edit.setSelection(start, length)
        else:
            edit.setCursorPosition(start)

    def focusInEvent(self, event) -> None:  # type: ignore[override]
        super().focusInEvent(event)
        QTimer.singleShot(0, self._select_value_without_suffix)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        super().mousePressEvent(event)
        QTimer.singleShot(0, self._select_value_without_suffix)

    def mouseDoubleClickEvent(self, event) -> None:  # type: ignore[override]
        super().mouseDoubleClickEvent(event)
        QTimer.singleShot(0, self._select_value_without_suffix)

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        # Settings should never silently mutate while the user is just scrolling.
        event.ignore()


class SuffixSafeSpinBox(_SuffixSafeMixin, QSpinBox):
    pass


class SuffixSafeDoubleSpinBox(_SuffixSafeMixin, QDoubleSpinBox):
    pass


class FocusSafeComboBox(QComboBox):
    def wheelEvent(self, event) -> None:  # type: ignore[override]
        view = self.view()
        if view is not None and view.isVisible():
            super().wheelEvent(event)
            return
        event.ignore()


class PassiveWheelSlider(QSlider):
    def wheelEvent(self, event) -> None:  # type: ignore[override]
        # Preserve page scrolling instead of nudging a slider from hover-wheel input.
        event.ignore()


class _BaseMiniPreview(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._colors = _colors(None)
        self.setMinimumSize(320, 220)

    def sizeHint(self) -> QSize:  # type: ignore[override]
        return QSize(420, 260)

    def _draw_shell(self, painter: QPainter) -> tuple[QRectF, Dict[str, QColor]]:
        rect = QRectF(self.rect()).adjusted(8.0, 8.0, -8.0, -8.0)
        colors = self._colors

        painter.setRenderHint(QPainter.Antialiasing, True)

        bg_grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
        bg_grad.setColorAt(0.0, _mix(colors["background"], colors["background_alt"], 0.28))
        bg_grad.setColorAt(0.6, _mix(colors["background"], colors["card"], 0.42))
        bg_grad.setColorAt(1.0, _mix(colors["background_alt"], colors["surface_soft"], 0.4))
        painter.fillPath(_rounded_rect_path(rect, 26.0), bg_grad)
        painter.fillPath(_rounded_rect_path(rect.adjusted(22.0, 18.0, -180.0, -24.0), 120.0), _alpha(colors["primary"], 48))
        painter.fillPath(_rounded_rect_path(rect.adjusted(180.0, 32.0, -24.0, -72.0), 130.0), _alpha(colors["secondary"], 36))
        painter.setPen(QPen(_alpha(colors["highlight"], 40), 1.2))
        painter.drawPath(_rounded_rect_path(rect, 26.0))

        shell = rect.adjusted(16.0, 16.0, -16.0, -16.0)
        shell_grad = QLinearGradient(shell.topLeft(), shell.bottomLeft())
        shell_grad.setColorAt(0.0, _alpha(_mix(colors["surface_soft"], colors["card"], 0.32), 246))
        shell_grad.setColorAt(1.0, _alpha(_mix(colors["surface_strong"], colors["background"], 0.18), 252))
        painter.fillPath(_rounded_rect_path(shell, 22.0), shell_grad)
        painter.setPen(QPen(_alpha(colors["border"], 138), 1.0))
        painter.drawPath(_rounded_rect_path(shell, 22.0))

        top_bar = QRectF(shell.left() + 14.0, shell.top() + 12.0, shell.width() - 28.0, 24.0)
        for index in range(3):
            dot_rect = QRectF(top_bar.left() + (index * 12.0), top_bar.top() + 7.0, 6.0, 6.0)
            painter.fillPath(_rounded_rect_path(dot_rect, 3.0), _alpha(colors["text"], 170 if index == 0 else 76))
        return shell, colors

    def _draw_chip(self, painter: QPainter, rect: QRectF, fill: QColor) -> None:
        painter.fillPath(_rounded_rect_path(rect, min(rect.height() / 2.0, 12.0)), fill)

    def _draw_label_line(self, painter: QPainter, rect: QRectF, fill: QColor, radius: float = 4.0) -> None:
        painter.fillPath(_rounded_rect_path(rect, radius), fill)

    def _draw_card(self, painter: QPainter, rect: QRectF, fill: QColor, border: QColor, radius: float) -> None:
        painter.fillPath(_rounded_rect_path(rect, radius), fill)
        painter.setPen(QPen(border, 1.0))
        painter.drawPath(_rounded_rect_path(rect, radius))


class ThemeMiniPreview(_BaseMiniPreview):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme_name = "Aurora"
        self._glass: Dict[str, Any] = {}
        self._experience: Dict[str, Any] = {}
        self._home_chrome: Dict[str, Any] = {}
        self._customization: Dict[str, Dict[str, Any]] = {}

    def set_preview(
        self,
        *,
        theme_name: str = "",
        colors: Dict[str, Any] | None = None,
        glass: Dict[str, Any] | None = None,
        experience: Dict[str, Any] | None = None,
        home_chrome: Dict[str, Any] | None = None,
        customization: Dict[str, Dict[str, Any]] | None = None,
    ) -> None:
        self._theme_name = str(theme_name or "Aurora")
        self._colors = _colors(colors)
        self._glass = dict(glass or {})
        self._experience = dict(experience or {})
        self._home_chrome = dict(home_chrome or {})
        self._customization = dict(customization or {})
        self.update()

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        shell, colors = self._draw_shell(painter)

        home_cfg = self._customization.get("home", {}) if isinstance(self._customization.get("home"), dict) else {}
        hero_ratio = float(home_cfg.get("hero_space_ratio_of_viewport_h", 0.34) or 0.34)
        max_cards = int(home_cfg.get("visible_cards_max", 7) or 7)
        poster_radius = int((self._customization.get("overlays", {}) if isinstance(self._customization.get("overlays"), dict) else {}).get("poster_radius_px", 24) or 24)
        glass_radius = int(self._glass.get("radius", 24) or 24)
        caption = str(self._experience.get("preview_caption", "") or "").strip() or "flagship atmosphere"
        curation_label = str(self._experience.get("hero_curation_label", "Curated for tonight") or "Curated for tonight").strip()
        eyebrow = str(self._experience.get("hero_default_eyebrow", "TONIGHT'S SPOTLIGHT") or "TONIGHT'S SPOTLIGHT").strip()
        top_variant = str(self._home_chrome.get("top_nav_variant", "default") or "default").replace("_", " ").title()
        dock_variant = str(self._home_chrome.get("dock_variant", "default") or "default").replace("_", " ").title()

        nav_y = shell.top() + 42.0
        nav_x = shell.left() + 16.0
        for index, label in enumerate(("Home", "Library", "Player")):
            width = 44.0 + (len(label) * 3.0)
            chip_rect = QRectF(nav_x, nav_y, width, 22.0)
            fill = _alpha(colors["primary"], 210) if index == 0 else _alpha(colors["chip"], 190)
            self._draw_chip(painter, chip_rect, fill)
            painter.setPen(_alpha(colors["text"], 245 if index == 0 else 168))
            painter.drawText(chip_rect, Qt.AlignCenter, label)
            nav_x += width + 8.0

        content = shell.adjusted(18.0, 72.0, -18.0, -18.0)
        hero_h = max(58.0, min(content.height() * 0.56, content.height() * max(0.26, min(0.54, hero_ratio + 0.06))))
        hero_rect = QRectF(content.left(), content.top(), content.width(), hero_h)
        hero_grad = QLinearGradient(hero_rect.topLeft(), hero_rect.bottomRight())
        hero_grad.setColorAt(0.0, _alpha(_mix(colors["primary"], colors["background_alt"], 0.26), 220))
        hero_grad.setColorAt(1.0, _alpha(_mix(colors["secondary"], colors["background"], 0.42), 210))
        self._draw_card(painter, hero_rect, QColor(hero_grad.stops()[-1][1]), _alpha(colors["highlight"], 52), 18.0)
        painter.fillPath(_rounded_rect_path(hero_rect, 18.0), hero_grad)

        painter.setPen(_alpha(colors["secondary"], 228))
        painter.drawText(
            QRectF(hero_rect.left() + 18.0, hero_rect.top() + 12.0, hero_rect.width() * 0.48, 14.0),
            Qt.AlignLeft | Qt.AlignVCenter,
            eyebrow,
        )
        curation_rect = QRectF(max(hero_rect.left() + 18.0, hero_rect.right() - 132.0), hero_rect.top() + 14.0, 114.0, 18.0)
        self._draw_chip(painter, curation_rect, _alpha(_mix(colors["secondary"], colors["chip"], 0.24), 194))
        painter.setPen(_alpha(colors["text"], 236))
        painter.drawText(curation_rect, Qt.AlignCenter, curation_label[:18].upper())

        title_width = hero_rect.width() * 0.42
        self._draw_label_line(painter, QRectF(hero_rect.left() + 18.0, hero_rect.top() + 34.0, title_width, 11.0), _alpha(colors["text"], 245), 5.0)
        self._draw_label_line(painter, QRectF(hero_rect.left() + 18.0, hero_rect.top() + 52.0, title_width * 0.7, 7.0), _alpha(colors["muted_text"], 190), 4.0)
        self._draw_chip(painter, QRectF(hero_rect.left() + 18.0, hero_rect.bottom() - 34.0, 74.0, 22.0), _alpha(colors["primary"], 225))
        self._draw_chip(painter, QRectF(hero_rect.left() + 100.0, hero_rect.bottom() - 34.0, 62.0, 22.0), _alpha(colors["surface_soft"], 210))

        cards_y = hero_rect.bottom() + 14.0
        cards_h = max(44.0, content.bottom() - cards_y - 26.0)
        cards_count = max(3, min(6, max_cards))
        gap = 8.0
        available_w = content.width() - (gap * float(cards_count - 1))
        card_w = available_w / float(cards_count)
        card_radius = max(8.0, min(16.0, poster_radius * 0.42))
        for index in range(cards_count):
            card_rect = QRectF(content.left() + (index * (card_w + gap)), cards_y, card_w, cards_h)
            poster_fill = _alpha(_mix(colors["card"], colors["primary"], 0.12 + (0.08 * (index / max(1, cards_count - 1)))), 228)
            self._draw_card(painter, card_rect, poster_fill, _alpha(colors["border"], 120), card_radius)
            self._draw_label_line(painter, QRectF(card_rect.left() + 8.0, card_rect.bottom() - 18.0, card_rect.width() * 0.68, 6.0), _alpha(colors["text"], 196))
            self._draw_label_line(painter, QRectF(card_rect.left() + 8.0, card_rect.bottom() - 8.0, card_rect.width() * 0.48, 4.0), _alpha(colors["muted_text"], 138), 3.0)

        palette_y = content.bottom() - 10.0
        swatches = (colors["primary"], colors["secondary"], colors["card"], colors["text"])
        for index, swatch in enumerate(swatches):
            swatch_rect = QRectF(content.right() - ((index + 1) * 18.0) - (index * 6.0), palette_y, 18.0, 8.0)
            self._draw_chip(painter, swatch_rect, _alpha(swatch, 245))

        painter.setPen(_alpha(colors["text"], 228))
        painter.drawText(
            QRectF(shell.left() + 18.0, shell.top() + 12.0, shell.width() - 36.0, 18.0),
            Qt.AlignRight | Qt.AlignVCenter,
            f"{self._theme_name}  |  {caption}",
        )
        painter.setPen(_alpha(colors["muted_text"], 216))
        painter.drawText(
            QRectF(shell.left() + 18.0, shell.bottom() - 20.0, shell.width() - 36.0, 14.0),
            Qt.AlignLeft | Qt.AlignVCenter,
            f"{top_variant} top nav  |  {dock_variant} dock  |  glass {glass_radius}px",
        )


class HomeLayoutMiniPreview(_BaseMiniPreview):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._home_cfg: Dict[str, Any] = {}
        self._overlay_cfg: Dict[str, Any] = {}
        self._inline_cfg: Dict[str, Any] = {}

    def set_preview(
        self,
        *,
        colors: Dict[str, Any] | None = None,
        home: Dict[str, Any] | None = None,
        overlays: Dict[str, Any] | None = None,
        inline: Dict[str, Any] | None = None,
    ) -> None:
        self._colors = _colors(colors)
        self._home_cfg = dict(home or {})
        self._overlay_cfg = dict(overlays or {})
        self._inline_cfg = dict(inline or {})
        self.update()

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        shell, colors = self._draw_shell(painter)

        home = self._home_cfg
        inline = self._inline_cfg
        overlays = self._overlay_cfg

        hero_ratio = float(home.get("hero_space_ratio_of_viewport_h", 0.34) or 0.34)
        min_cards = int(home.get("visible_cards_min", 4) or 4)
        max_cards = int(home.get("visible_cards_max", 7) or 7)
        row_gap_px = int(home.get("row_block_spacing_px", 48) or 48)
        min_gap = int(home.get("card_spacing_min_px", 10) or 10)
        max_gap = int(home.get("card_spacing_max_px", 18) or 18)
        poster_radius = int(overlays.get("poster_radius_px", 24) or 24)
        episode_scale = float(inline.get("episode_card_scale", 1.0) or 1.0)
        episode_gap = int(inline.get("episodes_spacing_px", 12) or 12)

        content = shell.adjusted(18.0, 46.0, -18.0, -18.0)
        available_h = content.height()
        hero_h = max(48.0, min(available_h * 0.48, available_h * _clamp(hero_ratio, 0.18, 0.55)))
        hero_rect = QRectF(content.left(), content.top(), content.width(), hero_h)
        hero_grad = QLinearGradient(hero_rect.topLeft(), hero_rect.bottomRight())
        hero_grad.setColorAt(0.0, _alpha(_mix(colors["primary"], colors["background_alt"], 0.34), 206))
        hero_grad.setColorAt(1.0, _alpha(_mix(colors["surface_soft"], colors["secondary"], 0.24), 206))
        painter.fillPath(_rounded_rect_path(hero_rect, 18.0), hero_grad)
        painter.setPen(QPen(_alpha(colors["border"], 142), 1.0))
        painter.drawPath(_rounded_rect_path(hero_rect, 18.0))
        self._draw_label_line(painter, QRectF(hero_rect.left() + 16.0, hero_rect.top() + 16.0, hero_rect.width() * 0.34, 9.0), _alpha(colors["text"], 236), 5.0)
        self._draw_label_line(painter, QRectF(hero_rect.left() + 16.0, hero_rect.top() + 32.0, hero_rect.width() * 0.22, 6.0), _alpha(colors["muted_text"], 186), 4.0)

        remaining_top = hero_rect.bottom() + 14.0
        card_radius = max(8.0, min(16.0, poster_radius * 0.38))
        row_gap = max(8.0, min(26.0, row_gap_px / 2.6))
        row1_h = max(38.0, (content.bottom() - remaining_top - row_gap - 30.0) * 0.54)
        row2_h = max(24.0, content.bottom() - remaining_top - row_gap - row1_h - 14.0)
        row1_rect = QRectF(content.left(), remaining_top, content.width(), row1_h)
        row2_rect = QRectF(content.left(), row1_rect.bottom() + row_gap, content.width(), row2_h)

        gap1 = max(4.0, min(18.0, min_gap / 1.7))
        row1_count = max(2, min(8, min_cards))
        row1_width = (row1_rect.width() - (gap1 * float(row1_count - 1))) / float(row1_count)
        for index in range(row1_count):
            card = QRectF(row1_rect.left() + (index * (row1_width + gap1)), row1_rect.top(), row1_width, row1_rect.height())
            fill = _alpha(_mix(colors["card"], colors["primary"], 0.10 + (0.02 * index)), 224)
            self._draw_card(painter, card, fill, _alpha(colors["border"], 112), card_radius)

        gap2 = max(4.0, min(14.0, max_gap / 2.2))
        row2_count = max(3, min(9, max_cards))
        row2_width = (row2_rect.width() - (gap2 * float(row2_count - 1))) / float(row2_count)
        ep_h = max(18.0, row2_rect.height() * _clamp(episode_scale, 0.65, 1.2))
        ep_y = row2_rect.top() + max(0.0, (row2_rect.height() - ep_h) / 2.0)
        ep_radius = max(6.0, card_radius - 3.0)
        for index in range(row2_count):
            card = QRectF(row2_rect.left() + (index * (row2_width + gap2)), ep_y, row2_width, ep_h)
            fill = _alpha(_mix(colors["surface_soft"], colors["secondary"], 0.08 + (0.02 * index)), 210)
            self._draw_card(painter, card, fill, _alpha(colors["border"], 94), ep_radius)

        legend_y = shell.bottom() - 22.0
        self._draw_chip(painter, QRectF(shell.left() + 18.0, legend_y, 84.0, 14.0), _alpha(colors["primary"], 196))
        painter.setPen(_alpha(colors["text"], 214))
        painter.drawText(QRectF(shell.left() + 24.0, legend_y - 2.0, 100.0, 18.0), Qt.AlignLeft | Qt.AlignVCenter, f"Min {row1_count}")
        self._draw_chip(painter, QRectF(shell.left() + 118.0, legend_y, 92.0, 14.0), _alpha(colors["secondary"], 160))
        painter.drawText(QRectF(shell.left() + 124.0, legend_y - 2.0, 112.0, 18.0), Qt.AlignLeft | Qt.AlignVCenter, f"Max {row2_count}")
        painter.setPen(_alpha(colors["muted_text"], 188))
        painter.drawText(QRectF(shell.right() - 150.0, legend_y - 2.0, 132.0, 18.0), Qt.AlignRight | Qt.AlignVCenter, f"Rhythm {row_gap_px}px")
        painter.drawText(QRectF(shell.right() - 150.0, legend_y - 18.0, 132.0, 18.0), Qt.AlignRight | Qt.AlignVCenter, f"Episodes {episode_gap}px")


class PlayerChromeMiniPreview(_BaseMiniPreview):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._chrome: Dict[str, Any] = {}

    def set_preview(self, *, colors: Dict[str, Any] | None = None, chrome: Dict[str, Any] | None = None) -> None:
        self._colors = _colors(colors)
        self._chrome = dict(chrome or {})
        self.update()

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        shell, colors = self._draw_shell(painter)

        chrome = dict(self._chrome or {})
        panel = _color(chrome.get("panel"), colors["surface_soft"].name())
        panel_alt = _color(chrome.get("panel_alt"), colors["surface_strong"].name())
        text = _color(chrome.get("text"), colors["text"].name())
        muted = _color(chrome.get("muted_text"), colors["muted_text"].name())
        border = _color(chrome.get("border"), colors["border"].name())
        primary = _color(chrome.get("primary"), colors["primary"].name())
        accent = _color(chrome.get("accent"), colors["secondary"].name())
        danger = _color(chrome.get("danger"), colors["danger"].name())
        bar_top = _color(chrome.get("bar_top"), panel_alt.name())
        bar_bottom = _color(chrome.get("bar_bottom"), colors["background"].name())
        radius = max(8.0, min(18.0, float(int(chrome.get("radius", 14) or 14))))
        surface_alpha = int(chrome.get("surface_alpha", 236) or 236)
        panel_alpha = int(chrome.get("panel_alpha", 228) or 228)

        content = shell.adjusted(18.0, 44.0, -18.0, -18.0)
        video_rect = QRectF(content.left() + 90.0, content.top(), content.width() - 90.0, content.height() - 44.0)
        painter.fillPath(_rounded_rect_path(video_rect, 16.0), _alpha(_mix(colors["background"], colors["background_alt"], 0.32), 245))
        painter.setPen(QPen(_alpha(border, 104), 1.0))
        painter.drawPath(_rounded_rect_path(video_rect, 16.0))

        side_rect = QRectF(content.left(), content.top(), 74.0, content.height() - 44.0)
        self._draw_card(painter, side_rect, _alpha(panel, panel_alpha), _alpha(border, 136), radius)
        self._draw_label_line(painter, QRectF(side_rect.left() + 12.0, side_rect.top() + 12.0, side_rect.width() - 24.0, 8.0), _alpha(text, 228), 4.0)
        self._draw_label_line(painter, QRectF(side_rect.left() + 12.0, side_rect.top() + 28.0, side_rect.width() - 36.0, 5.0), _alpha(muted, 170), 3.0)
        for index, fill in enumerate((primary, accent, QColor("#7F8EA7"), danger)):
            btn_rect = QRectF(side_rect.left() + 12.0, side_rect.top() + 52.0 + (index * 24.0), side_rect.width() - 24.0, 16.0)
            self._draw_chip(painter, btn_rect, _alpha(fill, 200 if index < 2 else 150))

        bottom_rect = QRectF(content.left(), content.bottom() - 32.0, content.width(), 32.0)
        grad = QLinearGradient(bottom_rect.topLeft(), bottom_rect.bottomLeft())
        grad.setColorAt(0.0, _alpha(bar_top, surface_alpha))
        grad.setColorAt(1.0, _alpha(bar_bottom, surface_alpha))
        painter.fillPath(_rounded_rect_path(bottom_rect, radius), grad)
        painter.setPen(QPen(_alpha(border, 148), 1.0))
        painter.drawPath(_rounded_rect_path(bottom_rect, radius))

        seek_rect = QRectF(bottom_rect.left() + 14.0, bottom_rect.top() + 8.0, bottom_rect.width() * 0.42, 4.0)
        self._draw_chip(painter, seek_rect, _alpha(muted, 120))
        self._draw_chip(painter, QRectF(seek_rect.left(), seek_rect.top(), seek_rect.width() * 0.48, seek_rect.height()), _alpha(primary, 230))
        handle = QRectF(seek_rect.left() + (seek_rect.width() * 0.48) - 5.0, seek_rect.top() - 4.0, 10.0, 10.0)
        self._draw_chip(painter, handle, _alpha(text, 240))

        cursor = bottom_rect.left() + 14.0
        for width, fill in ((42.0, panel_alt), (42.0, primary), (42.0, accent), (42.0, danger), (54.0, panel_alt)):
            btn_rect = QRectF(cursor, bottom_rect.top() + 16.0, width, 10.0)
            self._draw_chip(painter, btn_rect, _alpha(fill, 210))
            cursor += width + 8.0

        title_line = QRectF(video_rect.left() + 16.0, video_rect.top() + 16.0, video_rect.width() * 0.34, 9.0)
        self._draw_label_line(painter, title_line, _alpha(text, 225), 5.0)
        self._draw_label_line(painter, QRectF(video_rect.left() + 16.0, video_rect.top() + 32.0, video_rect.width() * 0.2, 6.0), _alpha(muted, 170), 4.0)

        command_rect = QRectF(video_rect.left() + 16.0, video_rect.top() + 52.0, min(150.0, video_rect.width() * 0.36), video_rect.height() - 72.0)
        self._draw_card(painter, command_rect, _alpha(panel_alt, panel_alpha), _alpha(border, 120), radius)
        self._draw_label_line(painter, QRectF(command_rect.left() + 10.0, command_rect.top() + 10.0, command_rect.width() - 28.0, 7.0), _alpha(text, 216), 4.0)
        for row in range(4):
            self._draw_label_line(painter, QRectF(command_rect.left() + 10.0, command_rect.top() + 26.0 + (row * 16.0), command_rect.width() - 20.0, 5.0), _alpha(muted, 120), 3.0)


class PageLayoutMiniPreview(_BaseMiniPreview):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._canvas_cols = int(DISCOVER_CANVAS_COLS)
        self._canvas_rows = int(DISCOVER_CANVAS_ROWS)
        self._slots = {
            "top": "session_director",
            "left": "discovered",
            "right": "verified",
            "bottom": "details",
        }
        self._row_sizes = {"top": 180, "middle": 320, "bottom": 420}
        self._col_sizes = {"left": 360, "right": 360}
        self._items: List[Dict[str, int | str]] = []
        self._component_labels: Dict[str, str] = {}
        self._drawn_item_rects: Dict[str, QRectF] = {}
        self._layout_content_rect = QRectF()
        self._selected_item_id = ""
        self._interactive_editor = False
        self._preview_title = "Page layout"
        self._footer_note = ""

    def set_preview(
        self,
        *,
        colors: Dict[str, Any] | None = None,
        items: Sequence[Dict[str, Any]] | None = None,
        slots: Dict[str, Any] | None = None,
        row_sizes: Dict[str, Any] | None = None,
        col_sizes: Dict[str, Any] | None = None,
        component_labels: Dict[str, str] | None = None,
        canvas_cols: int | None = None,
        canvas_rows: int | None = None,
        title: str | None = None,
        footer_note: str | None = None,
    ) -> None:
        self._colors = _colors(colors)
        self._items = []
        if canvas_cols is not None:
            try:
                self._canvas_cols = max(1, int(canvas_cols))
            except Exception:
                self._canvas_cols = int(DISCOVER_CANVAS_COLS)
        if canvas_rows is not None:
            try:
                self._canvas_rows = max(1, int(canvas_rows))
            except Exception:
                self._canvas_rows = int(DISCOVER_CANVAS_ROWS)
        src_slots = slots or {}
        clean_slots: Dict[str, str] = {}
        for key in DISCOVER_SLOT_LABELS:
            try:
                clean_slots[key] = str(src_slots.get(key, self._slots.get(key, "")) or "").strip()
            except Exception:
                clean_slots[key] = self._slots.get(key, "")
        self._slots = clean_slots

        src_rows = row_sizes or {}
        clean_rows: Dict[str, int] = {}
        for key in ("top", "middle", "bottom"):
            try:
                clean_rows[key] = max(80, int(src_rows.get(key, self._row_sizes.get(key, 240))))
            except Exception:
                clean_rows[key] = self._row_sizes.get(key, 240)
        self._row_sizes = clean_rows

        src_cols = col_sizes or {}
        clean_cols: Dict[str, int] = {}
        for key in ("left", "right"):
            try:
                clean_cols[key] = max(120, int(src_cols.get(key, self._col_sizes.get(key, 320))))
            except Exception:
                clean_cols[key] = self._col_sizes.get(key, 320)
        self._col_sizes = clean_cols
        if items is not None:
            self._items = [self._normalize_item(item, index) for index, item in enumerate(items)]
        self._component_labels = dict(component_labels or {})
        if title is not None:
            self._preview_title = str(title or "Page layout").strip() or "Page layout"
        if footer_note is not None:
            self._footer_note = str(footer_note or "").strip()
        self.update()

    def _normalize_item(self, raw: Dict[str, Any], index: int) -> Dict[str, int | str]:
        source = raw if isinstance(raw, dict) else {}
        component = str(source.get("component", source.get("key", source.get("id", f"item_{index}"))) or f"item_{index}").strip()
        item_id = str(source.get("id", component or f"item_{index}") or f"item_{index}").strip()
        try:
            x = int(source.get("x", 0))
        except Exception:
            x = 0
        try:
            y = int(source.get("y", 0))
        except Exception:
            y = 0
        try:
            w = int(source.get("w", 4))
        except Exception:
            w = 4
        try:
            h = int(source.get("h", 3))
        except Exception:
            h = 3
        x = max(0, min(self._canvas_cols - 1, x))
        y = max(0, min(self._canvas_rows - 1, y))
        w = max(1, min(self._canvas_cols - x, w))
        h = max(1, min(self._canvas_rows - y, h))
        return {"id": item_id, "component": component, "x": x, "y": y, "w": w, "h": h}

    def _items_from_slot_layout(self) -> List[Dict[str, int | str]]:
        row_total = float(
            max(1, int(self._row_sizes.get("top", 1)))
            + max(1, int(self._row_sizes.get("middle", 1)))
            + max(1, int(self._row_sizes.get("bottom", 1)))
        )
        top_rows = max(1, int(round((max(1, int(self._row_sizes.get("top", 1))) / row_total) * self._canvas_rows)))
        bottom_rows = max(1, int(round((max(1, int(self._row_sizes.get("bottom", 1))) / row_total) * self._canvas_rows)))
        middle_rows = max(1, self._canvas_rows - top_rows - bottom_rows)
        while top_rows + middle_rows + bottom_rows > self._canvas_rows:
            if bottom_rows >= top_rows and bottom_rows > 1:
                bottom_rows -= 1
            elif top_rows > 1:
                top_rows -= 1
            else:
                middle_rows = max(1, middle_rows - 1)
        while top_rows + middle_rows + bottom_rows < self._canvas_rows:
            middle_rows += 1

        col_total = float(max(1, int(self._col_sizes.get("left", 1))) + max(1, int(self._col_sizes.get("right", 1))))
        left_cols = max(1, int(round((max(1, int(self._col_sizes.get("left", 1))) / col_total) * self._canvas_cols)))
        right_cols = max(1, self._canvas_cols - left_cols)
        while left_cols + right_cols > self._canvas_cols:
            if right_cols > left_cols and right_cols > 1:
                right_cols -= 1
            elif left_cols > 1:
                left_cols -= 1
            else:
                break
        while left_cols + right_cols < self._canvas_cols:
            right_cols += 1

        return [
            {"id": "top", "component": str(self._slots.get("top", "session_director") or "session_director"), "x": 0, "y": 0, "w": self._canvas_cols, "h": top_rows},
            {"id": "left", "component": str(self._slots.get("left", "discovered") or "discovered"), "x": 0, "y": top_rows, "w": left_cols, "h": middle_rows},
            {"id": "right", "component": str(self._slots.get("right", "verified") or "verified"), "x": left_cols, "y": top_rows, "w": right_cols, "h": middle_rows},
            {"id": "bottom", "component": str(self._slots.get("bottom", "details") or "details"), "x": 0, "y": top_rows + middle_rows, "w": self._canvas_cols, "h": bottom_rows},
        ]

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        shell, colors = self._draw_shell(painter)

        content = shell.adjusted(18.0, 44.0, -18.0, -18.0)
        toolbar = QRectF(content.left(), content.top(), content.width(), 30.0)
        self._draw_card(painter, toolbar, _alpha(colors["surface_soft"], 180), _alpha(colors["border"], 96), 12.0)
        self._draw_label_line(painter, QRectF(toolbar.left() + 12.0, toolbar.top() + 10.0, toolbar.width() * 0.28, 7.0), _alpha(colors["text"], 204), 4.0)
        self._draw_chip(painter, QRectF(toolbar.right() - 82.0, toolbar.top() + 6.0, 66.0, 18.0), _alpha(colors["primary"], 188))

        layout_rect = QRectF(content.left(), toolbar.bottom() + 12.0, content.width(), content.height() - 42.0)
        self._layout_content_rect = layout_rect
        self._drawn_item_rects = {}

        painter.setPen(QPen(_alpha(colors["border"], 58), 1.0))
        for col in range(self._canvas_cols + 1):
            x = layout_rect.left() + ((layout_rect.width() / float(self._canvas_cols)) * float(col))
            painter.drawLine(QPointF(x, layout_rect.top()), QPointF(x, layout_rect.bottom()))
        for row in range(self._canvas_rows + 1):
            y = layout_rect.top() + ((layout_rect.height() / float(self._canvas_rows)) * float(row))
            painter.drawLine(QPointF(layout_rect.left(), y), QPointF(layout_rect.right(), y))

        items = list(self._items or self._items_from_slot_layout())
        selected_id = str(getattr(self, "_selected_item_id", "") or "")
        editable = bool(getattr(self, "_interactive_editor", False))
        grid_gap = 8.0 if editable else 10.0
        cell_w = layout_rect.width() / float(self._canvas_cols)
        cell_h = layout_rect.height() / float(self._canvas_rows)

        for item in items:
            item_id = str(item.get("id", "") or "")
            key = str(item.get("component", "") or "")
            x = int(item.get("x", 0) or 0)
            y = int(item.get("y", 0) or 0)
            w = max(1, int(item.get("w", 1) or 1))
            h = max(1, int(item.get("h", 1) or 1))
            panel_rect = QRectF(
                layout_rect.left() + (float(x) * cell_w) + (grid_gap / 2.0),
                layout_rect.top() + (float(y) * cell_h) + (grid_gap / 2.0),
                max(28.0, (float(w) * cell_w) - grid_gap),
                max(28.0, (float(h) * cell_h) - grid_gap),
            )
            self._drawn_item_rects[item_id] = panel_rect
            accent_hex = DISCOVER_ACCENTS.get(key)
            is_spacer = _discover_is_spacer(key) or not key
            accent = _color(accent_hex or "#7A8699", "#7A8699")
            fill = _alpha(_mix(colors["card"], accent, 0.12 if not is_spacer else 0.04), 228 if not is_spacer else 118)
            border = _alpha(accent if not is_spacer else colors["border"], 154 if not is_spacer else 110)
            self._draw_card(painter, panel_rect, fill, border, 14.0)

            if item_id == selected_id:
                painter.setPen(QPen(_alpha(colors["highlight"], 220), 2.0))
                painter.drawPath(_rounded_rect_path(panel_rect.adjusted(-2.0, -2.0, 2.0, 2.0), 16.0))

            slot_badge = QRectF(panel_rect.left() + 10.0, panel_rect.top() + 10.0, min(84.0, panel_rect.width() - 20.0), 16.0)
            self._draw_chip(painter, slot_badge, _alpha(colors["surface_soft"], 216))
            painter.setPen(_alpha(colors["muted_text"], 208))
            painter.drawText(
                slot_badge.adjusted(8.0, 0.0, -8.0, 0.0),
                Qt.AlignLeft | Qt.AlignVCenter,
                f"{x},{y}  {w}x{h}",
            )

            cap = QRectF(panel_rect.left() + 10.0, panel_rect.top() + 32.0, panel_rect.width() - 20.0, 18.0)
            self._draw_chip(painter, QRectF(cap.left(), cap.top(), max(72.0, cap.width() * 0.52), cap.height()), _alpha(accent if not is_spacer else colors["chip"], 204 if not is_spacer else 142))
            painter.setPen(_alpha(colors["text"], 236))
            label = self._component_labels.get(key) or _discover_label(key)
            painter.drawText(cap.adjusted(8.0, 0.0, -8.0, 0.0), Qt.AlignLeft | Qt.AlignVCenter, label)

            if is_spacer:
                painter.setPen(QPen(_alpha(colors["muted_text"], 124), 1.0, Qt.DashLine))
                painter.drawPath(_rounded_rect_path(panel_rect.adjusted(14.0, 58.0, -14.0, -14.0), 10.0))
            else:
                for row in range(4):
                    line_y = panel_rect.top() + 60.0 + (row * 16.0)
                    line_w = max(18.0, (panel_rect.width() - 24.0) * (0.78 - (row * 0.08)))
                    self._draw_label_line(
                        painter,
                        QRectF(panel_rect.left() + 10.0, line_y, min(line_w, panel_rect.width() - 20.0), 6.0),
                        _alpha(colors["muted_text"], 110),
                        3.0,
                    )

            if editable and item_id == selected_id:
                handle = QRectF(panel_rect.right() - 14.0, panel_rect.bottom() - 14.0, 10.0, 10.0)
                self._draw_chip(painter, handle, _alpha(colors["highlight"], 232))

        painter.setPen(_alpha(colors["muted_text"], 196))
        painter.drawText(
            QRectF(shell.left() + 18.0, shell.top() + 12.0, shell.width() - 36.0, 20.0),
            Qt.AlignLeft | Qt.AlignVCenter,
            str(self._preview_title or "Page layout"),
        )
        footer = str(self._footer_note or "").strip()
        if not footer:
            footer = "Drag boxes and resize from the lower-right corner" if editable else "Grid-based canvas with spacers and future drop-in pieces"
        painter.drawText(QRectF(shell.left() + 18.0, shell.bottom() - 20.0, shell.width() - 36.0, 16.0), Qt.AlignRight | Qt.AlignVCenter, footer)


class _LegacyDiscoverLayoutEditor(PageLayoutMiniPreview):
    layoutChanged = Signal(list)
    selectionChanged = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._interactive_editor = True
        self._drag_mode = ""
        self._drag_item_id = ""
        self._drag_origin_item: Dict[str, int | str] | None = None
        self._drag_origin_pos = QPointF()
        self._undo_history: List[List[Dict[str, int | str]]] = []
        self._redo_history: List[List[Dict[str, int | str]]] = []
        self._drag_start_items: List[Dict[str, int | str]] | None = None
        self.setMinimumSize(360, 700)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

    def sizeHint(self) -> QSize:  # type: ignore[override]
        scaled_height = max(900, int(round(960.0 * (float(self._canvas_rows) / float(DISCOVER_CANVAS_ROWS)))))
        return QSize(520, min(1400, scaled_height))

    def items(self) -> List[Dict[str, int | str]]:
        return [dict(item) for item in self._items]

    def can_undo(self) -> bool:
        return bool(self._undo_history)

    def _items_snapshot(self) -> List[Dict[str, int | str]]:
        return [dict(item) for item in self._items]

    def _push_undo_snapshot(self, snapshot: Sequence[Dict[str, int | str]]) -> None:
        clean = [dict(item) for item in snapshot]
        if self._undo_history and self._undo_history[-1] == clean:
            return
        self._undo_history.append(clean)
        if len(self._undo_history) > 64:
            self._undo_history = self._undo_history[-64:]
        self._redo_history.clear()

    def undo_last_change(self) -> bool:
        if not self._undo_history:
            return False
        current = self._items_snapshot()
        snapshot = self._undo_history.pop()
        if current != snapshot:
            self._redo_history.append(current)
        self._items = self._sanitize_items(snapshot, preferred_id=self._selected_item_id)
        if not any(str(item.get("id", "") or "") == str(self._selected_item_id or "") for item in self._items):
            self._selected_item_id = str(self._items[0].get("id", "") if self._items else "")
        self.selectionChanged.emit(self._selected_item_id)
        self.layoutChanged.emit(self.items())
        self.update()
        return True

    def set_items(
        self,
        items: Sequence[Dict[str, Any]],
        *,
        colors: Dict[str, Any] | None = None,
        component_labels: Dict[str, str] | None = None,
        canvas_cols: int | None = None,
        canvas_rows: int | None = None,
        selected_id: str = "",
        reset_history: bool = True,
    ) -> None:
        if colors is not None:
            self._colors = _colors(colors)
        if canvas_cols is not None:
            try:
                self._canvas_cols = max(1, int(canvas_cols))
            except Exception:
                self._canvas_cols = int(DISCOVER_CANVAS_COLS)
        if canvas_rows is not None:
            try:
                self._canvas_rows = max(1, int(canvas_rows))
            except Exception:
                self._canvas_rows = int(DISCOVER_CANVAS_ROWS)
        self._component_labels = dict(component_labels or {})
        self._items = self._sanitize_items(items, preferred_id=str(selected_id or ""))
        self._selected_item_id = str(selected_id or self._selected_item_id or (self._items[0].get("id", "") if self._items else ""))
        if reset_history:
            self._undo_history.clear()
            self._redo_history.clear()
            self._drag_start_items = None
        self.update()

    def selected_item(self) -> Dict[str, int | str] | None:
        wanted = str(self._selected_item_id or "")
        for item in self._items:
            if str(item.get("id", "") or "") == wanted:
                return dict(item)
        return None

    def select_item(self, item_id: str) -> None:
        self._selected_item_id = str(item_id or "")
        self.selectionChanged.emit(self._selected_item_id)
        self.update()

    def add_item(self, component_key: str) -> str:
        token = str(component_key or "").strip()
        if not token:
            return ""
        if not _discover_is_spacer(token):
            for item in self._items:
                if str(item.get("component", "") or "") == token:
                    existing_id = str(item.get("id", "") or "")
                    self.select_item(existing_id)
                    return existing_id
        self._push_undo_snapshot(self._items_snapshot())
        new_item = self._default_item_for_component(token)
        self._items = self._sanitize_items([*self._items, new_item], preferred_id=str(new_item["id"]))
        self._selected_item_id = str(new_item["id"])
        self.selectionChanged.emit(self._selected_item_id)
        self.layoutChanged.emit(self.items())
        self.update()
        return self._selected_item_id

    def remove_selected_item(self) -> None:
        selected = str(self._selected_item_id or "")
        if not selected:
            return
        self._push_undo_snapshot(self._items_snapshot())
        self._items = [dict(item) for item in self._items if str(item.get("id", "") or "") != selected]
        self._selected_item_id = str(self._items[0].get("id", "") if self._items else "")
        self.selectionChanged.emit(self._selected_item_id)
        self.layoutChanged.emit(self.items())
        self.update()

    def _default_item_for_component(self, component_key: str) -> Dict[str, int | str]:
        defaults = {
            "session_director": {"w": self._canvas_cols, "h": 3},
            "discovered": {"w": 10, "h": 6},
            "verified": {"w": 14, "h": 6},
            "details": {"w": self._canvas_cols, "h": 4},
            "library_hq": {"w": self._canvas_cols, "h": 3},
            "mission_control": {"w": self._canvas_cols, "h": 4},
            "profile_studio": {"w": self._canvas_cols, "h": 6},
            "theme_theater": {"w": self._canvas_cols, "h": 6},
            "shell_actions": {"w": self._canvas_cols, "h": 4},
            "palette_console": {"w": self._canvas_cols, "h": 6},
            "background_stage": {"w": self._canvas_cols, "h": 5},
            "glass_studio": {"w": self._canvas_cols, "h": 4},
            "home_chrome": {"w": self._canvas_cols, "h": 4},
            "player_chrome": {"w": self._canvas_cols, "h": 7},
            "layout_studio": {"w": self._canvas_cols, "h": 6},
        }
        dims = defaults.get(component_key, {"w": 4, "h": 3})
        return self._find_open_position(
            {
                "id": str(component_key),
                "component": str(component_key),
                "x": 0,
                "y": 0,
                "w": int(dims["w"]),
                "h": int(dims["h"]),
            },
            self._items,
        )

    def _normalize_layout_item(self, raw: Dict[str, Any], index: int) -> Dict[str, int | str]:
        source = self._normalize_item(raw, index)
        source["id"] = str(source.get("id", f"item_{index}") or f"item_{index}")
        source["component"] = str(source.get("component", source["id"]) or source["id"])
        return source

    def _rects_overlap(self, left: Dict[str, int | str], right: Dict[str, int | str]) -> bool:
        return not (
            int(left["x"]) + int(left["w"]) <= int(right["x"])
            or int(right["x"]) + int(right["w"]) <= int(left["x"])
            or int(left["y"]) + int(left["h"]) <= int(right["y"])
            or int(right["y"]) + int(right["h"]) <= int(left["y"])
        )

    def _find_open_position(
        self,
        candidate: Dict[str, int | str],
        placed: Sequence[Dict[str, int | str]],
    ) -> Dict[str, int | str]:
        base = dict(candidate)
        max_x = max(0, self._canvas_cols - int(base["w"]))
        max_y = max(0, self._canvas_rows - int(base["h"]))
        start_x = max(0, min(max_x, int(base["x"])))
        start_y = max(0, min(max_y, int(base["y"])))
        positions: List[tuple[int, int]] = []
        for y in range(start_y, max_y + 1):
            for x in range(start_x if y == start_y else 0, max_x + 1):
                positions.append((x, y))
        for y in range(0, start_y + 1):
            for x in range(0, max_x + 1):
                if y == start_y and x >= start_x:
                    continue
                positions.append((x, y))
        for x, y in positions:
            base["x"] = x
            base["y"] = y
            if not any(self._rects_overlap(base, other) for other in placed):
                return dict(base)
        base["x"] = 0
        base["y"] = max_y
        return base

    def _sanitize_items(
        self,
        items: Sequence[Dict[str, Any]],
        *,
        preferred_id: str = "",
    ) -> List[Dict[str, int | str]]:
        normalized = [self._normalize_layout_item(item, index) for index, item in enumerate(items)]
        normalized = [item for item in normalized if str(item.get("component", "") or "").strip()]
        seen_components: set[str] = set()
        deduped: List[Dict[str, int | str]] = []
        for item in normalized:
            component = str(item.get("component", "") or "")
            if not _discover_is_spacer(component):
                if component in seen_components:
                    continue
                seen_components.add(component)
            deduped.append(item)
        ordered = sorted(
            deduped,
            key=lambda item: (0 if str(item.get("id", "") or "") == str(preferred_id or "") else 1),
        )
        placed: List[Dict[str, int | str]] = []
        for item in ordered:
            candidate = dict(item)
            candidate["x"] = max(0, min(self._canvas_cols - 1, int(candidate.get("x", 0) or 0)))
            candidate["y"] = max(0, min(self._canvas_rows - 1, int(candidate.get("y", 0) or 0)))
            candidate["w"] = max(1, min(self._canvas_cols - int(candidate["x"]), int(candidate.get("w", 1) or 1)))
            candidate["h"] = max(1, min(self._canvas_rows - int(candidate["y"]), int(candidate.get("h", 1) or 1)))
            if any(self._rects_overlap(candidate, other) for other in placed):
                candidate = self._find_open_position(candidate, placed)
            placed.append(candidate)
        placed_by_id = {str(item.get("id", "") or ""): item for item in placed}
        return [dict(placed_by_id[str(item.get("id", "") or "")]) for item in deduped if str(item.get("id", "") or "") in placed_by_id]

    def _update_cursor_for_pos(self, pos: QPointF) -> None:
        for item in reversed(self._items):
            item_id = str(item.get("id", "") or "")
            rect = self._drawn_item_rects.get(item_id)
            if rect is None:
                continue
            handle = QRectF(rect.right() - 16.0, rect.bottom() - 16.0, 14.0, 14.0)
            if handle.contains(pos):
                self.setCursor(Qt.SizeFDiagCursor)
                return
            if rect.contains(pos):
                self.setCursor(Qt.OpenHandCursor)
                return
        self.unsetCursor()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        pos = event.position()
        try:
            self.setFocus(Qt.MouseFocusReason)
        except Exception:
            pass
        for item in reversed(self._items):
            item_id = str(item.get("id", "") or "")
            rect = self._drawn_item_rects.get(item_id)
            if rect is None or not rect.contains(pos):
                continue
            self._selected_item_id = item_id
            self.selectionChanged.emit(item_id)
            handle = QRectF(rect.right() - 16.0, rect.bottom() - 16.0, 14.0, 14.0)
            self._drag_mode = "resize" if handle.contains(pos) else "move"
            self._drag_item_id = item_id
            self._drag_origin_item = dict(item)
            self._drag_origin_pos = QPointF(pos)
            self._drag_start_items = self._items_snapshot()
            self.setCursor(Qt.ClosedHandCursor if self._drag_mode == "move" else Qt.SizeFDiagCursor)
            self.update()
            return
        self._selected_item_id = ""
        self.selectionChanged.emit("")
        self._drag_mode = ""
        self._drag_item_id = ""
        self._drag_origin_item = None
        self.update()

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        pos = event.position()
        if not self._drag_mode or not self._drag_item_id or self._drag_origin_item is None or self._layout_content_rect.isNull():
            self._update_cursor_for_pos(pos)
            return
        cell_w = max(1.0, self._layout_content_rect.width() / float(self._canvas_cols))
        cell_h = max(1.0, self._layout_content_rect.height() / float(self._canvas_rows))
        dx = int(round((pos.x() - self._drag_origin_pos.x()) / cell_w))
        dy = int(round((pos.y() - self._drag_origin_pos.y()) / cell_h))
        candidate = dict(self._drag_origin_item)
        if self._drag_mode == "resize":
            candidate["w"] = max(1, int(self._drag_origin_item.get("w", 1) or 1) + dx)
            candidate["h"] = max(1, int(self._drag_origin_item.get("h", 1) or 1) + dy)
        else:
            candidate["x"] = int(self._drag_origin_item.get("x", 0) or 0) + dx
            candidate["y"] = int(self._drag_origin_item.get("y", 0) or 0) + dy
        updated = []
        for item in self._items:
            if str(item.get("id", "") or "") == self._drag_item_id:
                updated.append(candidate)
            else:
                updated.append(dict(item))
        self._items = self._sanitize_items(updated, preferred_id=self._drag_item_id)
        self.layoutChanged.emit(self.items())
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if self._drag_start_items is not None and self._drag_start_items != self._items_snapshot():
            self._push_undo_snapshot(self._drag_start_items)
        self._drag_mode = ""
        self._drag_item_id = ""
        self._drag_origin_item = None
        self._drag_start_items = None
        self._update_cursor_for_pos(event.position())

    def leaveEvent(self, _event) -> None:  # type: ignore[override]
        if not self._drag_mode:
            self.unsetCursor()


LAYOUT_CANVAS_MIN_WIDTH = 2600
LAYOUT_CANVAS_MIN_HEIGHT = 1800
LAYOUT_CANVAS_EDGE_PAD_PX = 250
LAYOUT_CANVAS_GROW_CHUNK_PX = 600
LAYOUT_CELL_WIDTH_PX = 96
LAYOUT_ROW_HEIGHT_PX = 72
LAYOUT_CANVAS_MARGIN_PX = 72


class _LayoutMiniMap(QWidget):
    clicked = Signal(float, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: List[Dict[str, Any]] = []
        self._selected_item_id = ""
        self._canvas_cols = int(DISCOVER_CANVAS_COLS)
        self._canvas_rows = int(DISCOVER_CANVAS_ROWS)
        self.setMinimumSize(180, 130)
        self.setMaximumHeight(170)

    def set_snapshot(self, items: Sequence[Dict[str, Any]], canvas_cols: int, canvas_rows: int, selected_item_id: str) -> None:
        self._items = [dict(item) for item in items]
        self._canvas_cols = max(1, int(canvas_cols or DISCOVER_CANVAS_COLS))
        self._canvas_rows = max(1, int(canvas_rows or DISCOVER_CANVAS_ROWS))
        self._selected_item_id = str(selected_item_id or "")
        self.update()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        rect = QRectF(self.rect()).adjusted(10.0, 10.0, -10.0, -10.0)
        if rect.isEmpty():
            return
        pos = event.position()
        x_ratio = _clamp((pos.x() - rect.left()) / max(1.0, rect.width()), 0.0, 1.0)
        y_ratio = _clamp((pos.y() - rect.top()) / max(1.0, rect.height()), 0.0, 1.0)
        self.clicked.emit(float(x_ratio), float(y_ratio))

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(8.0, 8.0, -8.0, -8.0)
        painter.fillPath(_rounded_rect_path(rect, 10.0), QColor(12, 18, 28, 226))
        painter.setPen(QPen(QColor(255, 255, 255, 32), 1.0))
        painter.drawPath(_rounded_rect_path(rect, 10.0))
        inner = rect.adjusted(10.0, 10.0, -10.0, -10.0)
        cols = max(1, self._canvas_cols)
        rows = max(1, self._canvas_rows)
        for item in self._items:
            if bool(item.get("hidden", False)):
                continue
            x = int(item.get("x", 0) or 0)
            y = int(item.get("y", 0) or 0)
            w = max(1, int(item.get("w", 1) or 1))
            h = max(1, int(item.get("h", 1) or 1))
            block = QRectF(
                inner.left() + (float(x) / float(cols)) * inner.width(),
                inner.top() + (float(y) / float(rows)) * inner.height(),
                max(2.0, (float(w) / float(cols)) * inner.width()),
                max(2.0, (float(h) / float(rows)) * inner.height()),
            )
            selected = str(item.get("id", "") or "") == self._selected_item_id
            color = QColor(92, 160, 255, 210 if selected else 118)
            painter.fillPath(_rounded_rect_path(block, 3.0), color)
        painter.setPen(QPen(QColor(255, 255, 255, 48), 1.0))
        painter.drawRect(inner)


class _LayoutDesignSurface(_BaseMiniPreview):
    layoutChanged = Signal(list)
    selectionChanged = Signal(str)
    statusChanged = Signal(str)
    canvasChanged = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._canvas_cols = int(DISCOVER_CANVAS_COLS)
        self._canvas_rows = max(24, int(DISCOVER_CANVAS_ROWS))
        self._base_canvas_width = int(LAYOUT_CANVAS_MIN_WIDTH)
        self._base_canvas_height = int(LAYOUT_CANVAS_MIN_HEIGHT)
        self._zoom = 1.0
        self._show_guides = True
        self._snap_to_grid = True
        self._debug_overlay = False
        self._items: List[Dict[str, Any]] = []
        self._component_labels: Dict[str, str] = {}
        self._selected_item_id = ""
        self._drawn_item_rects: Dict[str, QRectF] = {}
        self._drag_mode = ""
        self._drag_item_id = ""
        self._drag_origin_item: Dict[str, Any] | None = None
        self._drag_origin_pos = QPointF()
        self._drag_start_items: List[Dict[str, Any]] | None = None
        self._drag_candidate_rect: QRectF | None = None
        self._undo_history: List[List[Dict[str, Any]]] = []
        self._redo_history: List[List[Dict[str, Any]]] = []
        self._last_validation = validate_layout([], canvas_cols=self._canvas_cols, canvas_rows=self._canvas_rows)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self._recompute_canvas_size()

    def _grid_rect(self) -> QRectF:
        margin = float(LAYOUT_CANVAS_MARGIN_PX) * self._zoom
        return QRectF(
            margin,
            margin,
            float(self._canvas_cols * LAYOUT_CELL_WIDTH_PX) * self._zoom,
            float(self._canvas_rows * LAYOUT_ROW_HEIGHT_PX) * self._zoom,
        )

    def _recompute_canvas_size(self) -> None:
        base_w = max(int(self._base_canvas_width), int((LAYOUT_CANVAS_MARGIN_PX * 2) + (self._canvas_cols * LAYOUT_CELL_WIDTH_PX)))
        base_h = max(int(self._base_canvas_height), int((LAYOUT_CANVAS_MARGIN_PX * 2) + (self._canvas_rows * LAYOUT_ROW_HEIGHT_PX)))
        self.setFixedSize(max(1, int(round(base_w * self._zoom))), max(1, int(round(base_h * self._zoom))))
        self.canvasChanged.emit()

    def set_visible_viewport_size(self, size: QSize) -> None:
        changed = False
        width = max(int(LAYOUT_CANVAS_MIN_WIDTH), int(round(float(max(1, size.width())) * 2.5)))
        height = max(int(LAYOUT_CANVAS_MIN_HEIGHT), int(round(float(max(1, size.height())) * 2.5)))
        if width > self._base_canvas_width:
            self._base_canvas_width = width
            changed = True
        if height > self._base_canvas_height:
            self._base_canvas_height = height
            changed = True
        if changed:
            self._recompute_canvas_size()

    def set_zoom(self, zoom: float) -> None:
        self._zoom = _clamp(float(zoom or 1.0), 0.5, 2.0)
        self._recompute_canvas_size()
        self.update()

    def zoom(self) -> float:
        return float(self._zoom)

    def set_show_guides(self, enabled: bool) -> None:
        self._show_guides = bool(enabled)
        self.update()

    def set_snap_to_grid(self, enabled: bool) -> None:
        self._snap_to_grid = bool(enabled)

    def set_debug_overlay(self, enabled: bool) -> None:
        self._debug_overlay = bool(enabled)
        self.update()

    def items(self) -> List[Dict[str, Any]]:
        return [dict(item) for item in self._items]

    def can_undo(self) -> bool:
        return bool(self._undo_history)

    def can_redo(self) -> bool:
        return bool(self._redo_history)

    def _items_snapshot(self) -> List[Dict[str, Any]]:
        return [dict(item) for item in self._items]

    def _push_undo_snapshot(self, snapshot: Sequence[Dict[str, Any]]) -> None:
        clean = [dict(item) for item in snapshot]
        if self._undo_history and self._undo_history[-1] == clean:
            return
        self._undo_history.append(clean)
        if len(self._undo_history) > 80:
            self._undo_history = self._undo_history[-80:]
        self._redo_history.clear()

    def undo_last_change(self) -> bool:
        if not self._undo_history:
            return False
        current = self._items_snapshot()
        snapshot = self._undo_history.pop()
        if current != snapshot:
            self._redo_history.append(current)
        self._items = self._resolve_items(snapshot, preferred_id=self._selected_item_id, compact=False)
        self._after_items_changed(emit_layout=True, emit_selection=True)
        return True

    def redo_last_change(self) -> bool:
        if not self._redo_history:
            return False
        current = self._items_snapshot()
        snapshot = self._redo_history.pop()
        if current != snapshot:
            self._undo_history.append(current)
        self._items = self._resolve_items(snapshot, preferred_id=self._selected_item_id, compact=False)
        self._after_items_changed(emit_layout=True, emit_selection=True)
        return True

    def set_items(
        self,
        items: Sequence[Dict[str, Any]],
        *,
        colors: Dict[str, Any] | None = None,
        component_labels: Dict[str, str] | None = None,
        canvas_cols: int | None = None,
        canvas_rows: int | None = None,
        selected_id: str = "",
        reset_history: bool = True,
    ) -> None:
        if colors is not None:
            self._colors = _colors(colors)
        if canvas_cols is not None:
            self._canvas_cols = max(1, int(canvas_cols or DISCOVER_CANVAS_COLS))
        if canvas_rows is not None:
            self._canvas_rows = max(1, int(canvas_rows or DISCOVER_CANVAS_ROWS))
        self._component_labels = dict(component_labels or {})
        self._items = normalize_layout_items(
            list(items),
            canvas_cols=self._canvas_cols,
            canvas_rows=self._canvas_rows,
            preferred_id=str(selected_id or ""),
            compact=True,
        )
        self._canvas_rows = grow_canvas_rows_to_items(self._items, canvas_rows=self._canvas_rows)
        self._selected_item_id = str(selected_id or self._selected_item_id or (self._items[0].get("id", "") if self._items else ""))
        if reset_history:
            self._undo_history.clear()
            self._redo_history.clear()
            self._drag_start_items = None
        self._recompute_canvas_size()
        self._after_items_changed(emit_layout=False, emit_selection=True)

    def selected_item(self) -> Dict[str, Any] | None:
        wanted = str(self._selected_item_id or "")
        for item in self._items:
            if str(item.get("id", "") or "") == wanted:
                return dict(item)
        return None

    def select_item(self, item_id: str) -> None:
        self._selected_item_id = str(item_id or "")
        self.selectionChanged.emit(self._selected_item_id)
        self._emit_status()
        self.update()

    def _component_label(self, key: str) -> str:
        return self._component_labels.get(str(key or "")) or _discover_label(str(key or ""))

    def _default_item_for_component(self, component_key: str) -> Dict[str, Any]:
        defaults = {
            "session_director": {"w": self._canvas_cols, "h": 3},
            "discovered": {"w": 10, "h": 6},
            "verified": {"w": 14, "h": 6},
            "details": {"w": self._canvas_cols, "h": 4},
            "library_hq": {"w": self._canvas_cols, "h": 3},
            "mission_control": {"w": self._canvas_cols, "h": 4},
            "profile_studio": {"w": self._canvas_cols, "h": 6},
            "theme_theater": {"w": self._canvas_cols, "h": 6},
            "shell_actions": {"w": self._canvas_cols, "h": 4},
            "palette_console": {"w": self._canvas_cols, "h": 6},
            "background_stage": {"w": self._canvas_cols, "h": 5},
            "glass_studio": {"w": self._canvas_cols, "h": 4},
            "home_chrome": {"w": self._canvas_cols, "h": 4},
            "player_chrome": {"w": self._canvas_cols, "h": 7},
            "layout_studio": {"w": self._canvas_cols, "h": 6},
            "video_stage": {"w": self._canvas_cols, "h": 12},
            "episode_title": {"w": self._canvas_cols, "h": 2},
            "smart_shuffle": {"w": self._canvas_cols, "h": 3},
            "controls_bar": {"w": self._canvas_cols, "h": 3},
            "playlist_drawer": {"w": 16, "h": 4},
            "command_center": {"w": 8, "h": 4},
        }
        dims = defaults.get(component_key, {"w": 6, "h": 4})
        return {
            "id": str(component_key),
            "widget_id": str(component_key),
            "component": str(component_key),
            "x": 0,
            "y": 0,
            "w": max(1, min(self._canvas_cols, int(dims["w"]))),
            "h": max(1, int(dims["h"])),
            "min_w": 1,
            "min_h": 1,
            "locked": False,
            "hidden": False,
        }

    def _next_spacer_component(self) -> str:
        highest = 0
        for item in self._items:
            component = str(item.get("component", "") or "")
            if component.startswith("spacer_"):
                try:
                    highest = max(highest, int(component.split("_", 1)[1]))
                except Exception:
                    continue
        return f"spacer_{highest + 1}"

    def add_item(self, component_key: str) -> str:
        token = str(component_key or "").strip()
        if not token:
            return ""
        if not _discover_is_spacer(token):
            for item in self._items:
                if str(item.get("component", "") or "") == token:
                    existing_id = str(item.get("id", "") or "")
                    self.select_item(existing_id)
                    return existing_id
        self._push_undo_snapshot(self._items_snapshot())
        new_item = self._default_item_for_component(token)
        self._items = self._resolve_items([*self._items, new_item], preferred_id=str(new_item["id"]), compact=False)
        self._selected_item_id = str(new_item["id"])
        self._after_items_changed(emit_layout=True, emit_selection=True)
        return self._selected_item_id

    def remove_selected_item(self) -> None:
        selected = str(self._selected_item_id or "")
        if not selected:
            return
        self._push_undo_snapshot(self._items_snapshot())
        self._items = [dict(item) for item in self._items if str(item.get("id", "") or "") != selected]
        self._selected_item_id = str(self._items[0].get("id", "") if self._items else "")
        self._after_items_changed(emit_layout=True, emit_selection=True)

    def duplicate_selected_item(self) -> str:
        selected = self.selected_item()
        if not selected:
            return ""
        self._push_undo_snapshot(self._items_snapshot())
        clone = dict(selected)
        component = str(clone.get("component", "") or "")
        if not _discover_is_spacer(component):
            component = self._next_spacer_component()
        clone["component"] = component
        clone["id"] = f"{component}_{len(self._items) + 1}"
        clone["widget_id"] = clone["id"]
        clone["x"] = int(clone.get("x", 0) or 0) + 1
        clone["y"] = int(clone.get("y", 0) or 0) + 1
        clone["locked"] = False
        clone["hidden"] = False
        self._items = self._resolve_items([*self._items, clone], preferred_id=str(clone["id"]), compact=False)
        self._selected_item_id = str(clone["id"])
        self._after_items_changed(emit_layout=True, emit_selection=True)
        return self._selected_item_id

    def toggle_selected_locked(self) -> None:
        selected = str(self._selected_item_id or "")
        if not selected:
            return
        self._push_undo_snapshot(self._items_snapshot())
        for item in self._items:
            if str(item.get("id", "") or "") == selected:
                item["locked"] = not bool(item.get("locked", False))
                break
        self._after_items_changed(emit_layout=True, emit_selection=True)

    def toggle_selected_hidden(self) -> None:
        selected = str(self._selected_item_id or "")
        if not selected:
            return
        self._push_undo_snapshot(self._items_snapshot())
        for item in self._items:
            if str(item.get("id", "") or "") == selected:
                item["hidden"] = not bool(item.get("hidden", False))
                break
        self._after_items_changed(emit_layout=True, emit_selection=True)

    def restore_selected_default(self) -> None:
        selected = self.selected_item()
        if not selected:
            return
        self._push_undo_snapshot(self._items_snapshot())
        default_item = self._default_item_for_component(str(selected.get("component", "") or selected.get("id", "")))
        default_item["id"] = str(selected.get("id", "") or default_item["id"])
        default_item["widget_id"] = default_item["id"]
        updated = [default_item if str(item.get("id", "") or "") == default_item["id"] else dict(item) for item in self._items]
        self._items = self._resolve_items(updated, preferred_id=str(default_item["id"]), compact=False)
        self._after_items_changed(emit_layout=True, emit_selection=True)

    def make_selected_full_width(self) -> None:
        selected = str(self._selected_item_id or "")
        if not selected:
            return
        self._push_undo_snapshot(self._items_snapshot())
        updated = []
        for item in self._items:
            copy = dict(item)
            if str(copy.get("id", "") or "") == selected and not bool(copy.get("locked", False)):
                copy["x"] = 0
                copy["w"] = self._canvas_cols
            updated.append(copy)
        self._items = self._resolve_items(updated, preferred_id=selected, compact=False)
        self._after_items_changed(emit_layout=True, emit_selection=True)

    def normalize_now(self) -> None:
        self._push_undo_snapshot(self._items_snapshot())
        self._items = self._resolve_items(self._items, preferred_id=self._selected_item_id, compact=True)
        self._after_items_changed(emit_layout=True, emit_selection=True)

    def reset_canvas_size(self) -> None:
        self._base_canvas_width = int(LAYOUT_CANVAS_MIN_WIDTH)
        self._base_canvas_height = int(LAYOUT_CANVAS_MIN_HEIGHT)
        self._canvas_rows = grow_canvas_rows_to_items(self._items, canvas_rows=max(24, self._canvas_rows))
        self._recompute_canvas_size()
        self._emit_status(note="canvas reset")
        self.update()

    def grow_canvas_to_content(self) -> None:
        left, top, right, bottom = content_bounds(self._items)
        _ = (left, top)
        needed_w = int((LAYOUT_CANVAS_MARGIN_PX * 2) + (max(self._canvas_cols, right) * LAYOUT_CELL_WIDTH_PX) + LAYOUT_CANVAS_EDGE_PAD_PX)
        needed_h = int((LAYOUT_CANVAS_MARGIN_PX * 2) + (max(self._canvas_rows, bottom) * LAYOUT_ROW_HEIGHT_PX) + LAYOUT_CANVAS_EDGE_PAD_PX)
        self._base_canvas_width = max(self._base_canvas_width, needed_w)
        self._base_canvas_height = max(self._base_canvas_height, needed_h)
        self._canvas_rows = grow_canvas_rows_to_items(self._items, canvas_rows=self._canvas_rows)
        self._recompute_canvas_size()
        self._emit_status(note="canvas grown")
        self.update()

    def _resolve_items(self, items: Sequence[Dict[str, Any]], *, preferred_id: str = "", compact: bool = False) -> List[Dict[str, Any]]:
        resolved = resolve_grid_items(
            [dict(item) for item in items],
            canvas_cols=self._canvas_cols,
            canvas_rows=self._canvas_rows,
            active_id=str(preferred_id or ""),
            compact=compact,
            fixed_ids=(str(preferred_id),) if preferred_id and not compact else (),
        )
        self._canvas_rows = grow_canvas_rows_to_items(resolved, canvas_rows=self._canvas_rows)
        return resolved

    def _after_items_changed(self, *, emit_layout: bool, emit_selection: bool) -> None:
        self._auto_grow_canvas()
        self._last_validation = validate_layout(self._items, canvas_cols=self._canvas_cols, canvas_rows=self._canvas_rows)
        if emit_selection:
            if self._selected_item_id and not any(str(item.get("id", "") or "") == self._selected_item_id for item in self._items):
                self._selected_item_id = str(self._items[0].get("id", "") if self._items else "")
            self.selectionChanged.emit(self._selected_item_id)
        if emit_layout:
            self.layoutChanged.emit(self.items())
        self._emit_status()
        self.update()

    def _auto_grow_canvas(self) -> None:
        _, _, right, bottom = content_bounds(self._items)
        needed_rows = grow_canvas_rows_to_items(self._items, canvas_rows=self._canvas_rows)
        if needed_rows != self._canvas_rows:
            self._canvas_rows = needed_rows
        grid = self._grid_rect()
        content_right = grid.left() + (float(max(1, right)) * LAYOUT_CELL_WIDTH_PX * self._zoom)
        content_bottom = grid.top() + (float(max(1, bottom)) * LAYOUT_ROW_HEIGHT_PX * self._zoom)
        grew = False
        if self.width() - content_right < float(LAYOUT_CANVAS_EDGE_PAD_PX) * self._zoom:
            self._base_canvas_width += int(LAYOUT_CANVAS_GROW_CHUNK_PX)
            grew = True
        if self.height() - content_bottom < float(LAYOUT_CANVAS_EDGE_PAD_PX) * self._zoom:
            self._base_canvas_height += int(LAYOUT_CANVAS_GROW_CHUNK_PX)
            grew = True
        if grew:
            self._recompute_canvas_size()

    def _emit_status(self, note: str = "") -> None:
        report = layout_debug_report(
            "studio",
            self._items,
            canvas_cols=self._canvas_cols,
            canvas_rows=self._canvas_rows,
            viewport_size=(0, 0),
            canvas_size=(self.width(), self.height()),
            note=note,
        )
        self.statusChanged.emit(report)

    def _item_rect(self, item: Dict[str, Any]) -> QRectF:
        grid = self._grid_rect()
        cell_w = max(1.0, float(LAYOUT_CELL_WIDTH_PX) * self._zoom)
        cell_h = max(1.0, float(LAYOUT_ROW_HEIGHT_PX) * self._zoom)
        gap = max(4.0, 8.0 * self._zoom)
        return QRectF(
            grid.left() + (float(int(item.get("x", 0) or 0)) * cell_w) + (gap / 2.0),
            grid.top() + (float(int(item.get("y", 0) or 0)) * cell_h) + (gap / 2.0),
            max(18.0, (float(max(1, int(item.get("w", 1) or 1))) * cell_w) - gap),
            max(18.0, (float(max(1, int(item.get("h", 1) or 1))) * cell_h) - gap),
        )

    def _grid_delta_from_points(self, pos: QPointF, origin: QPointF) -> tuple[int, int]:
        cell_w = max(1.0, float(LAYOUT_CELL_WIDTH_PX) * self._zoom)
        cell_h = max(1.0, float(LAYOUT_ROW_HEIGHT_PX) * self._zoom)
        if self._snap_to_grid:
            return int(round((pos.x() - origin.x()) / cell_w)), int(round((pos.y() - origin.y()) / cell_h))
        return int((pos.x() - origin.x()) / cell_w), int((pos.y() - origin.y()) / cell_h)

    def _update_cursor_for_pos(self, pos: QPointF) -> None:
        for item in reversed(self._items):
            item_id = str(item.get("id", "") or "")
            rect = self._drawn_item_rects.get(item_id)
            if rect is None:
                continue
            handle = QRectF(rect.right() - 18.0, rect.bottom() - 18.0, 16.0, 16.0)
            if handle.contains(pos) and not bool(item.get("locked", False)):
                self.setCursor(Qt.SizeFDiagCursor)
                return
            if rect.contains(pos):
                self.setCursor(Qt.ForbiddenCursor if bool(item.get("locked", False)) else Qt.OpenHandCursor)
                return
        self.unsetCursor()

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        full = QRectF(self.rect())
        bg = QLinearGradient(full.topLeft(), full.bottomRight())
        bg.setColorAt(0.0, QColor(6, 12, 20))
        bg.setColorAt(0.55, QColor(13, 23, 34))
        bg.setColorAt(1.0, QColor(10, 18, 28))
        painter.fillRect(full, bg)

        grid = self._grid_rect()
        painter.fillPath(_rounded_rect_path(grid.adjusted(-18.0, -18.0, 18.0, 18.0), 18.0), QColor(255, 255, 255, 10))
        painter.setPen(QPen(QColor(255, 255, 255, 42), 1.0))
        painter.drawPath(_rounded_rect_path(grid.adjusted(-18.0, -18.0, 18.0, 18.0), 18.0))

        if self._show_guides:
            painter.setPen(QPen(QColor(255, 255, 255, 34), 1.0))
            cell_w = float(LAYOUT_CELL_WIDTH_PX) * self._zoom
            cell_h = float(LAYOUT_ROW_HEIGHT_PX) * self._zoom
            for col in range(self._canvas_cols + 1):
                x = grid.left() + (float(col) * cell_w)
                painter.drawLine(QPointF(x, grid.top()), QPointF(x, grid.bottom()))
            for row in range(self._canvas_rows + 1):
                y = grid.top() + (float(row) * cell_h)
                painter.drawLine(QPointF(grid.left(), y), QPointF(grid.right(), y))

        self._drawn_item_rects = {}
        for item in self._items:
            item_id = str(item.get("id", "") or "")
            key = str(item.get("component", "") or "")
            rect = self._item_rect(item)
            self._drawn_item_rects[item_id] = rect
            hidden = bool(item.get("hidden", False))
            locked = bool(item.get("locked", False))
            is_spacer = _discover_is_spacer(key) or not key
            accent = _color(DISCOVER_ACCENTS.get(key, "#7A8699"), "#7A8699")
            fill_alpha = 74 if hidden else (126 if is_spacer else 214)
            border_alpha = 120 if hidden else (132 if is_spacer else 184)
            fill = _alpha(_mix(QColor(18, 28, 42), accent, 0.16 if not is_spacer else 0.05), fill_alpha)
            border = _alpha(accent if not is_spacer else QColor(135, 154, 180), border_alpha)
            self._draw_card(painter, rect, fill, border, 9.0)
            if hidden:
                painter.fillPath(_rounded_rect_path(rect, 9.0), QColor(0, 0, 0, 82))

            if item_id == self._selected_item_id:
                painter.setPen(QPen(QColor(214, 236, 255, 232), 2.0))
                painter.drawPath(_rounded_rect_path(rect.adjusted(-3.0, -3.0, 3.0, 3.0), 11.0))

            badge = QRectF(rect.left() + 10.0, rect.top() + 9.0, min(112.0 * self._zoom, rect.width() - 20.0), 20.0 * self._zoom)
            self._draw_chip(painter, badge, QColor(255, 255, 255, 24))
            painter.setPen(QColor(222, 232, 246, 210))
            painter.drawText(badge.adjusted(7.0, 0.0, -7.0, 0.0), Qt.AlignLeft | Qt.AlignVCenter, f"{int(item.get('x', 0))},{int(item.get('y', 0))}  {int(item.get('w', 1))}x{int(item.get('h', 1))}")

            title_rect = QRectF(rect.left() + 10.0, rect.top() + 36.0 * self._zoom, rect.width() - 20.0, 26.0 * self._zoom)
            painter.setPen(QColor(248, 251, 255, 232 if not hidden else 130))
            title = self._component_label(key)
            if locked:
                title = f"{title}  [locked]"
            if hidden:
                title = f"{title}  [hidden]"
            painter.drawText(title_rect, Qt.AlignLeft | Qt.AlignVCenter, title)

            if not hidden:
                painter.setPen(QPen(QColor(255, 255, 255, 38), 1.0))
                for index in range(3):
                    line_y = rect.top() + (72.0 + (index * 18.0)) * self._zoom
                    line_w = min(rect.width() - 20.0, rect.width() * (0.72 - (index * 0.08)))
                    self._draw_label_line(painter, QRectF(rect.left() + 10.0, line_y, max(18.0, line_w), 6.0), QColor(255, 255, 255, 38), 3.0)

            if item_id == self._selected_item_id and not locked:
                handle = QRectF(rect.right() - 16.0, rect.bottom() - 16.0, 12.0, 12.0)
                self._draw_chip(painter, handle, QColor(214, 236, 255, 235))

        if self._drag_candidate_rect is not None:
            painter.setPen(QPen(QColor(218, 238, 255, 210), 2.0, Qt.DashLine))
            painter.drawPath(_rounded_rect_path(self._drag_candidate_rect, 10.0))

        if self._debug_overlay:
            painter.setPen(QPen(QColor(255, 196, 96, 170), 1.0, Qt.DashLine))
            painter.drawText(
                QRectF(18.0, 18.0, 900.0, 24.0),
                Qt.AlignLeft | Qt.AlignVCenter,
                self._last_validation.summary(),
            )

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        pos = event.position()
        try:
            self.setFocus(Qt.MouseFocusReason)
        except Exception:
            pass
        for item in reversed(self._items):
            item_id = str(item.get("id", "") or "")
            rect = self._drawn_item_rects.get(item_id, self._item_rect(item))
            if not rect.contains(pos):
                continue
            self._selected_item_id = item_id
            self.selectionChanged.emit(item_id)
            self._emit_status()
            if bool(item.get("locked", False)):
                self._drag_mode = ""
                self.update()
                return
            handle = QRectF(rect.right() - 18.0, rect.bottom() - 18.0, 16.0, 16.0)
            self._drag_mode = "resize" if handle.contains(pos) else "move"
            self._drag_item_id = item_id
            self._drag_origin_item = dict(item)
            self._drag_origin_pos = QPointF(pos)
            self._drag_start_items = self._items_snapshot()
            self.setCursor(Qt.SizeFDiagCursor if self._drag_mode == "resize" else Qt.ClosedHandCursor)
            self.update()
            return
        self._selected_item_id = ""
        self._drag_mode = ""
        self._drag_item_id = ""
        self._drag_origin_item = None
        self.selectionChanged.emit("")
        self._emit_status()
        self.update()

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        pos = event.position()
        if not self._drag_mode or not self._drag_item_id or self._drag_origin_item is None:
            self._update_cursor_for_pos(pos)
            return
        dx, dy = self._grid_delta_from_points(pos, self._drag_origin_pos)
        candidate = dict(self._drag_origin_item)
        if self._drag_mode == "resize":
            candidate["w"] = max(1, int(self._drag_origin_item.get("w", 1) or 1) + dx)
            candidate["h"] = max(1, int(self._drag_origin_item.get("h", 1) or 1) + dy)
        else:
            candidate["x"] = int(self._drag_origin_item.get("x", 0) or 0) + dx
            candidate["y"] = int(self._drag_origin_item.get("y", 0) or 0) + dy
        candidate["w"] = max(1, min(self._canvas_cols, int(candidate.get("w", 1) or 1)))
        candidate["x"] = max(0, min(self._canvas_cols - int(candidate["w"]), int(candidate.get("x", 0) or 0)))
        candidate["y"] = max(0, int(candidate.get("y", 0) or 0))
        candidate["h"] = max(1, int(candidate.get("h", 1) or 1))
        self._canvas_rows = max(self._canvas_rows, int(candidate["y"]) + int(candidate["h"]) + 4)
        updated = [candidate if str(item.get("id", "") or "") == self._drag_item_id else dict(item) for item in self._items]
        self._items = self._resolve_items(updated, preferred_id=self._drag_item_id, compact=False)
        active = self.selected_item()
        self._drag_candidate_rect = self._item_rect(active) if active else None
        self._after_items_changed(emit_layout=True, emit_selection=False)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if self._drag_start_items is not None and self._drag_start_items != self._items_snapshot():
            self._push_undo_snapshot(self._drag_start_items)
        self._drag_mode = ""
        self._drag_item_id = ""
        self._drag_origin_item = None
        self._drag_start_items = None
        self._drag_candidate_rect = None
        self._update_cursor_for_pos(event.position())
        self._after_items_changed(emit_layout=True, emit_selection=True)

    def leaveEvent(self, _event) -> None:  # type: ignore[override]
        if not self._drag_mode:
            self.unsetCursor()

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        selected = self.selected_item()
        if selected is None:
            super().keyPressEvent(event)
            return
        key = event.key()
        modifiers = event.modifiers()
        if key == Qt.Key_Delete:
            self.remove_selected_item()
            return
        if key == Qt.Key_D and bool(modifiers & Qt.ControlModifier):
            self.duplicate_selected_item()
            return
        if bool(selected.get("locked", False)):
            super().keyPressEvent(event)
            return
        dx = dy = 0
        step = 4 if bool(modifiers & Qt.ShiftModifier) else 1
        if key == Qt.Key_Left:
            dx = -step
        elif key == Qt.Key_Right:
            dx = step
        elif key == Qt.Key_Up:
            dy = -step
        elif key == Qt.Key_Down:
            dy = step
        else:
            super().keyPressEvent(event)
            return
        self._push_undo_snapshot(self._items_snapshot())
        updated = []
        for item in self._items:
            copy = dict(item)
            if str(copy.get("id", "") or "") == str(selected.get("id", "") or ""):
                copy["x"] = int(copy.get("x", 0) or 0) + dx
                copy["y"] = int(copy.get("y", 0) or 0) + dy
            updated.append(copy)
        self._items = self._resolve_items(updated, preferred_id=str(selected.get("id", "")), compact=False)
        self._after_items_changed(emit_layout=True, emit_selection=True)


class DiscoverLayoutEditor(QWidget):
    layoutChanged = Signal(list)
    selectionChanged = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._zoom_values = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]
        self.setObjectName("pageLayoutStudio")
        self.setMinimumSize(1180, 880)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        toolbar = QFrame(self)
        toolbar.setObjectName("layoutStudioToolbar")
        toolbar_l = QHBoxLayout(toolbar)
        toolbar_l.setContentsMargins(10, 8, 10, 8)
        toolbar_l.setSpacing(6)
        self._btn_undo = self._tool_button("Undo", "Undo the last layout edit", self.undo_last_change)
        self._btn_redo = self._tool_button("Redo", "Redo the last layout edit", self.redo_last_change)
        toolbar_l.addWidget(self._btn_undo)
        toolbar_l.addWidget(self._btn_redo)
        toolbar_l.addSpacing(8)
        toolbar_l.addWidget(self._tool_button("-", "Zoom out", self._zoom_out))
        self._zoom_combo = FocusSafeComboBox(toolbar)
        for value in self._zoom_values:
            self._zoom_combo.addItem(f"{int(value * 100)}%", value)
        self._zoom_combo.setCurrentIndex(2)
        self._zoom_combo.currentIndexChanged.connect(lambda _i: self._surface.set_zoom(float(self._zoom_combo.currentData() or 1.0)))
        toolbar_l.addWidget(self._zoom_combo)
        toolbar_l.addWidget(self._tool_button("+", "Zoom in", self._zoom_in))
        toolbar_l.addWidget(self._tool_button("Fit", "Fit the full canvas into the viewport", self.fit_to_screen))
        toolbar_l.addWidget(self._tool_button("Focus", "Fit and center the selected widget", self.fit_selected_widget))
        toolbar_l.addWidget(self._tool_button("Center", "Center the content bounds", self.center_content))
        toolbar_l.addWidget(self._tool_button("100%", "Reset zoom", self.reset_zoom))
        toolbar_l.addSpacing(8)
        toolbar_l.addWidget(self._tool_button("Normalize", "Reflow and compact safely", self.normalize_now))
        toolbar_l.addWidget(self._tool_button("Full", "Make selected widget full width", self.make_selected_full_width))
        toolbar_l.addWidget(self._tool_button("Copy", "Duplicate selected widget", self.duplicate_selected_item))
        toolbar_l.addWidget(self._tool_button("Lock", "Toggle selected widget lock", self.toggle_selected_locked))
        toolbar_l.addWidget(self._tool_button("Hide", "Toggle selected widget visibility", self.toggle_selected_hidden))
        toolbar_l.addWidget(self._tool_button("Default", "Restore selected widget to its default size", self.restore_selected_default))
        toolbar_l.addWidget(self._tool_button("Canvas", "Grow canvas to content bounds", self.grow_canvas_to_content))
        toolbar_l.addWidget(self._tool_button("Reset Canvas", "Reset canvas size", self.reset_canvas_size))
        toolbar_l.addWidget(self._tool_button("Export", "Export this layout preset", self.export_layout_preset))
        toolbar_l.addWidget(self._tool_button("Import", "Import and repair a layout preset", self.import_layout_preset))
        toolbar_l.addStretch(1)
        self._snap_check = QCheckBox("Snap", toolbar)
        self._snap_check.setChecked(True)
        self._snap_check.toggled.connect(lambda checked: self._surface.set_snap_to_grid(bool(checked)))
        toolbar_l.addWidget(self._snap_check)
        self._guides_check = QCheckBox("Guides", toolbar)
        self._guides_check.setChecked(True)
        self._guides_check.toggled.connect(lambda checked: self._surface.set_show_guides(bool(checked)))
        toolbar_l.addWidget(self._guides_check)
        self._debug_check = QCheckBox("Debug", toolbar)
        self._debug_check.toggled.connect(lambda checked: self._surface.set_debug_overlay(bool(checked)))
        toolbar_l.addWidget(self._debug_check)
        root.addWidget(toolbar, 0)

        body = QSplitter(Qt.Horizontal, self)
        body.setObjectName("layoutStudioBody")
        root.addWidget(body, 1)

        self._navigator = QListWidget(body)
        self._navigator.setObjectName("layoutStudioNavigator")
        self._navigator.setMinimumWidth(170)
        self._navigator.setMaximumWidth(220)
        self._navigator.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self._navigator.itemClicked.connect(lambda item: self._surface.select_item(str(item.data(Qt.UserRole) or "")))
        body.addWidget(self._navigator)

        self._scroll = QScrollArea(body)
        self._scroll.setObjectName("layoutStudioScroll")
        self._scroll.setMinimumWidth(760)
        self._scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._scroll.setWidgetResizable(False)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self._surface = _LayoutDesignSurface(self._scroll)
        self._scroll.setWidget(self._surface)
        body.addWidget(self._scroll)

        inspector = QFrame(body)
        inspector.setObjectName("layoutStudioInspector")
        inspector.setMinimumWidth(200)
        inspector.setMaximumWidth(230)
        inspector.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        inspector_l = QVBoxLayout(inspector)
        inspector_l.setContentsMargins(10, 10, 10, 10)
        inspector_l.setSpacing(10)
        title = QLabel("Inspector", inspector)
        title.setStyleSheet("font-size: 14px; font-weight: 900; background: transparent;")
        inspector_l.addWidget(title)
        self._inspector_label = QLabel("", inspector)
        self._inspector_label.setWordWrap(True)
        self._inspector_label.setStyleSheet("background: transparent; color: rgba(235,242,252,0.82);")
        inspector_l.addWidget(self._inspector_label)
        self._minimap = _LayoutMiniMap(inspector)
        self._minimap.clicked.connect(self._scroll_to_minimap_ratio)
        inspector_l.addWidget(self._minimap)
        self._validation_label = QLabel("", inspector)
        self._validation_label.setWordWrap(True)
        self._validation_label.setStyleSheet("background: transparent; color: rgba(180,205,232,0.78);")
        inspector_l.addWidget(self._validation_label)
        inspector_l.addStretch(1)
        body.addWidget(inspector)
        body.setStretchFactor(0, 0)
        body.setStretchFactor(1, 1)
        body.setStretchFactor(2, 0)
        for index in range(3):
            body.setCollapsible(index, False)
        body.setSizes([180, 1600, 210])

        self._status_label = QLabel("", self)
        self._status_label.setObjectName("layoutStudioStatus")
        self._status_label.setMinimumHeight(28)
        root.addWidget(self._status_label, 0)

        self._surface.layoutChanged.connect(self._on_surface_layout_changed)
        self._surface.selectionChanged.connect(self._on_surface_selection_changed)
        self._surface.statusChanged.connect(self._on_surface_status)
        self._surface.canvasChanged.connect(self._refresh_overview)
        self.setStyleSheet(
            """
            QWidget#pageLayoutStudio {
                background: rgba(7, 12, 20, 0.72);
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 8px;
            }
            QFrame#layoutStudioToolbar, QLabel#layoutStudioStatus {
                background: rgba(255,255,255,0.045);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 8px;
                color: rgba(235,242,252,0.82);
            }
            QFrame#layoutStudioInspector, QListWidget#layoutStudioNavigator {
                background: rgba(255,255,255,0.035);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 8px;
                color: rgba(240,246,255,0.90);
            }
            QScrollArea#layoutStudioScroll {
                background: rgba(0,0,0,0.22);
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 8px;
            }
            QPushButton {
                background: rgba(255,255,255,0.06);
                color: rgba(245,250,255,0.92);
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 6px;
                padding: 6px 9px;
                font-weight: 700;
            }
            QPushButton:hover {
                background: rgba(92,160,255,0.18);
                border-color: rgba(144,202,255,0.42);
            }
            QCheckBox {
                color: rgba(235,242,252,0.82);
                spacing: 6px;
            }
            QListWidget#layoutStudioNavigator::item {
                border-bottom: 1px solid rgba(255,255,255,0.06);
                padding: 8px;
            }
            QListWidget#layoutStudioNavigator::item:selected {
                background: rgba(92,160,255,0.24);
                color: #FFFFFF;
            }
            """
        )

    def _tool_button(self, text: str, tooltip: str, callback) -> QPushButton:
        btn = QPushButton(str(text), self)
        btn.setToolTip(str(tooltip))
        btn.setFocusPolicy(Qt.NoFocus)
        btn.clicked.connect(lambda _checked=False: callback())
        return btn

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        try:
            self._surface.set_visible_viewport_size(self._scroll.viewport().size())
        except Exception:
            pass
        self._refresh_overview()

    def _on_surface_layout_changed(self, items: list) -> None:
        self._refresh_overview()
        self.layoutChanged.emit(items)

    def _on_surface_selection_changed(self, item_id: str) -> None:
        self._refresh_overview()
        self.selectionChanged.emit(str(item_id or ""))

    def _on_surface_status(self, status: str) -> None:
        self._status_label.setText(str(status or ""))

    def _refresh_overview(self) -> None:
        items = self._surface.items()
        selected = str(self._surface._selected_item_id or "")
        self._navigator.blockSignals(True)
        self._navigator.clear()
        for item in items:
            component = str(item.get("component", "") or "")
            label = self._surface._component_label(component)
            flags = []
            if bool(item.get("locked", False)):
                flags.append("locked")
            if bool(item.get("hidden", False)):
                flags.append("hidden")
            suffix = f" ({', '.join(flags)})" if flags else ""
            nav_item = QListWidgetItem(f"{label}  {int(item.get('w', 1))}x{int(item.get('h', 1))}{suffix}")
            nav_item.setData(Qt.UserRole, str(item.get("id", "") or ""))
            self._navigator.addItem(nav_item)
            if str(item.get("id", "") or "") == selected:
                self._navigator.setCurrentItem(nav_item)
        self._navigator.blockSignals(False)
        self._minimap.set_snapshot(items, self._surface._canvas_cols, self._surface._canvas_rows, selected)
        selected_item = self._surface.selected_item()
        if selected_item:
            self._inspector_label.setText(
                "{name}\nGrid: x={x}, y={y}, span={w}x{h}\nMin: {min_w}x{min_h}\nLocked: {locked}\nVisible: {visible}".format(
                    name=self._surface._component_label(str(selected_item.get("component", "") or "")),
                    x=int(selected_item.get("x", 0) or 0),
                    y=int(selected_item.get("y", 0) or 0),
                    w=int(selected_item.get("w", 1) or 1),
                    h=int(selected_item.get("h", 1) or 1),
                    min_w=int(selected_item.get("min_w", 1) or 1),
                    min_h=int(selected_item.get("min_h", 1) or 1),
                    locked="yes" if bool(selected_item.get("locked", False)) else "no",
                    visible="no" if bool(selected_item.get("hidden", False)) else "yes",
                )
            )
        else:
            self._inspector_label.setText("No widget selected.")
        validation = validate_layout(items, canvas_cols=self._surface._canvas_cols, canvas_rows=self._surface._canvas_rows)
        self._validation_label.setText(validation.summary())

    def _scroll_to_minimap_ratio(self, x_ratio: float, y_ratio: float) -> None:
        hbar = self._scroll.horizontalScrollBar()
        vbar = self._scroll.verticalScrollBar()
        hbar.setValue(int(float(hbar.maximum()) * _clamp(float(x_ratio), 0.0, 1.0)))
        vbar.setValue(int(float(vbar.maximum()) * _clamp(float(y_ratio), 0.0, 1.0)))

    def _center_rect_in_scroll(self, rect: QRectF) -> None:
        hbar = self._scroll.horizontalScrollBar()
        vbar = self._scroll.verticalScrollBar()
        viewport = self._scroll.viewport().size()
        hbar.setValue(max(hbar.minimum(), min(hbar.maximum(), int(rect.center().x() - (viewport.width() / 2)))))
        vbar.setValue(max(vbar.minimum(), min(vbar.maximum(), int(rect.center().y() - (viewport.height() / 2)))))

    def _zoom_in(self) -> None:
        current = self._surface.zoom()
        for index, value in enumerate(self._zoom_values):
            if value > current + 0.01:
                self._zoom_combo.setCurrentIndex(index)
                return
        self._zoom_combo.setCurrentIndex(len(self._zoom_values) - 1)

    def _zoom_out(self) -> None:
        current = self._surface.zoom()
        for index in range(len(self._zoom_values) - 1, -1, -1):
            value = self._zoom_values[index]
            if value < current - 0.01:
                self._zoom_combo.setCurrentIndex(index)
                return
        self._zoom_combo.setCurrentIndex(0)

    def reset_zoom(self) -> None:
        self._zoom_combo.setCurrentIndex(2)

    def fit_to_screen(self) -> None:
        viewport = self._scroll.viewport().size()
        if viewport.width() <= 0 or viewport.height() <= 0:
            return
        zoom = min(float(viewport.width()) / float(max(1, self._surface.width() / self._surface.zoom())), float(viewport.height()) / float(max(1, self._surface.height() / self._surface.zoom())))
        zoom = _clamp(zoom, 0.5, 2.0)
        nearest = min(range(len(self._zoom_values)), key=lambda index: abs(self._zoom_values[index] - zoom))
        self._zoom_combo.setCurrentIndex(nearest)
        self.center_content()

    def fit_selected_widget(self) -> None:
        selected = self._surface.selected_item()
        if not selected:
            self.center_content()
            return
        self._center_rect_in_scroll(self._surface._item_rect(selected))

    def center_content(self) -> None:
        items = self._surface.items()
        left, top, right, bottom = content_bounds(items)
        grid = self._surface._grid_rect()
        cell_w = float(LAYOUT_CELL_WIDTH_PX) * self._surface.zoom()
        cell_h = float(LAYOUT_ROW_HEIGHT_PX) * self._surface.zoom()
        rect = QRectF(
            grid.left() + (float(left) * cell_w),
            grid.top() + (float(top) * cell_h),
            max(cell_w, float(max(1, right - left)) * cell_w),
            max(cell_h, float(max(1, bottom - top)) * cell_h),
        )
        self._center_rect_in_scroll(rect)

    def grow_canvas_to_content(self) -> None:
        self._surface.grow_canvas_to_content()
        self._refresh_overview()

    def reset_canvas_size(self) -> None:
        self._surface.reset_canvas_size()
        self._refresh_overview()

    def normalize_now(self) -> None:
        self._surface.normalize_now()

    def duplicate_selected_item(self) -> None:
        self._surface.duplicate_selected_item()

    def toggle_selected_locked(self) -> None:
        self._surface.toggle_selected_locked()

    def toggle_selected_hidden(self) -> None:
        self._surface.toggle_selected_hidden()

    def restore_selected_default(self) -> None:
        self._surface.restore_selected_default()

    def make_selected_full_width(self) -> None:
        self._surface.make_selected_full_width()

    def export_layout_preset(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(
            self,
            "Export Layout Preset",
            "omega-layout-preset.json",
            "Omega Layout Preset (*.json)",
        )
        if not path:
            return
        payload = {
            "schema_version": GRID_SCHEMA_VERSION,
            "canvas_cols": int(self._surface._canvas_cols),
            "canvas_rows": int(self._surface._canvas_rows),
            "items": self._surface.items(),
        }
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
        except Exception as exc:
            self._status_label.setText(f"Export failed: {exc}")

    def import_layout_preset(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self,
            "Import Layout Preset",
            "",
            "Omega Layout Preset (*.json)",
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception as exc:
            self._status_label.setText(f"Import failed: {exc}")
            return
        source = payload if isinstance(payload, dict) else {}
        self._surface._push_undo_snapshot(self._surface.items())
        self._surface.set_items(
            source.get("items", []),
            canvas_cols=int(source.get("canvas_cols", self._surface._canvas_cols) or self._surface._canvas_cols),
            canvas_rows=int(source.get("canvas_rows", self._surface._canvas_rows) or self._surface._canvas_rows),
            reset_history=False,
        )
        self._surface.normalize_now()
        self._refresh_overview()
        self.layoutChanged.emit(self.items())

    def items(self) -> List[Dict[str, Any]]:
        return self._surface.items()

    def can_undo(self) -> bool:
        return self._surface.can_undo()

    def can_redo(self) -> bool:
        return self._surface.can_redo()

    def undo_last_change(self) -> bool:
        changed = self._surface.undo_last_change()
        self._refresh_overview()
        return bool(changed)

    def redo_last_change(self) -> bool:
        changed = self._surface.redo_last_change()
        self._refresh_overview()
        return bool(changed)

    def set_items(
        self,
        items: Sequence[Dict[str, Any]],
        *,
        colors: Dict[str, Any] | None = None,
        component_labels: Dict[str, str] | None = None,
        canvas_cols: int | None = None,
        canvas_rows: int | None = None,
        selected_id: str = "",
        reset_history: bool = True,
    ) -> None:
        self._surface.set_items(
            items,
            colors=colors,
            component_labels=component_labels,
            canvas_cols=canvas_cols,
            canvas_rows=canvas_rows,
            selected_id=selected_id,
            reset_history=reset_history,
        )
        self._refresh_overview()

    def selected_item(self) -> Dict[str, Any] | None:
        return self._surface.selected_item()

    def select_item(self, item_id: str) -> None:
        self._surface.select_item(item_id)

    def add_item(self, component_key: str) -> str:
        item_id = self._surface.add_item(component_key)
        self._refresh_overview()
        return item_id

    def remove_selected_item(self) -> None:
        self._surface.remove_selected_item()
        self._refresh_overview()
