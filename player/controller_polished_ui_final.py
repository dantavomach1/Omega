# =========================
# omega/player/controller.py
# HIERARCHICAL RAIL SYSTEM — STABLE
# =========================

from __future__ import annotations

from dataclasses import dataclass
from PySide6.QtCore import Qt, QObject, QEvent, QTimer, QPoint, Signal
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QScrollArea,
    QVBoxLayout,
    QHBoxLayout,
    QStackedWidget,
    QSizePolicy,
    QPushButton,
    QComboBox,
    QLabel,
)
from PySide6.QtGui import QColor


# ============================================================
# CONFIG
# ============================================================

@dataclass
class RailConfig:
    reference_width: int = 1920
    base_card_width: int = 260
    base_spacing: int = 20
    card_min_width: int = 180
    card_max_width: int = 360
    spacing_min: int = 12
    spacing_max: int = 36
    total_rows: int = 3
    cards_per_row: int = 20
    aspect_ratio: float = 16 / 9
    episode_scale: float = 0.75


# ============================================================
# CARD
# ============================================================

class ClickableCard(QWidget):

    clicked = Signal(object)

    def __init__(self, color: QColor, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"background-color: {color.name()}; border-radius: 14px;"
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self)


# ============================================================
# CONTROLLER
# ============================================================

