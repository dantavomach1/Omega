from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from omega.ui.posters import apply_poster, apply_rounded_mask


@dataclass(frozen=True)
class SelectedShowItem:
    key: str
    title: str
    show_dirs: List[Path]
    poster_path: Optional[Path] = None
    backdrop_path: Optional[Path] = None
    title_id: str = ""


class ShowSelectionTray(QWidget):
    removeRequested = Signal(str)
    clearRequested = Signal()
    startRequested = Signal()
    smartStartRequested = Signal()
    closeRequested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("showSelectionTray")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setMinimumWidth(332)
        self.setMaximumWidth(468)
        self._card_width = 136
        self._card_height = 154
        self._card_art_width = 116
        self._card_art_height = 68
        self._grid_spacing = 10

        self._items: Dict[str, SelectedShowItem] = {}
        self._cards: Dict[str, QWidget] = {}
        self._order: List[str] = []
        self._grid_columns = 2

        self._build_ui()
        self._refresh_count()
        self._refresh_empty_state()

    def selected_count(self) -> int:
        return len(self._order)

    def has_item(self, key: str) -> bool:
        return str(key) in self._items

    def upsert_item(self, item: SelectedShowItem) -> None:
        key = str(item.key)
        exists = key in self._items
        self._items[key] = item

        if not exists:
            self._order.append(key)
            self._cards[key] = self._build_card(item)
        else:
            self._refresh_card(key)

        self._reflow_grid()
        self._refresh_count()
        self._refresh_empty_state()

    def remove_item(self, key: str) -> None:
        key = str(key)
        self._items.pop(key, None)

        if key in self._order:
            self._order.remove(key)

        card = self._cards.pop(key, None)
        if card is not None:
            card.setParent(None)
            card.deleteLater()

        self._reflow_grid()
        self._refresh_count()
        self._refresh_empty_state()

    def clear_items(self) -> None:
        self._items.clear()
        self._order.clear()
        for key in list(self._cards.keys()):
            card = self._cards.pop(key, None)
            if card is not None:
                card.setParent(None)
                card.deleteLater()
        self._reflow_grid()
        self._refresh_count()
        self._refresh_empty_state()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        cols = self._compute_columns()
        if cols != self._grid_columns:
            self._grid_columns = cols
            self._reflow_grid()

    def _build_ui(self) -> None:
        self.setStyleSheet(
            """
            QWidget#showSelectionTray {
                background: rgba(7,10,18,0.68);
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 24px;
            }
            QFrame#showSelectionPanel,
            QFrame#showSelectionFooter,
            QFrame#showSelectionHintPanel,
            QFrame#showSelectionEmptyState {
                background: rgba(9,14,22,0.52);
                border: 1px solid rgba(255,255,255,0.16);
                border-radius: 18px;
            }
            QFrame#showSelectionCard {
                background: rgba(10,16,24,0.44);
                border: 1px solid rgba(255,255,255,0.18);
                border-radius: 18px;
            }
            QLabel#showSelectionHeaderTitle {
                color: #ffffff;
                font-size: 18px;
                font-weight: 700;
                background: transparent;
            }
            QLabel#showSelectionCount {
                color: rgba(255,255,255,0.86);
                background: transparent;
            }
            QLabel#showSelectionHint,
            QLabel#showSelectionEmptyBody {
                color: rgba(255,255,255,0.72);
                background: transparent;
            }
            QLabel#showSelectionEmptyTitle {
                color: #ffffff;
                font-size: 15px;
                font-weight: 700;
                background: transparent;
            }
            QLabel#showSelectionCardTitle {
                color: #ffffff;
                background: transparent;
                font-size: 13px;
                font-weight: 700;
            }
            QLabel#showSelectionCardMeta {
                color: rgba(255,255,255,0.72);
                background: transparent;
                font-size: 11px;
            }
            QPushButton {
                color: #ffffff;
                background: rgba(10,16,24,0.68);
                border: 1px solid rgba(255,255,255,0.22);
                border-radius: 11px;
                padding: 8px 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: rgba(14,22,34,0.92);
            }
            QPushButton#showSelectionCloseBtn,
            QPushButton#showSelectionRemoveBtn {
                min-width: 34px;
                min-height: 34px;
                padding: 0px;
                font-size: 14px;
            }
            QPushButton#showSelectionStartBtn {
                background: rgba(95,160,255,0.36);
                border: 1px solid rgba(95,160,255,0.85);
                font-weight: 700;
            }
            QPushButton#showSelectionStartBtn:hover {
                background: rgba(95,160,255,0.44);
            }
            QPushButton#showSelectionSmartBtn {
                background: rgba(65,210,150,0.26);
                border: 1px solid rgba(65,210,150,0.82);
                font-weight: 700;
            }
            QPushButton#showSelectionSmartBtn:hover {
                background: rgba(65,210,150,0.38);
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        header_panel = QFrame(self)
        header_panel.setObjectName("showSelectionPanel")
        header_layout = QVBoxLayout(header_panel)
        header_layout.setContentsMargins(16, 14, 16, 14)
        header_layout.setSpacing(8)

        top = QWidget(header_panel)
        top_h = QHBoxLayout(top)
        top_h.setContentsMargins(0, 0, 0, 0)
        top_h.setSpacing(8)

        title = QLabel("Show Selection", top)
        title.setObjectName("showSelectionHeaderTitle")
        close_btn = QPushButton("X", top)
        close_btn.setObjectName("showSelectionCloseBtn")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setFocusPolicy(Qt.NoFocus)
        close_btn.clicked.connect(self.closeRequested.emit)

        top_h.addWidget(title)
        top_h.addStretch(1)
        top_h.addWidget(close_btn)

        self._count_label = QLabel("", header_panel)
        self._count_label.setObjectName("showSelectionCount")

        header_layout.addWidget(top)
        header_layout.addWidget(self._count_label)

        hint_panel = QFrame(self)
        hint_panel.setObjectName("showSelectionHintPanel")
        hint_layout = QVBoxLayout(hint_panel)
        hint_layout.setContentsMargins(16, 12, 16, 12)
        hint_layout.setSpacing(0)

        self._hint_label = QLabel(
            "Build a cleaner multi-show mix here. Pick a few titles, then launch a fast shuffle or a smarter guided mix.",
            hint_panel,
        )
        self._hint_label.setObjectName("showSelectionHint")
        self._hint_label.setWordWrap(True)
        hint_layout.addWidget(self._hint_label)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self._scroll.viewport().setStyleSheet("background: transparent; border: none;")

        self._content = QWidget(self._scroll)
        self._content.setObjectName("showSelectionGridHost")
        self._content.setStyleSheet("background: transparent; border: none;")

        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)

        self._empty_state = QFrame(self._content)
        self._empty_state.setObjectName("showSelectionEmptyState")
        empty_layout = QVBoxLayout(self._empty_state)
        empty_layout.setContentsMargins(18, 18, 18, 18)
        empty_layout.setSpacing(6)

        empty_title = QLabel("No shows stacked yet", self._empty_state)
        empty_title.setObjectName("showSelectionEmptyTitle")
        empty_body = QLabel(
            "Turn on show selection, tap a few cards, and this tray will build a compact mix board for you.",
            self._empty_state,
        )
        empty_body.setObjectName("showSelectionEmptyBody")
        empty_body.setWordWrap(True)

        empty_layout.addWidget(empty_title)
        empty_layout.addWidget(empty_body)

        self._grid_host = QWidget(self._content)
        self._grid_host.setObjectName("showSelectionGridWrap")
        self._grid_host.setStyleSheet("background: transparent; border: none;")
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(self._grid_spacing)
        self._grid.setVerticalSpacing(self._grid_spacing)
        self._grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        content_layout.addWidget(self._empty_state)
        content_layout.addWidget(self._grid_host)
        content_layout.addStretch(1)

        self._scroll.setWidget(self._content)

        footer = QFrame(self)
        footer.setObjectName("showSelectionFooter")
        bottom_h = QHBoxLayout(footer)
        bottom_h.setContentsMargins(14, 12, 14, 12)
        bottom_h.setSpacing(8)

        clear_btn = QPushButton("Clear", footer)
        clear_btn.setCursor(Qt.PointingHandCursor)
        clear_btn.setFocusPolicy(Qt.NoFocus)
        clear_btn.setMinimumHeight(40)
        clear_btn.clicked.connect(self.clearRequested.emit)

        smart_btn = QPushButton("Smart Shuffle", footer)
        smart_btn.setObjectName("showSelectionSmartBtn")
        smart_btn.setCursor(Qt.PointingHandCursor)
        smart_btn.setFocusPolicy(Qt.NoFocus)
        smart_btn.setMinimumHeight(40)
        smart_btn.clicked.connect(self.smartStartRequested.emit)

        start_btn = QPushButton("Start Shuffle", footer)
        start_btn.setObjectName("showSelectionStartBtn")
        start_btn.setCursor(Qt.PointingHandCursor)
        start_btn.setFocusPolicy(Qt.NoFocus)
        start_btn.setMinimumHeight(40)
        start_btn.clicked.connect(self.startRequested.emit)

        bottom_h.addWidget(clear_btn)
        bottom_h.addWidget(smart_btn)
        bottom_h.addStretch(1)
        bottom_h.addWidget(start_btn)

        root.addWidget(header_panel)
        root.addWidget(hint_panel)
        root.addWidget(self._scroll, 1)
        root.addWidget(footer)

    def _build_card(self, item: SelectedShowItem) -> QWidget:
        card = QFrame(self._grid_host)
        card.setObjectName("showSelectionCard")
        card.setFixedSize(self._card_width, self._card_height)
        card.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        apply_rounded_mask(card, 18)

        body = QVBoxLayout(card)
        body.setContentsMargins(10, 10, 10, 10)
        body.setSpacing(7)

        art = QLabel(card)
        art.setObjectName("showSelectionPoster")
        art.setAlignment(Qt.AlignCenter)
        art.setFixedSize(self._card_art_width, self._card_art_height)
        art.setStyleSheet(
            "background: rgba(0,0,0,0.22); border: 1px solid rgba(255,255,255,0.12); border-radius: 14px;"
        )
        art_path = item.backdrop_path or item.poster_path
        if art_path is not None:
            try:
                apply_poster(
                    art,
                    art_path,
                    radius=14,
                    fill_label=False,
                    cache_namespace=str(item.title_id or item.key or ""),
                )
            except Exception:
                pass

        title = QLabel(item.title, card)
        title.setObjectName("showSelectionCardTitle")
        title.setWordWrap(True)
        title.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        title.setMaximumHeight(32)

        meta = QLabel(
            f"{len(item.show_dirs)} source folder{'s' if len(item.show_dirs) != 1 else ''}",
            card,
        )
        meta.setObjectName("showSelectionCardMeta")
        meta.setWordWrap(True)
        meta.setMaximumHeight(24)

        footer = QWidget(card)
        footer_h = QHBoxLayout(footer)
        footer_h.setContentsMargins(0, 0, 0, 0)
        footer_h.setSpacing(6)

        remove_btn = QPushButton("X", footer)
        remove_btn.setObjectName("showSelectionRemoveBtn")
        remove_btn.setCursor(Qt.PointingHandCursor)
        remove_btn.setFocusPolicy(Qt.NoFocus)
        remove_btn.clicked.connect(lambda _=False, k=item.key: self.removeRequested.emit(str(k)))

        footer_h.addStretch(1)
        footer_h.addWidget(remove_btn)

        body.addWidget(art, 0, Qt.AlignHCenter)
        body.addWidget(title)
        body.addWidget(meta)
        body.addStretch(1)
        body.addWidget(footer)
        return card

    def _refresh_card(self, key: str) -> None:
        key = str(key)
        old = self._cards.pop(key, None)
        if old is not None:
            old.setParent(None)
            old.deleteLater()
        item = self._items.get(key)
        if item is None:
            return
        self._cards[key] = self._build_card(item)

    def _refresh_count(self) -> None:
        count = len(self._order)
        suffix = "show" if count == 1 else "shows"
        self._count_label.setText(f"{count} selected {suffix}")

    def _refresh_empty_state(self) -> None:
        has_items = bool(self._order)
        self._empty_state.setVisible(not has_items)
        self._grid_host.setVisible(has_items)

    def _compute_columns(self) -> int:
        available = max(1, int(self.width()) - 28)
        cols = max(1, (available + self._grid_spacing) // (self._card_width + self._grid_spacing))
        return max(1, min(3, int(cols)))

    def _reflow_grid(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(self._grid_host)

        cols = self._compute_columns()
        self._grid_columns = cols
        for index, key in enumerate(self._order):
            card = self._cards.get(key)
            if card is None:
                continue
            row = int(index // cols)
            col = int(index % cols)
            self._grid.addWidget(card, row, col, 1, 1, Qt.AlignLeft | Qt.AlignTop)

        self._grid.setColumnStretch(cols, 1)
