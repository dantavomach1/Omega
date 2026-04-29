from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from omega.ui.posters import apply_rounded_mask, cover_pixmap_cached, rounded_cover_pixmap_cached


@dataclass(frozen=True)
class HeroEntry:
    content_key: str
    title: str
    subtitle: str
    overview: str
    image_path: Optional[Path]
    poster_path: Optional[Path] = None
    media_type: str = ""
    eyebrow: str = ""
    badges: tuple[str, ...] = ()
    supporting: str = ""


class HomeHeroCarousel(QFrame):
    """
    Premium hero used by the Home page.

    This widget stays self-contained on purpose:
    - controller.py decides *what* to show
    - this class decides *how* the hero feels on screen

    Keeping that split makes future Home polish much safer.
    """

    playRequested = Signal(str)
    infoRequested = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("homeHeroCarousel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)

        self._items: List[HeroEntry] = []
        self._index = 0
        self._last_render_size = (0, 0, 0, 0)
        self._pending_render_size = (0, 0, 0, 0)
        self._last_mask_signature = (0, 0, 0, 0)
        self._last_bg_cache_key = 0
        self._last_poster_cache_key = 0
        self._badge_labels: List[QLabel] = []
        self._accent_hex = "#5CA0FF"
        self._experience: dict[str, str] = {}

        self._bg = QLabel(self)
        self._bg.setObjectName("heroBackground")
        self._bg.setScaledContents(False)
        self._bg.setStyleSheet("background: transparent; border-radius: 22px;")

        self._shade = QWidget(self)
        self._shade.setObjectName("heroShade")
        self._shade.setAttribute(Qt.WA_StyledBackground, True)

        self._atmosphere = QWidget(self)
        self._atmosphere.setObjectName("heroAtmosphere")
        self._atmosphere.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        root = QHBoxLayout(self._shade)
        root.setContentsMargins(38, 30, 34, 26)
        root.setSpacing(24)

        left = QVBoxLayout()
        left.setSpacing(10)

        self._eyebrow = QLabel("", self._shade)
        self._eyebrow.setObjectName("heroEyebrow")
        self._eyebrow.setWordWrap(True)

        self._title = QLabel("", self._shade)
        self._title.setObjectName("heroTitle")
        self._title.setWordWrap(True)

        self._meta = QLabel("", self._shade)
        self._meta.setObjectName("heroMeta")
        self._meta.setWordWrap(True)

        self._badge_wrap = QWidget(self._shade)
        self._badge_wrap.setObjectName("heroBadgeWrap")
        self._badge_wrap.setStyleSheet("background: transparent;")
        self._badge_layout = QHBoxLayout(self._badge_wrap)
        self._badge_layout.setContentsMargins(0, 0, 0, 0)
        self._badge_layout.setSpacing(8)
        self._badge_layout.addStretch(1)

        self._overview = QLabel("", self._shade)
        self._overview.setObjectName("heroOverview")
        self._overview.setWordWrap(True)
        self._overview.setMaximumHeight(116)

        self._supporting = QLabel("", self._shade)
        self._supporting.setObjectName("heroSupporting")
        self._supporting.setWordWrap(True)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self._play_btn = QPushButton("Play Now", self._shade)
        self._play_btn.setObjectName("heroPrimaryBtn")
        self._play_btn.setCursor(Qt.PointingHandCursor)
        self._play_btn.setFocusPolicy(Qt.StrongFocus)
        self._play_btn.setAutoDefault(False)

        self._info_btn = QPushButton("Open Details", self._shade)
        self._info_btn.setObjectName("heroGhostBtn")
        self._info_btn.setCursor(Qt.PointingHandCursor)
        self._info_btn.setFocusPolicy(Qt.StrongFocus)
        self._info_btn.setAutoDefault(False)

        btn_row.addWidget(self._play_btn)
        btn_row.addWidget(self._info_btn)
        btn_row.addStretch(1)

        self._hint = QLabel("Left/Right to browse  |  Enter to play", self._shade)
        self._hint.setObjectName("heroHint")

        left.addWidget(self._eyebrow)
        left.addWidget(self._title)
        left.addWidget(self._meta)
        left.addWidget(self._badge_wrap)
        left.addWidget(self._overview)
        left.addWidget(self._supporting)
        left.addSpacing(4)
        left.addLayout(btn_row)
        left.addWidget(self._hint)
        left.addStretch(1)

        right = QVBoxLayout()
        right.setSpacing(12)
        right.addStretch(1)

        # These back cards are simple depth cues.
        # They make the poster feel intentionally staged instead of flat.
        self._poster_back_far = QFrame(self._shade)
        self._poster_back_far.setObjectName("heroPosterBackFar")
        self._poster_back_far.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self._poster_back_near = QFrame(self._shade)
        self._poster_back_near.setObjectName("heroPosterBackNear")
        self._poster_back_near.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self._poster_card = QLabel(self._shade)
        self._poster_card.setObjectName("heroPosterCard")
        self._poster_card.setMinimumSize(150, 220)
        self._poster_card.setMaximumSize(248, 368)
        self._poster_card.setAlignment(Qt.AlignCenter)

        poster_stack = QWidget(self._shade)
        poster_stack.setObjectName("heroPosterStack")
        poster_stack.setStyleSheet("background: transparent;")
        poster_stack_l = QVBoxLayout(poster_stack)
        poster_stack_l.setContentsMargins(0, 0, 0, 0)
        poster_stack_l.setSpacing(0)
        poster_stack_l.addWidget(self._poster_card, 0, Qt.AlignRight)
        right.addWidget(poster_stack, 0, Qt.AlignRight)

        self._curation_label = QLabel("Curated for tonight", self._shade)
        self._curation_label.setObjectName("heroCurationLabel")

        self._dots = QLabel("", self._shade)
        self._dots.setObjectName("heroDots")

        self._prev_btn = QPushButton("<", self._shade)
        self._prev_btn.setObjectName("heroNavBtn")
        self._prev_btn.setCursor(Qt.PointingHandCursor)
        self._prev_btn.setFocusPolicy(Qt.StrongFocus)
        self._prev_btn.setFixedWidth(46)
        self._prev_btn.setAutoDefault(False)

        self._next_btn = QPushButton(">", self._shade)
        self._next_btn.setObjectName("heroNavBtn")
        self._next_btn.setCursor(Qt.PointingHandCursor)
        self._next_btn.setFocusPolicy(Qt.StrongFocus)
        self._next_btn.setFixedWidth(46)
        self._next_btn.setAutoDefault(False)

        self._index_lbl = QLabel("0 / 0", self._shade)
        self._index_lbl.setObjectName("heroIndex")

        nav = QHBoxLayout()
        nav.setSpacing(8)
        nav.addWidget(self._prev_btn)
        nav.addWidget(self._next_btn)
        nav.addWidget(self._index_lbl)

        right.addWidget(self._curation_label, 0, Qt.AlignRight)
        right.addWidget(self._dots, 0, Qt.AlignRight)
        right.addLayout(nav)

        root.addLayout(left, 1)
        root.addLayout(right, 0)

        self._edge_left = QWidget(self)
        self._edge_left.setObjectName("heroEdgeFadeLeft")
        self._edge_left.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self._edge_right = QWidget(self)
        self._edge_right.setObjectName("heroEdgeFadeRight")
        self._edge_right.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self._timer = QTimer(self)
        self._timer.setInterval(12750)
        self._timer.timeout.connect(self.next_item)

        self._resize_render_timer = QTimer(self)
        self._resize_render_timer.setSingleShot(True)
        self._resize_render_timer.setInterval(24)
        self._resize_render_timer.timeout.connect(self._flush_resize_render)

        self._play_btn.clicked.connect(self._emit_play)
        self._info_btn.clicked.connect(self._emit_info)
        self._prev_btn.clicked.connect(self.prev_item)
        self._next_btn.clicked.connect(self.next_item)

        self.setMinimumHeight(280)
        self.apply_palette()

    def apply_palette(
        self,
        *,
        primary_hex: str = "#5CA0FF",
        secondary_hex: str = "#4FD4B3",
        text_hex: str = "#F5F7FB",
        muted_hex: str = "#B8C0D4",
        border_hex: str = "rgba(255,255,255,46)",
        card_hex: str = "rgba(11,14,24,188)",
        opaque: bool = False,
        bg_hex: str = "#05070B",
        experience: Optional[dict[str, str]] = None,
    ) -> None:
        """
        Rebuild the hero stylesheet from the active app palette.

        Keeping this centralized means the hero can stay visually aligned
        with Home, Library HQ, Settings, and the player overlay.
        """

        accent = QColor(str(primary_hex or "#5CA0FF"))
        if not accent.isValid():
            accent = QColor("#5CA0FF")
        self._accent_hex = accent.name().upper()
        accent_rgb = (accent.red(), accent.green(), accent.blue())
        secondary = QColor(str(secondary_hex or "#4FD4B3"))
        if not secondary.isValid():
            secondary = QColor("#4FD4B3")
        secondary_rgb = (secondary.red(), secondary.green(), secondary.blue())
        self._experience = {
            "hero_curation_label": "Curated for tonight",
            "hero_default_eyebrow": "TONIGHT'S SPOTLIGHT",
            "hero_hint": "Left/Right to browse  |  Enter to play",
            "hero_primary_label": "Play Now",
            "hero_secondary_label": "Open Details",
            "hero_fallback_supporting": "Picked from your Omega library because it fits the shape of the night.",
        }
        if isinstance(experience, dict):
            for key, value in experience.items():
                if str(value or "").strip():
                    self._experience[str(key)] = str(value)
        self._play_btn.setText(str(self._experience.get("hero_primary_label", "Play Now") or "Play Now"))
        self._info_btn.setText(str(self._experience.get("hero_secondary_label", "Open Details") or "Open Details"))
        self._hint.setText(str(self._experience.get("hero_hint", "Left/Right to browse  |  Enter to play") or "Left/Right to browse  |  Enter to play"))
        border = str(border_hex or "rgba(255,255,255,0.18)")
        card = str(card_hex or "rgba(11,14,24,0.74)")
        text = str(text_hex or "#F5F7FB")
        muted = str(muted_hex or "#B8C0D4")

        bg = QColor(str(bg_hex or "#05070B"))
        if not bg.isValid():
            bg = QColor("#05070B")
        bg_r, bg_g, bg_b = bg.red(), bg.green(), bg.blue()

        if opaque:
            carousel_bg = f"background: {bg_hex};"
            shade_bg = (
                f"background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
                f"stop:0 rgba({bg_r},{bg_g},{bg_b},255),"
                f"stop:0.38 rgba({bg_r},{bg_g},{bg_b},240),"
                f"stop:1 rgba({bg_r},{bg_g},{bg_b},220));"
            )
            atmo_bg = (
                f"background: qradialgradient(cx:0.82, cy:0.22, radius:0.65,"
                f"fx:0.82, fy:0.22,"
                f"stop:0 rgba({accent_rgb[0]},{accent_rgb[1]},{accent_rgb[2]},60),"
                f"stop:0.3 rgba({secondary_rgb[0]},{secondary_rgb[1]},{secondary_rgb[2]},42),"
                f"stop:0.55 rgba({accent_rgb[0]},{accent_rgb[1]},{accent_rgb[2]},14),"
                f"stop:1 rgba({bg_r},{bg_g},{bg_b},255));"
            )
        else:
            carousel_bg = (
                "background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
                "stop:0 rgba(7,10,18,255),"
                "stop:0.55 rgba(10,14,24,248),"
                "stop:1 rgba(6,8,14,255));"
            )
            shade_bg = (
                "background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
                "stop:0 rgba(4,7,12,226),"
                "stop:0.38 rgba(7,10,18,178),"
                "stop:1 rgba(7,10,18,110));"
            )
            atmo_bg = (
                f"background: qradialgradient(cx:0.82, cy:0.22, radius:0.65,"
                f"fx:0.82, fy:0.22,"
                f"stop:0 rgba({accent_rgb[0]},{accent_rgb[1]},{accent_rgb[2]},82),"
                f"stop:0.32 rgba({secondary_rgb[0]},{secondary_rgb[1]},{secondary_rgb[2]},48),"
                f"stop:0.52 rgba({accent_rgb[0]},{accent_rgb[1]},{accent_rgb[2]},18),"
                f"stop:1 rgba({accent_rgb[0]},{accent_rgb[1]},{accent_rgb[2]},0));"
            )

        self.setStyleSheet(
            f"""
            QFrame#homeHeroCarousel {{
                {carousel_bg}
                border: 1px solid rgba(255,255,255,28);
                border-radius: 22px;
            }}
            QWidget#heroShade {{
                {shade_bg}
                border-radius: 22px;
            }}
            QWidget#heroAtmosphere {{
                {atmo_bg}
                border-radius: 22px;
            }}
            QLabel#heroEyebrow {{
                color: rgba({accent_rgb[0]}, {accent_rgb[1]}, {accent_rgb[2]}, 235);
                background: transparent;
                font-size: 11px;
                font-weight: 800;
                letter-spacing: 1.2px;
                text-transform: uppercase;
            }}
            QLabel#heroTitle {{
                color: {text};
                font-size: 34px;
                font-weight: 900;
                background: transparent;
            }}
            QLabel#heroMeta {{
                color: rgba(245,247,251,212);
                font-size: 13px;
                font-weight: 600;
                background: transparent;
            }}
            QLabel#heroOverview {{
                color: rgba(236,239,245,230);
                font-size: 14px;
                line-height: 1.28em;
                background: transparent;
            }}
            QLabel#heroSupporting {{
                color: {muted};
                font-size: 12px;
                font-weight: 600;
                background: transparent;
            }}
            QLabel#heroHint {{
                color: rgba(218,224,236,176);
                font-size: 11px;
                font-weight: 600;
                background: transparent;
            }}
            QLabel#heroBadge {{
                color: rgb(247,249,253);
                background: rgba(255,255,255,16);
                border: 1px solid rgba(255,255,255,34);
                border-radius: 12px;
                padding: 5px 10px;
                font-size: 11px;
                font-weight: 700;
            }}
            QFrame#heroPosterBackFar {{
                background: rgba(255,255,255,9);
                border: 1px solid rgba(255,255,255,16);
                border-radius: 18px;
            }}
            QFrame#heroPosterBackNear {{
                background: rgba({accent_rgb[0]}, {accent_rgb[1]}, {accent_rgb[2]}, 18);
                border: 1px solid rgba({accent_rgb[0]}, {accent_rgb[1]}, {accent_rgb[2]}, 48);
                border-radius: 18px;
            }}
            QLabel#heroPosterCard {{
                background: {card};
                border: 1px solid rgba(255,255,255,36);
                border-radius: 18px;
            }}
            QWidget#heroEdgeFadeLeft {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 rgba(0,0,0,184), stop:1 rgba(0,0,0,0));
                border-top-left-radius: 22px;
                border-bottom-left-radius: 22px;
            }}
            QWidget#heroEdgeFadeRight {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 rgba(0,0,0,0), stop:1 rgba(0,0,0,184));
                border-top-right-radius: 22px;
                border-bottom-right-radius: 22px;
            }}
            QPushButton#heroPrimaryBtn {{
                color: white;
                background: rgba({accent_rgb[0]}, {accent_rgb[1]}, {accent_rgb[2]}, 214);
                border: 1px solid rgba({accent_rgb[0]}, {accent_rgb[1]}, {accent_rgb[2]}, 245);
                border-radius: 13px;
                padding: 9px 16px;
                font-size: 12px;
                font-weight: 800;
            }}
            QPushButton#heroPrimaryBtn:hover, QPushButton#heroPrimaryBtn:focus {{
                background: rgba({accent_rgb[0]}, {accent_rgb[1]}, {accent_rgb[2]}, 234);
                border: 1px solid rgba(255,255,255,215);
            }}
            QPushButton#heroGhostBtn, QPushButton#heroNavBtn {{
                color: rgb(244,246,251);
                background: rgba(6,8,14,146);
                border: 1px solid rgba(255,255,255,48);
                border-radius: 13px;
                padding: 8px 12px;
                font-size: 12px;
                font-weight: 700;
            }}
            QPushButton#heroGhostBtn:hover, QPushButton#heroGhostBtn:focus,
            QPushButton#heroNavBtn:hover, QPushButton#heroNavBtn:focus {{
                background: rgba(18,22,34,190);
                border: 1px solid rgba({accent_rgb[0]}, {accent_rgb[1]}, {accent_rgb[2]}, 205);
            }}
            QLabel#heroCurationLabel {{
                color: rgba({secondary_rgb[0]}, {secondary_rgb[1]}, {secondary_rgb[2]}, 228);
                font-size: 11px;
                font-weight: 800;
                letter-spacing: 0.9px;
                background: transparent;
            }}
            QLabel#heroDots {{
                color: rgba(255,255,255,182);
                background: transparent;
                font-size: 12px;
                font-weight: 700;
                letter-spacing: 2px;
            }}
            QLabel#heroIndex {{
                color: rgba(245,245,245,220);
                background: rgba(0,0,0,118);
                border: 1px solid {border};
                border-radius: 10px;
                padding: 5px 9px;
                font-size: 12px;
                font-weight: 700;
            }}
            """
        )
        self.update()

    def set_items(self, items: List[HeroEntry]) -> None:
        self._items = list(items or [])
        self._index = 0
        self._render_current()
        self._sync_rotation_timer()

    def set_rotation_interval_ms(self, interval_ms: int) -> None:
        try:
            ms = max(1000, int(interval_ms))
        except Exception:
            ms = 12750
        self._timer.setInterval(ms)
        self._sync_rotation_timer()

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        if self._pending_render_size != self._last_render_size and not self._resize_render_timer.isActive():
            self._resize_render_timer.start()
        self._sync_rotation_timer()

    def hideEvent(self, event) -> None:  # type: ignore[override]
        self._timer.stop()
        super().hideEvent(event)

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        key = int(event.key())
        if key in {int(Qt.Key_Left), int(Qt.Key_A)}:
            self.prev_item()
            event.accept()
            return
        if key in {int(Qt.Key_Right), int(Qt.Key_D)}:
            self.next_item()
            event.accept()
            return
        if key in {int(Qt.Key_Return), int(Qt.Key_Enter), int(Qt.Key_Space)}:
            self._emit_play()
            event.accept()
            return
        if key == int(Qt.Key_I):
            self._emit_info()
            event.accept()
            return
        super().keyPressEvent(event)

    def next_item(self) -> None:
        if not self._items:
            return
        self._index = (self._index + 1) % len(self._items)
        self._render_current()

    def prev_item(self) -> None:
        if not self._items:
            return
        self._index = (self._index - 1) % len(self._items)
        self._render_current()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._bg.setGeometry(0, 0, self.width(), self.height())
        self._atmosphere.setGeometry(0, 0, self.width(), self.height())
        self._shade.setGeometry(0, 0, self.width(), self.height())

        poster_h = max(178, min(334, int(self.height() * 0.80)))
        poster_w = max(120, int(round(float(poster_h) * 0.675)))
        self._poster_card.setFixedSize(poster_w, poster_h)
        self._overview.setMaximumHeight(max(76, min(138, int(self.height() * 0.36))))

        # Keep the depth cards slightly behind the main poster.
        poster_geo = self._poster_card.geometry()
        depth_offset_far = 18
        depth_offset_near = 10
        self._poster_back_far.setGeometry(
            poster_geo.x() - depth_offset_far,
            poster_geo.y() + 14,
            poster_geo.width(),
            poster_geo.height(),
        )
        self._poster_back_near.setGeometry(
            poster_geo.x() - depth_offset_near,
            poster_geo.y() + 8,
            poster_geo.width(),
            poster_geo.height(),
        )
        self._poster_back_far.lower()
        self._poster_back_near.lower()
        self._bg.lower()
        self._atmosphere.raise_()
        self._shade.raise_()

        edge_w = max(44, min(112, int(self.width() * 0.09)))
        self._edge_left.setGeometry(0, 0, edge_w, self.height())
        self._edge_right.setGeometry(self.width() - edge_w, 0, edge_w, self.height())
        self._edge_left.raise_()
        self._edge_right.raise_()

        render_size = (self.width(), self.height(), poster_w, poster_h)
        if render_size != self._pending_render_size:
            self._pending_render_size = render_size
        if not self._resize_render_timer.isActive():
            self._resize_render_timer.start()

    def _flush_resize_render(self) -> None:
        if not self.isVisible():
            return
        mask_signature = (
            int(self.width()),
            int(self.height()),
            int(self._poster_card.width()),
            int(self._poster_card.height()),
        )
        if mask_signature != self._last_mask_signature:
            apply_rounded_mask(self, 22)
            apply_rounded_mask(self._shade, 22)
            apply_rounded_mask(self._poster_card, 18)
            apply_rounded_mask(self._poster_back_far, 18)
            apply_rounded_mask(self._poster_back_near, 18)
            self._last_mask_signature = mask_signature
        if self._pending_render_size != self._last_render_size:
            self._last_render_size = self._pending_render_size
            self._render_current()

    def _set_badges(self, badges: Sequence[str]) -> None:
        for label in self._badge_labels:
            try:
                label.setParent(None)
                label.deleteLater()
            except Exception:
                pass
        self._badge_labels = []

        # Remove the trailing stretch so fresh badges can be inserted cleanly.
        while self._badge_layout.count():
            item = self._badge_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

        clean_badges = [str(b).strip() for b in badges if str(b).strip()]
        for text in clean_badges[:4]:
            chip = QLabel(text, self._badge_wrap)
            chip.setObjectName("heroBadge")
            self._badge_layout.addWidget(chip, 0, Qt.AlignLeft)
            self._badge_labels.append(chip)
        self._badge_layout.addStretch(1)
        self._badge_wrap.setVisible(bool(clean_badges))

    def _dots_text(self, count: int, active: int) -> str:
        if count <= 1:
            return ""
        dots: List[str] = []
        for index in range(count):
            dots.append("[#]" if index == active else "[ ]")
        return " ".join(dots[:8])

    def _render_current(self) -> None:
        count = len(self._items)
        curation_label = str(self._experience.get("hero_curation_label", "Curated for tonight") or "Curated for tonight")
        default_eyebrow = str(self._experience.get("hero_default_eyebrow", "TONIGHT'S SPOTLIGHT") or "TONIGHT'S SPOTLIGHT")
        default_supporting = str(
            self._experience.get("hero_fallback_supporting", "Picked from your Omega library because it fits the shape of the night.")
            or "Picked from your Omega library because it fits the shape of the night."
        )
        if count <= 0:
            self._eyebrow.setText(default_eyebrow or "HOME SPOTLIGHT")
            self._title.setText("No featured media yet")
            self._meta.setText("Build your library to unlock a cinematic hero carousel")
            self._overview.setText("Add movies and shows, then metadata enrichment will surface great picks here.")
            self._supporting.setText("Omega will start hand-composing this area as soon as the library has enough verified titles.")
            self._curation_label.setText(curation_label)
            self._dots.setText("")
            self._index_lbl.setText("0 / 0")
            self._set_badges(())
            self._bg.clear()
            self._poster_card.clear()
            self._last_bg_cache_key = 0
            self._last_poster_cache_key = 0
            return

        item = self._items[self._index]

        eyebrow = str(item.eyebrow or "").strip()
        if not eyebrow:
            eyebrow = default_eyebrow
        self._eyebrow.setText(eyebrow)
        self._title.setText(str(item.title or "Untitled"))
        self._meta.setText(str(item.subtitle or ""))
        self._overview.setText(str(item.overview or ""))
        self._supporting.setText(str(item.supporting or default_supporting))
        self._curation_label.setText(curation_label)
        self._dots.setText(self._dots_text(count, self._index))
        self._index_lbl.setText(f"{self._index + 1} / {count}")
        self._set_badges(item.badges)

        bg_src = item.image_path or item.poster_path
        bg_px = cover_pixmap_cached(bg_src, self.width(), self.height())
        if bg_px.isNull() and item.poster_path is not None and item.poster_path != bg_src:
            bg_px = cover_pixmap_cached(item.poster_path, self.width(), self.height())
        bg_key = int(bg_px.cacheKey()) if not bg_px.isNull() else 0
        if bg_key != int(self._last_bg_cache_key):
            if bg_px.isNull():
                self._bg.clear()
            else:
                self._bg.setPixmap(bg_px)
            self._last_bg_cache_key = bg_key

        poster_src = item.poster_path or item.image_path
        target = self._poster_card.size()
        poster_px = rounded_cover_pixmap_cached(poster_src, target.width(), target.height(), 18)
        poster_key = int(poster_px.cacheKey()) if not poster_px.isNull() else 0
        if poster_key != int(self._last_poster_cache_key):
            if poster_px.isNull():
                self._poster_card.clear()
            else:
                self._poster_card.setPixmap(poster_px)
            self._last_poster_cache_key = poster_key

    def _sync_rotation_timer(self) -> None:
        should_run = len(self._items) > 1 and self.isVisible()
        if should_run:
            if not self._timer.isActive():
                self._timer.start()
            return
        self._timer.stop()

    def _emit_play(self) -> None:
        if not self._items:
            return
        self.playRequested.emit(str(self._items[self._index].content_key))

    def _emit_info(self) -> None:
        if not self._items:
            return
        self.infoRequested.emit(str(self._items[self._index].content_key))