class PlayerController(QObject):

    def __init__(self, win: QMainWindow):
        super().__init__(win)

        self.win = win
        self.config = RailConfig()

        self.pages: QStackedWidget = win.findChild(QStackedWidget, "pages")
        self.homeScrollArea: QScrollArea = win.findChild(QScrollArea, "homeScrollArea")

        self.homeScrollArea.setWidgetResizable(True)
        self.homeScrollArea.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.homeScrollArea.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.viewport = self.homeScrollArea.viewport()

        self.scrollContents = QWidget()
        self.homeScrollArea.setWidget(self.scrollContents)

        self.mainLayout = QVBoxLayout(self.scrollContents)
        self.mainLayout.setContentsMargins(40, 40, 40, 40)
        self.mainLayout.setSpacing(40)

        self.rails = []
        self.expanded_episode = None

        self.current_card_width = 260
        self.current_card_height = int(260 / self.config.aspect_ratio)

        self.resize_timer = QTimer()
        self.resize_timer.setSingleShot(True)
        self.resize_timer.timeout.connect(self._update_layout)

        self.viewport.installEventFilter(self)

        self._build_rails()
        QTimer.singleShot(0, self._update_layout)

    # ============================================================

    def eventFilter(self, obj, event):
        if obj is self.viewport and event.type() == QEvent.Resize:
            self.resize_timer.start(0)
        return super().eventFilter(obj, event)

    # ============================================================

    def _create_chevrons(self, scroll):

        left = QPushButton("❮", self.win)
        right = QPushButton("❯", self.win)

        for btn in (left, right):
            btn.setFixedSize(52, 52)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: rgba(0,0,0,180);
                    color: white;
                    border-radius: 26px;
                    font-size: 22px;
                }
            """)
            btn.raise_()
            btn.show()

        left.clicked.connect(lambda: self._scroll(scroll, -1))
        right.clicked.connect(lambda: self._scroll(scroll, 1))

        return left, right

    # ============================================================

    def _build_rails(self):

        for r in range(self.config.total_rows):

            wrapper = QWidget()
            wrapper.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

            wrapperLayout = QVBoxLayout(wrapper)
            wrapperLayout.setContentsMargins(0, 0, 0, 0)

            title = QLabel(f"Rail {r+1}")
            title.setStyleSheet("color: white; font-size: 18px;")
            wrapperLayout.addWidget(title)

            scroll = QScrollArea(wrapper)
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

            inner = QWidget()
            innerLayout = QHBoxLayout(inner)
            innerLayout.setContentsMargins(0, 0, 0, 0)

            scroll.setWidget(inner)
            wrapperLayout.addWidget(scroll)

            left_btn, right_btn = self._create_chevrons(scroll)

            self.rails.append({
                "wrapper": wrapper,
                "scroll": scroll,
                "layout": innerLayout,
                "left": left_btn,
                "right": right_btn,
            })

            self.mainLayout.addWidget(wrapper)

        self.mainLayout.addStretch(1)

    # ============================================================

    def _solve_layout(self, viewport_width):

        scale = viewport_width / self.config.reference_width

        card_w = int(self.config.base_card_width * scale)
        card_w = max(self.config.card_min_width,
                     min(self.config.card_max_width, card_w))

        spacing = int(self.config.base_spacing * scale)
        spacing = max(self.config.spacing_min,
                      min(self.config.spacing_max, spacing))

        card_h = int(card_w / self.config.aspect_ratio)

        return card_w, spacing, card_h

    # ============================================================

    def _update_layout(self):

        viewport_width = self.viewport.width()
        if viewport_width <= 0:
            return

        card_w, spacing, card_h = self._solve_layout(viewport_width)

        self.current_card_width = card_w
        self.current_card_height = card_h

        for rail in self.rails:

            layout = rail["layout"]

            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

            layout.setSpacing(spacing)

            for i in range(self.config.cards_per_row):
                color = QColor(
                    (i * 43) % 255,
                    (i * 71) % 255,
                    (i * 91) % 255,
                )

                card = ClickableCard(color)
                card.setFixedSize(card_w, card_h)

                # Store rail wrapper for correct insertion
                card.rail_wrapper = rail["wrapper"]

                card.clicked.connect(self._toggle_episode_rail)
                layout.addWidget(card)

            rail["wrapper"].setFixedHeight(card_h + 100)

        QTimer.singleShot(0, self._position_chevrons)

        if self.expanded_episode:
            self._scale_episode()

    # ============================================================

    def _position_chevrons(self):

        viewport_width = self.viewport.width()

        for rail in self.rails:

            scroll = rail["scroll"]
            global_pos = scroll.mapTo(self.win, QPoint(0, 0))
            center_y = global_pos.y() + scroll.height() // 2 - 26

            rail["left"].move(0, center_y)
            rail["right"].move(viewport_width - 52, center_y)

            rail["left"].raise_()
            rail["right"].raise_()

        if self.expanded_episode:
            scroll = self.expanded_episode["scroll"]
            global_pos = scroll.mapTo(self.win, QPoint(0, 0))
            center_y = global_pos.y() + scroll.height() // 2 - 26

            self.expanded_episode["left"].move(0, center_y)
            self.expanded_episode["right"].move(viewport_width - 52, center_y)

            self.expanded_episode["left"].raise_()
            self.expanded_episode["right"].raise_()

    # ============================================================

    def _toggle_episode_rail(self, card):

        target_wrapper = card.rail_wrapper

        # If already open
        if self.expanded_episode:

            if self.expanded_episode["parent_wrapper"] == target_wrapper:
                self.mainLayout.removeWidget(self.expanded_episode["wrapper"])
                self.expanded_episode["wrapper"].deleteLater()
                self.expanded_episode = None
                return

            self.mainLayout.removeWidget(self.expanded_episode["wrapper"])
            self.expanded_episode["wrapper"].deleteLater()
            self.expanded_episode = None

        wrapper = QWidget()
        wrapperLayout = QVBoxLayout(wrapper)

        title = QLabel("Episodes")
        title.setStyleSheet("color: white; font-size: 18px;")
        wrapperLayout.addWidget(title)

        season = QComboBox()
        season.addItems(["Season 1", "Season 2", "Season 3"])
        wrapperLayout.addWidget(season)

        scroll = QScrollArea(wrapper)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        inner = QWidget()
        innerLayout = QHBoxLayout(inner)
        innerLayout.setContentsMargins(0, 0, 0, 0)

        scroll.setWidget(inner)
        wrapperLayout.addWidget(scroll)

        left_btn, right_btn = self._create_chevrons(scroll)

        episode_cards = []

        for i in range(20):
            ep = ClickableCard(QColor(120, 120, 255))
            episode_cards.append(ep)
            innerLayout.addWidget(ep)

        rail_index = self.mainLayout.indexOf(target_wrapper)
        self.mainLayout.insertWidget(rail_index + 1, wrapper)

        self.expanded_episode = {
            "wrapper": wrapper,
            "scroll": scroll,
            "left": left_btn,
            "right": right_btn,
            "cards": episode_cards,
            "parent_wrapper": target_wrapper,
        }

        self._scale_episode()

    # ============================================================

    def _scale_episode(self):

        episode_w = int(self.current_card_width * self.config.episode_scale)
        episode_h = int(episode_w / self.config.aspect_ratio)

        for ep in self.expanded_episode["cards"]:
            ep.setFixedSize(episode_w, episode_h)

        self.expanded_episode["wrapper"].setFixedHeight(episode_h + 120)

        QTimer.singleShot(0, self._position_chevrons)

    # ============================================================

    def _scroll(self, scroll, direction):
        bar = scroll.horizontalScrollBar()
        bar.setValue(bar.value() + direction * 400)