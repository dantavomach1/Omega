from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from omega.ui.posters import cover_pixmap_cached, rounded_cover_pixmap_cached


@dataclass(frozen=True)
class ViewerProfileCard:
    profile_id: str
    name: str
    accent_color: str = "#5CA0FF"
    avatar_art_path: Optional[Path] = None
    tagline: str = ""


class StartupBackdropWidget(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._image_path: Optional[Path] = None
        self._cache_sig = ""
        self._cache_pixmap = None
        self._primary = QColor("#5CA0FF")
        self._secondary = QColor("#4FD4B3")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def set_image_path(self, image_path: Optional[Path]) -> None:
        self._image_path = Path(str(image_path)) if image_path is not None else None
        self._cache_sig = ""
        self.update()

    def set_theme(self, primary: str, secondary: str) -> None:
        self._primary = QColor(str(primary or "#5CA0FF"))
        if not self._primary.isValid():
            self._primary = QColor("#5CA0FF")
        self._secondary = QColor(str(secondary or "#4FD4B3"))
        if not self._secondary.isValid():
            self._secondary = QColor("#4FD4B3")
        self.update()

    def _refresh_cache(self) -> None:
        key = str(self._image_path or "")
        sig = f"{key}|{self.width()}x{self.height()}"
        if sig == self._cache_sig:
            return
        self._cache_sig = sig
        self._cache_pixmap = None
        if self._image_path is None:
            return
        src = cover_pixmap_cached(self._image_path, max(1, self.width()), max(1, self.height()))
        if src.isNull():
            return
        blurred = src
        for factor in (0.18, 0.12):
            small_w = max(1, int(round(float(src.width()) * factor)))
            small_h = max(1, int(round(float(src.height()) * factor)))
            blurred = blurred.scaled(small_w, small_h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            blurred = blurred.scaled(src.width(), src.height(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        self._cache_pixmap = blurred

    def paintEvent(self, _event) -> None:
        self._refresh_cache()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect()
        painter.fillRect(rect, QColor("#04070B"))
        if self._cache_pixmap is not None and not self._cache_pixmap.isNull():
            painter.drawPixmap(rect, self._cache_pixmap)

        top_wash = QLinearGradient(0.0, 0.0, float(rect.width()), float(rect.height()))
        top_wash.setColorAt(0.0, QColor(4, 8, 14, 184))
        top_wash.setColorAt(0.5, QColor(8, 12, 20, 118))
        top_wash.setColorAt(1.0, QColor(2, 4, 8, 214))
        painter.fillRect(rect, top_wash)

        aurora = QRadialGradient(float(rect.width()) * 0.76, float(rect.height()) * 0.18, max(120.0, float(rect.width()) * 0.44))
        aurora.setColorAt(0.0, QColor(self._primary.red(), self._primary.green(), self._primary.blue(), 84))
        aurora.setColorAt(0.48, QColor(self._secondary.red(), self._secondary.green(), self._secondary.blue(), 30))
        aurora.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(rect, aurora)


class SpinnerWidget(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._tick = 0
        self._accent = QColor("#5CA0FF")
        self._timer = QTimer(self)
        self._timer.setInterval(72)
        self._timer.timeout.connect(self._advance)
        self._timer.start()
        self.setFixedSize(78, 78)

    def set_accent(self, accent: str) -> None:
        self._accent = QColor(str(accent or "#5CA0FF"))
        if not self._accent.isValid():
            self._accent = QColor("#5CA0FF")
        self.update()

    def _advance(self) -> None:
        self._tick = (int(self._tick) + 1) % 12
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.translate(self.width() / 2.0, self.height() / 2.0)
        for index in range(12):
            painter.save()
            painter.rotate(float(index * 30))
            phase = (index + int(self._tick)) % 12
            alpha = 40 + int(phase * 16)
            color = QColor(self._accent)
            color.setAlpha(min(255, alpha))
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(-4, -30, 8, 18, 4, 4)
            painter.restore()


class ProfileArtWidget(QWidget):
    def __init__(
        self,
        *,
        name: str,
        accent_color: str,
        art_path: Optional[Path] = None,
        add_mode: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._name = str(name or "")
        self._accent_color = str(accent_color or "#5CA0FF")
        self._art_path = Path(str(art_path)) if art_path is not None else None
        self._add_mode = bool(add_mode)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setFixedSize(168, 168)

    def set_profile(
        self,
        *,
        name: Optional[str] = None,
        accent_color: Optional[str] = None,
        art_path: Optional[Path] = None,
        add_mode: Optional[bool] = None,
    ) -> None:
        if name is not None:
            self._name = str(name or "")
        if accent_color is not None:
            self._accent_color = str(accent_color or "#5CA0FF")
        if add_mode is not None:
            self._add_mode = bool(add_mode)
        self._art_path = Path(str(art_path)) if art_path is not None and str(art_path).strip() else None
        self.update()

    def _initials(self) -> str:
        parts = [part[:1].upper() for part in str(self._name).split() if part]
        if not parts:
            return "?"
        return "".join(parts[:2])

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect().adjusted(2, 2, -2, -2)
        radius = 30.0
        path = QPainterPath()
        path.addRoundedRect(float(rect.x()), float(rect.y()), float(rect.width()), float(rect.height()), radius, radius)
        painter.setClipPath(path)

        art = rounded_cover_pixmap_cached(self._art_path, rect.width(), rect.height(), 30)
        has_art = not art.isNull()
        accent = QColor(self._accent_color)
        if not accent.isValid():
            accent = QColor("#5CA0FF")

        if has_art:
            painter.drawPixmap(rect, art)
            glaze = QLinearGradient(float(rect.left()), float(rect.top()), float(rect.left()), float(rect.bottom()))
            glaze.setColorAt(0.0, QColor(255, 255, 255, 38))
            glaze.setColorAt(0.35, QColor(255, 255, 255, 10))
            glaze.setColorAt(1.0, QColor(0, 0, 0, 116))
            painter.fillPath(path, glaze)
        else:
            accent_dark = QColor(accent)
            accent_dark = accent_dark.darker(245)
            fill = QLinearGradient(float(rect.left()), float(rect.top()), float(rect.right()), float(rect.bottom()))
            fill.setColorAt(0.0, accent)
            fill.setColorAt(1.0, accent_dark)
            painter.fillPath(path, fill)

        halo = QRadialGradient(float(rect.center().x()), float(rect.top()) + 28.0, float(rect.width()) * 0.72)
        halo.setColorAt(0.0, QColor(255, 255, 255, 50))
        halo.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillPath(path, halo)

        painter.setClipping(False)
        painter.setPen(QPen(QColor(255, 255, 255, 92), 1.35))
        painter.drawPath(path)
        painter.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 188), 2.0))
        painter.drawRoundedRect(rect.adjusted(5, 5, -5, -5), 24, 24)

        text_font = QFont()
        text_font.setBold(True)
        text_font.setPointSize(30)
        painter.setFont(text_font)
        painter.setPen(QColor(255, 255, 255, 236))
        if self._add_mode:
            painter.drawText(rect, Qt.AlignCenter, "+")
            return
        if has_art:
            return
        painter.drawText(rect, Qt.AlignCenter, self._initials())


class ProfileCardButton(QPushButton):
    def __init__(
        self,
        profile: ViewerProfileCard,
        *,
        add_mode: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.profile_id = str(profile.profile_id or "")
        self._accent_color = str(profile.accent_color or "#5CA0FF")
        self._add_mode = bool(add_mode)
        self.setObjectName("viewerProfileCardButton")
        self.setCursor(Qt.PointingHandCursor)
        self.setFlat(True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setMinimumSize(220, 292)
        self.setMaximumWidth(254)

        body = QVBoxLayout(self)
        body.setContentsMargins(14, 14, 14, 14)
        body.setSpacing(12)

        badge_row = QHBoxLayout()
        badge_row.setContentsMargins(0, 0, 0, 0)
        badge_row.setSpacing(8)
        badge = QLabel("Create" if add_mode else "Private Suite", self)
        badge.setObjectName("viewerProfileCardBadge")
        accent_chip = QLabel("Ready" if not add_mode else "New", self)
        accent_chip.setObjectName("viewerProfileCardAccent")
        accent_chip.setStyleSheet(
            f"background: rgba({QColor(self._accent_color).red()}, {QColor(self._accent_color).green()}, {QColor(self._accent_color).blue()}, 46);"
            f"border: 1px solid rgba({QColor(self._accent_color).red()}, {QColor(self._accent_color).green()}, {QColor(self._accent_color).blue()}, 154);"
        )
        badge_row.addWidget(badge, 0, Qt.AlignLeft)
        badge_row.addStretch(1)
        badge_row.addWidget(accent_chip, 0, Qt.AlignRight)
        body.addLayout(badge_row)

        self._art = ProfileArtWidget(
            name=profile.name,
            accent_color=profile.accent_color,
            art_path=profile.avatar_art_path,
            add_mode=bool(add_mode),
            parent=self,
        )
        self._art.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        body.addWidget(self._art, 0, Qt.AlignHCenter)

        self._title = QLabel("Add Profile" if add_mode else str(profile.name or "Profile"), self)
        self._title.setObjectName("viewerProfileCardTitle")
        self._title.setAlignment(Qt.AlignHCenter)
        self._title.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        body.addWidget(self._title)

        meta_text = (
            "Create a new room with its own palette, momentum, and watch identity."
            if add_mode
            else str(profile.tagline or "Continue watching, saved mixes, and personal atmosphere.")
        )
        self._meta = QLabel(meta_text, self)
        self._meta.setObjectName("viewerProfileCardMeta")
        self._meta.setAlignment(Qt.AlignHCenter)
        self._meta.setWordWrap(True)
        self._meta.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        body.addWidget(self._meta)
        body.addStretch(1)


class StartupProfileGate(QWidget):
    profileChosen = Signal(str)
    addProfileRequested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("viewerStartupGate")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)

        self._cards: List[ViewerProfileCard] = []
        self._card_buttons: List[QPushButton] = []
        self._allow_add = True
        self._theme: Dict[str, str] = {
            "primary": "#5CA0FF",
            "secondary": "#4FD4B3",
            "text": "#F4F7FF",
            "muted_text": "#B4C0D8",
            "background": "#05070B",
            "background_alt": "#0F1320",
            "card": "#141A29",
            "border": "#2A3449",
        }

        self._backdrop = StartupBackdropWidget(self)
        self._scrim = QWidget(self)
        self._scrim.setObjectName("viewerStartupScrim")
        self._content = QWidget(self)
        self._content.setObjectName("viewerStartupGateContent")

        root = QVBoxLayout(self._content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._stack = QStackedLayout()
        self._stack.setStackingMode(QStackedLayout.StackOne)
        root.addLayout(self._stack, 1)

        chooser = QWidget(self._content)
        chooser_l = QVBoxLayout(chooser)
        chooser_l.setContentsMargins(88, 66, 88, 66)
        chooser_l.setSpacing(20)
        chooser_l.addStretch(1)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(14)

        self._eyebrow = QLabel("OMEGA", chooser)
        self._eyebrow.setObjectName("viewerGateEyebrow")
        self._status_chip = QLabel("Up to 5 profiles", chooser)
        self._status_chip.setObjectName("viewerGateStatusChip")
        top.addWidget(self._eyebrow)
        top.addStretch(1)
        top.addWidget(self._status_chip)

        self._title = QLabel("Choose your suite", chooser)
        self._title.setObjectName("viewerGateTitle")
        self._subtitle = QLabel(
            "Step into a profile to restore its momentum, saved mixes, subtitle defaults, and visual atmosphere.",
            chooser,
        )
        self._subtitle.setObjectName("viewerGateSubtitle")
        self._subtitle.setWordWrap(True)
        self._subtitle.setMaximumWidth(820)

        self._grid_host = QWidget(chooser)
        self._grid_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(0, 18, 0, 0)
        self._grid.setHorizontalSpacing(22)
        self._grid.setVerticalSpacing(24)
        self._grid.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)

        chooser_l.addLayout(top)
        chooser_l.addWidget(self._title)
        chooser_l.addWidget(self._subtitle)
        chooser_l.addWidget(self._grid_host, 0, Qt.AlignHCenter)
        chooser_l.addStretch(2)

        loading = QWidget(self._content)
        loading_l = QVBoxLayout(loading)
        loading_l.setContentsMargins(88, 66, 88, 66)
        loading_l.setSpacing(16)
        loading_l.addStretch(1)

        self._loading_badge = QLabel("Restoring your theater", loading)
        self._loading_badge.setObjectName("viewerGateStatusChip")
        loading_l.addWidget(self._loading_badge, 0, Qt.AlignHCenter)

        self._spinner = SpinnerWidget(loading)
        loading_l.addWidget(self._spinner, 0, Qt.AlignHCenter)

        self._loading_title = QLabel("Loading your profile...", loading)
        self._loading_title.setObjectName("viewerLoadingTitle")
        self._loading_title.setAlignment(Qt.AlignHCenter)
        loading_l.addWidget(self._loading_title)

        self._loading_detail = QLabel("Restoring your background, list, and home atmosphere.", loading)
        self._loading_detail.setObjectName("viewerLoadingDetail")
        self._loading_detail.setAlignment(Qt.AlignHCenter)
        self._loading_detail.setWordWrap(True)
        self._loading_detail.setMaximumWidth(620)
        loading_l.addWidget(self._loading_detail, 0, Qt.AlignHCenter)
        loading_l.addStretch(1)

        self._stack.addWidget(chooser)
        self._stack.addWidget(loading)
        self._stack.setCurrentIndex(0)

        self.apply_theme(dict(self._theme))

    def apply_theme(self, colors: Dict[str, str]) -> None:
        palette = dict(self._theme)
        for key, value in (colors or {}).items():
            if str(value or "").strip():
                palette[str(key)] = str(value)
        self._theme = palette

        primary = QColor(str(palette.get("primary", "#5CA0FF")))
        secondary = QColor(str(palette.get("secondary", "#4FD4B3")))
        text = str(palette.get("text", "#F4F7FF"))
        muted = str(palette.get("muted_text", "#B4C0D8"))
        surface = str(palette.get("surface_soft", palette.get("card", "#141A29")))
        border = str(palette.get("border", "#2A3449"))

        if not primary.isValid():
            primary = QColor("#5CA0FF")
        if not secondary.isValid():
            secondary = QColor("#4FD4B3")

        self._backdrop.set_theme(primary.name(), secondary.name())
        self._spinner.set_accent(primary.name())
        self._scrim.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            f"stop:0 rgba(3,6,10,190), stop:0.46 rgba({primary.red()}, {primary.green()}, {primary.blue()}, 32), "
            f"stop:1 rgba(3,6,10,214));"
        )

        self.setStyleSheet(
            f"""
            QWidget#viewerStartupGate {{
                background: transparent;
            }}
            QWidget#viewerStartupGateContent {{
                background: transparent;
            }}
            QLabel#viewerGateEyebrow {{
                color: rgba({secondary.red()}, {secondary.green()}, {secondary.blue()}, 228);
                font-size: 13px;
                font-weight: 800;
                letter-spacing: 1.2px;
                background: transparent;
            }}
            QLabel#viewerGateTitle {{
                color: {text};
                font-size: 48px;
                font-weight: 900;
                background: transparent;
            }}
            QLabel#viewerGateSubtitle {{
                color: {muted};
                font-size: 15px;
                line-height: 1.34em;
                background: transparent;
            }}
            QLabel#viewerGateStatusChip {{
                color: {text};
                background: rgba({primary.red()}, {primary.green()}, {primary.blue()}, 36);
                border: 1px solid rgba({primary.red()}, {primary.green()}, {primary.blue()}, 150);
                border-radius: 13px;
                padding: 6px 12px;
                font-size: 12px;
                font-weight: 800;
            }}
            QPushButton#viewerProfileCardButton {{
                background: rgba(14, 18, 26, 176);
                border: 1px solid {border};
                border-radius: 30px;
                padding: 0px;
            }}
            QPushButton#viewerProfileCardButton:hover {{
                background: rgba({primary.red()}, {primary.green()}, {primary.blue()}, 28);
                border: 1px solid rgba({primary.red()}, {primary.green()}, {primary.blue()}, 176);
            }}
            QLabel#viewerProfileCardBadge {{
                color: {muted};
                background: rgba(255,255,255,12);
                border: 1px solid rgba(255,255,255,20);
                border-radius: 11px;
                padding: 5px 9px;
                font-size: 11px;
                font-weight: 700;
            }}
            QLabel#viewerProfileCardAccent {{
                color: {text};
                border-radius: 11px;
                padding: 5px 9px;
                font-size: 11px;
                font-weight: 700;
            }}
            QLabel#viewerProfileCardTitle {{
                color: {text};
                font-size: 20px;
                font-weight: 800;
                background: transparent;
            }}
            QLabel#viewerProfileCardMeta {{
                color: {muted};
                font-size: 12px;
                line-height: 1.35em;
                background: transparent;
            }}
            QLabel#viewerLoadingTitle {{
                color: {text};
                font-size: 30px;
                font-weight: 900;
                background: transparent;
            }}
            QLabel#viewerLoadingDetail {{
                color: {muted};
                font-size: 14px;
                line-height: 1.34em;
                background: transparent;
            }}
            QWidget#viewerStartupGateContent QFrame {{
                background: transparent;
            }}
            """
        )

        self._grid_host.setStyleSheet("background: transparent;")
        self.update()

    def set_background_image(self, image_path: Optional[Path]) -> None:
        self._backdrop.set_image_path(image_path)

    def set_profiles(self, cards: List[ViewerProfileCard], *, allow_add: bool) -> None:
        self._cards = list(cards or [])
        self._allow_add = bool(allow_add)
        self._rebuild_profile_grid()

    def show_chooser(self, *, status_text: str = "Up to 5 profiles") -> None:
        self._status_chip.setText(str(status_text or "Up to 5 profiles"))
        self._stack.setCurrentIndex(0)

    def show_loading(self, *, profile_name: str, detail: str) -> None:
        display_name = str(profile_name or "your profile")
        self._loading_title.setText(f"Loading {display_name}...")
        self._loading_detail.setText(str(detail or "Preparing Omega."))
        self._stack.setCurrentIndex(1)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        rect = self.rect()
        self._backdrop.setGeometry(rect)
        self._scrim.setGeometry(rect)
        self._content.setGeometry(rect)
        self._reflow_profile_grid()

    def _clear_grid(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._card_buttons = []

    def _rebuild_profile_grid(self) -> None:
        self._clear_grid()
        buttons: List[QPushButton] = []
        for card in self._cards:
            button = ProfileCardButton(card, parent=self._grid_host)
            button.clicked.connect(lambda _checked=False, pid=card.profile_id: self.profileChosen.emit(str(pid)))
            buttons.append(button)

        if self._allow_add:
            add_card = ViewerProfileCard(profile_id="__add__", name="Add Profile", accent_color="#94A3B8")
            add_button = ProfileCardButton(add_card, add_mode=True, parent=self._grid_host)
            add_button.clicked.connect(self.addProfileRequested.emit)
            buttons.append(add_button)

        self._card_buttons = buttons
        self._reflow_profile_grid()

    def _reflow_profile_grid(self) -> None:
        while self._grid.count():
            self._grid.takeAt(0)

        total = len(self._card_buttons)
        if total <= 0:
            return

        host_w = max(1, int(self.width()) - 240)
        cols = max(1, min(5, host_w // 244))
        cols = min(cols, max(1, total))
        for index, button in enumerate(self._card_buttons):
            row = int(index // cols)
            col = int(index % cols)
            self._grid.addWidget(button, row, col)

        for col in range(cols):
            self._grid.setColumnStretch(col, 0)
        self._grid.setColumnStretch(cols, 1)
