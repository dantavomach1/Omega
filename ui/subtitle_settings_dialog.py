from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QDialog,
    QDoubleSpinBox,
    QFontComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


class SubtitleSettingsDialog(QDialog):
    def __init__(
        self,
        settings: Dict[str, Any],
        *,
        defaults: Dict[str, Any],
        parent: Optional[QWidget] = None,
        on_apply: Optional[Callable[[Dict[str, Any]], None]] = None,
        theme: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Subtitle Studio")
        self.setMinimumSize(860, 700)

        self._defaults = dict(defaults or {})
        self._on_apply = on_apply
        self._color_values: Dict[str, str] = {}
        self._color_buttons: Dict[str, QPushButton] = {}
        self._theme = dict(theme or {})

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        hero = QFrame(self)
        hero.setObjectName("subtitleStudioHero")
        hero_l = QVBoxLayout(hero)
        hero_l.setContentsMargins(20, 18, 20, 18)
        hero_l.setSpacing(6)
        eyebrow = QLabel("OMEGA SUBTITLE STUDIO", hero)
        eyebrow.setObjectName("subtitleStudioEyebrow")
        title = QLabel("Tune readability like a finishing pass.", hero)
        title.setObjectName("subtitleStudioTitle")
        subtitle = QLabel(
            "Shape font, contrast, outline, and placement with a live preview. Apply changes instantly while something is playing or save them as your default house style.",
            hero,
        )
        subtitle.setObjectName("subtitleStudioSubtitle")
        subtitle.setWordWrap(True)
        hero_l.addWidget(eyebrow)
        hero_l.addWidget(title)
        hero_l.addWidget(subtitle)
        root.addWidget(hero)

        tabs = QTabWidget(self)
        tabs.setObjectName("subtitleStudioTabs")
        root.addWidget(tabs, 1)

        appearance_tab = QWidget(tabs)
        behavior_tab = QWidget(tabs)
        tabs.addTab(appearance_tab, "Appearance")
        tabs.addTab(behavior_tab, "Behavior")

        appearance_layout = QVBoxLayout(appearance_tab)
        appearance_layout.setContentsMargins(0, 0, 0, 0)
        appearance_layout.setSpacing(14)

        preview_frame = QFrame(appearance_tab)
        preview_frame.setObjectName("subtitlePreviewFrame")
        preview_layout = QVBoxLayout(preview_frame)
        preview_layout.setContentsMargins(22, 20, 22, 20)
        preview_layout.setSpacing(10)
        preview_eyebrow = QLabel("LIVE PREVIEW", preview_frame)
        preview_eyebrow.setObjectName("subtitleStudioEyebrow")
        preview_layout.addWidget(preview_eyebrow, 0, Qt.AlignLeft)

        self._preview_top_spacer = QFrame(preview_frame)
        self._preview_bottom_spacer = QFrame(preview_frame)
        self._preview_top_spacer.setStyleSheet("background: transparent;")
        self._preview_bottom_spacer.setStyleSheet("background: transparent;")
        self._preview_top_spacer.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self._preview_bottom_spacer.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self._preview_label = QLabel(
            "Omega subtitle preview\nThe future belongs to deeply readable screens.",
            preview_frame,
        )
        self._preview_label.setObjectName("subtitlePreviewLabel")
        self._preview_label.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self._preview_label.setWordWrap(True)
        self._preview_label.setMinimumHeight(110)
        preview_layout.addWidget(self._preview_top_spacer, 1)
        preview_layout.addWidget(self._preview_label, 0, Qt.AlignHCenter)
        preview_layout.addWidget(self._preview_bottom_spacer, 1)
        appearance_layout.addWidget(preview_frame, 1)

        preset_card = QFrame(appearance_tab)
        preset_card.setObjectName("subtitleStudioCard")
        preset_l = QVBoxLayout(preset_card)
        preset_l.setContentsMargins(16, 16, 16, 16)
        preset_l.setSpacing(10)
        preset_title = QLabel("Quick Style Starts", preset_card)
        preset_title.setObjectName("subtitleCardTitle")
        preset_help = QLabel(
            "Start from a tuned baseline, then refine. These do not save automatically until you Apply or Save.",
            preset_card,
        )
        preset_help.setObjectName("subtitleCardBody")
        preset_help.setWordWrap(True)
        preset_l.addWidget(preset_title)
        preset_l.addWidget(preset_help)
        preset_row = QHBoxLayout()
        preset_row.setContentsMargins(0, 0, 0, 0)
        preset_row.setSpacing(8)
        for key, label in [
            ("cinema", "Cinema"),
            ("broadcast", "Broadcast"),
            ("minimal", "Minimal"),
            ("high_contrast", "High Contrast"),
        ]:
            btn = QPushButton(label, preset_card)
            btn.clicked.connect(lambda _=False, preset_key=key: self._apply_style_preset(preset_key))
            preset_row.addWidget(btn)
        preset_row.addStretch(1)
        preset_l.addLayout(preset_row)
        appearance_layout.addWidget(preset_card)

        appearance_card = QFrame(appearance_tab)
        appearance_card.setObjectName("subtitleStudioCard")
        appearance_card_l = QVBoxLayout(appearance_card)
        appearance_card_l.setContentsMargins(16, 16, 16, 16)
        appearance_card_l.setSpacing(10)
        appearance_card_title = QLabel("Typography and Materials", appearance_card)
        appearance_card_title.setObjectName("subtitleCardTitle")
        appearance_card_l.addWidget(appearance_card_title)

        appearance_form = QFormLayout()
        appearance_form.setContentsMargins(0, 0, 0, 0)
        appearance_form.setHorizontalSpacing(16)
        appearance_form.setVerticalSpacing(10)
        appearance_card_l.addLayout(appearance_form)

        self._font_combo = QFontComboBox(appearance_tab)
        appearance_form.addRow("Font", self._font_combo)

        size_row = QHBoxLayout()
        size_row.setContentsMargins(0, 0, 0, 0)
        size_row.setSpacing(8)
        self._font_size = QSpinBox(appearance_tab)
        self._font_size.setRange(10, 96)
        self._font_size.setSuffix(" pt")
        size_row.addWidget(self._font_size)
        self._font_scale = QSpinBox(appearance_tab)
        self._font_scale.setRange(50, 300)
        self._font_scale.setSuffix("% scale")
        size_row.addWidget(self._font_scale)
        appearance_form.addRow("Size", self._wrap_row(size_row, appearance_tab))

        style_row = QHBoxLayout()
        style_row.setContentsMargins(0, 0, 0, 0)
        style_row.setSpacing(8)
        self._bold = QCheckBox("Bold", appearance_tab)
        self._italic = QCheckBox("Italic", appearance_tab)
        style_row.addWidget(self._bold)
        style_row.addWidget(self._italic)
        style_row.addStretch(1)
        appearance_form.addRow("Style", self._wrap_row(style_row, appearance_tab))

        color_row = QHBoxLayout()
        color_row.setContentsMargins(0, 0, 0, 0)
        color_row.setSpacing(8)
        color_row.addWidget(self._build_color_button("text_color", "Text", appearance_tab))
        color_row.addWidget(self._build_color_button("background_color", "Background", appearance_tab))
        color_row.addWidget(self._build_color_button("border_color", "Outline", appearance_tab))
        color_row.addWidget(self._build_color_button("shadow_color", "Shadow", appearance_tab))
        appearance_form.addRow("Colors", self._wrap_row(color_row, appearance_tab))

        edge_row = QHBoxLayout()
        edge_row.setContentsMargins(0, 0, 0, 0)
        edge_row.setSpacing(8)
        self._border_size = QDoubleSpinBox(appearance_tab)
        self._border_size.setRange(0.0, 12.0)
        self._border_size.setDecimals(1)
        self._border_size.setSingleStep(0.5)
        self._border_size.setSuffix(" px")
        edge_row.addWidget(self._border_size)
        self._shadow_offset = QDoubleSpinBox(appearance_tab)
        self._shadow_offset.setRange(0.0, 12.0)
        self._shadow_offset.setDecimals(1)
        self._shadow_offset.setSingleStep(0.5)
        self._shadow_offset.setSuffix(" px")
        edge_row.addWidget(self._shadow_offset)
        appearance_form.addRow("Outline / Shadow", self._wrap_row(edge_row, appearance_tab))

        appearance_layout.addWidget(appearance_card)

        behavior_layout = QVBoxLayout(behavior_tab)
        behavior_layout.setContentsMargins(0, 0, 0, 0)
        behavior_layout.setSpacing(14)

        behavior_card = QFrame(behavior_tab)
        behavior_card.setObjectName("subtitleStudioCard")
        behavior_card_l = QVBoxLayout(behavior_card)
        behavior_card_l.setContentsMargins(16, 16, 16, 16)
        behavior_card_l.setSpacing(10)
        behavior_title = QLabel("Behavior Defaults", behavior_card)
        behavior_title.setObjectName("subtitleCardTitle")
        behavior_body = QLabel(
            "Choose how assertively Omega should show subtitles and how far the style studio should override embedded ASS or SSA tracks.",
            behavior_card,
        )
        behavior_body.setObjectName("subtitleCardBody")
        behavior_body.setWordWrap(True)
        behavior_card_l.addWidget(behavior_title)
        behavior_card_l.addWidget(behavior_body)

        behavior_form = QFormLayout()
        behavior_form.setContentsMargins(0, 0, 0, 0)
        behavior_form.setHorizontalSpacing(16)
        behavior_form.setVerticalSpacing(10)
        behavior_card_l.addLayout(behavior_form)

        self._enabled_on_load = QCheckBox("Automatically show subtitles when a track exists", behavior_tab)
        behavior_form.addRow("Default", self._enabled_on_load)

        self._force_override = QCheckBox("Force your chosen style over ASS / SSA styling", behavior_tab)
        behavior_form.addRow("Style Override", self._force_override)

        pos_row = QHBoxLayout()
        pos_row.setContentsMargins(0, 0, 0, 0)
        pos_row.setSpacing(8)
        self._position_slider = QSlider(Qt.Horizontal, behavior_tab)
        self._position_slider.setRange(0, 100)
        self._position_spin = QSpinBox(behavior_tab)
        self._position_spin.setRange(0, 100)
        self._position_spin.setSuffix("%")
        pos_row.addWidget(self._position_slider, 1)
        pos_row.addWidget(self._position_spin, 0)
        behavior_form.addRow("Vertical Position", self._wrap_row(pos_row, behavior_tab))

        self._margin_y = QSpinBox(behavior_tab)
        self._margin_y.setRange(0, 180)
        self._margin_y.setSuffix(" px")
        behavior_form.addRow("Bottom Margin", self._margin_y)

        help_text = QLabel(
            "Tip: a semi-transparent background plus a darker outline usually gives the best compromise between cinematic taste and scene-legibility.",
            behavior_tab,
        )
        help_text.setWordWrap(True)
        help_text.setObjectName("subtitleCardBody")
        behavior_card_l.addWidget(help_text)
        behavior_layout.addWidget(behavior_card)
        behavior_layout.addStretch(1)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(10)
        self._reset_btn = QPushButton("Reset Defaults", self)
        self._cancel_btn = QPushButton("Cancel", self)
        self._apply_btn = QPushButton("Apply Live", self)
        self._save_btn = QPushButton("Save", self)
        actions.addWidget(self._reset_btn)
        actions.addStretch(1)
        actions.addWidget(self._cancel_btn)
        actions.addWidget(self._apply_btn)
        actions.addWidget(self._save_btn)
        root.addLayout(actions)

        self._position_slider.valueChanged.connect(self._position_spin.setValue)
        self._position_spin.valueChanged.connect(self._position_slider.setValue)

        for widget in (
            self._font_combo,
            self._font_size,
            self._font_scale,
            self._bold,
            self._italic,
            self._border_size,
            self._shadow_offset,
            self._enabled_on_load,
            self._force_override,
            self._position_slider,
            self._position_spin,
            self._margin_y,
        ):
            self._connect_preview_signal(widget)

        self._reset_btn.clicked.connect(self._reset_defaults)
        self._cancel_btn.clicked.connect(self.reject)
        self._apply_btn.clicked.connect(self._apply_current_settings)
        self._save_btn.clicked.connect(self._save_and_close)

        self._apply_chrome()
        self._load_settings(settings or self._defaults)
        self._update_preview()

    def current_settings(self) -> Dict[str, Any]:
        return {
            "enabled_on_load": bool(self._enabled_on_load.isChecked()),
            "force_override": bool(self._force_override.isChecked()),
            "font_family": str(self._font_combo.currentFont().family() or self._defaults.get("font_family", "Arial")),
            "font_size": int(self._font_size.value()),
            "font_scale": int(self._font_scale.value()),
            "bold": bool(self._bold.isChecked()),
            "italic": bool(self._italic.isChecked()),
            "text_color": str(self._color_values.get("text_color", self._defaults.get("text_color", "#FFFFFFFF"))),
            "background_color": str(self._color_values.get("background_color", self._defaults.get("background_color", "#80000000"))),
            "border_color": str(self._color_values.get("border_color", self._defaults.get("border_color", "#FF000000"))),
            "shadow_color": str(self._color_values.get("shadow_color", self._defaults.get("shadow_color", "#B0000000"))),
            "border_size": float(self._border_size.value()),
            "shadow_offset": float(self._shadow_offset.value()),
            "position": int(self._position_spin.value()),
            "margin_y": int(self._margin_y.value()),
        }

    def _apply_chrome(self) -> None:
        primary = QColor(str(self._theme.get("primary", "#5CA0FF")))
        secondary = QColor(str(self._theme.get("secondary", "#4FD4B3")))
        text = str(self._theme.get("text", "#F4F7FF"))
        muted = str(self._theme.get("muted_text", "#B4C0D8"))
        surface = str(self._theme.get("surface_soft", self._theme.get("card", "#141A29")))
        surface_strong = str(self._theme.get("surface_strong", self._theme.get("background_alt", "#0F1320")))
        border = str(self._theme.get("border", "#2A3449"))

        if not primary.isValid():
            primary = QColor("#5CA0FF")
        if not secondary.isValid():
            secondary = QColor("#4FD4B3")

        self.setStyleSheet(
            f"""
            QDialog {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                    stop:0 rgba(5,8,14,252),
                    stop:0.52 rgba({primary.red()}, {primary.green()}, {primary.blue()}, 26),
                    stop:1 rgba(5,8,14,252));
                color: {text};
            }}
            QFrame#subtitleStudioHero,
            QFrame#subtitleStudioCard,
            QFrame#subtitlePreviewFrame {{
                background: {surface};
                border: 1px solid {border};
                border-radius: 22px;
            }}
            QFrame#subtitlePreviewFrame {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                    stop:0 rgba(8,12,18,252),
                    stop:0.45 rgba({primary.red()}, {primary.green()}, {primary.blue()}, 26),
                    stop:1 rgba({secondary.red()}, {secondary.green()}, {secondary.blue()}, 18));
            }}
            QLabel#subtitleStudioEyebrow {{
                color: rgba({secondary.red()}, {secondary.green()}, {secondary.blue()}, 228);
                font-size: 11px;
                font-weight: 800;
                letter-spacing: 1px;
                background: transparent;
            }}
            QLabel#subtitleStudioTitle {{
                color: {text};
                font-size: 28px;
                font-weight: 900;
                background: transparent;
            }}
            QLabel#subtitleStudioSubtitle,
            QLabel#subtitleCardBody {{
                color: {muted};
                font-size: 13px;
                background: transparent;
            }}
            QLabel#subtitleCardTitle {{
                color: {text};
                font-size: 16px;
                font-weight: 800;
                background: transparent;
            }}
            QLabel#subtitlePreviewLabel {{
                color: #FDFEFF;
                background: transparent;
            }}
            QTabWidget#subtitleStudioTabs::pane {{
                background: transparent;
                border: none;
                margin-top: 10px;
            }}
            QTabWidget#subtitleStudioTabs QTabBar::tab {{
                color: {text};
                background: {surface};
                border: 1px solid {border};
                border-radius: 14px;
                padding: 8px 14px;
                margin-right: 8px;
                font-weight: 700;
            }}
            QTabWidget#subtitleStudioTabs QTabBar::tab:selected {{
                background: rgba({primary.red()}, {primary.green()}, {primary.blue()}, 96);
                border: 1px solid rgba({primary.red()}, {primary.green()}, {primary.blue()}, 220);
                color: #FFFFFF;
            }}
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QFontComboBox {{
                background: {surface_strong};
                color: {text};
                border: 1px solid {border};
                border-radius: 12px;
                padding: 6px 8px;
            }}
            QCheckBox {{
                color: {text};
            }}
            QPushButton {{
                color: {text};
                background: {surface_strong};
                border: 1px solid {border};
                border-radius: 12px;
                padding: 8px 12px;
                font-weight: 700;
            }}
            QPushButton:hover {{
                background: rgba({primary.red()}, {primary.green()}, {primary.blue()}, 42);
                border: 1px solid rgba({primary.red()}, {primary.green()}, {primary.blue()}, 210);
            }}
            QSlider::groove:horizontal {{
                height: 6px;
                border-radius: 3px;
                background: rgba(255,255,255,32);
            }}
            QSlider::sub-page:horizontal {{
                background: rgba({primary.red()}, {primary.green()}, {primary.blue()}, 212);
                border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                width: 14px;
                margin: -6px 0;
                background: #FFFFFF;
                border-radius: 7px;
                border: 1px solid rgba(0,0,0,90);
            }}
            """
        )

    def _apply_style_preset(self, key: str) -> None:
        presets: Dict[str, Dict[str, Any]] = {
            "cinema": {
                "font_family": "Trebuchet MS",
                "font_size": 44,
                "font_scale": 100,
                "bold": True,
                "italic": False,
                "text_color": "#FFF7E8FF",
                "background_color": "#66000000",
                "border_color": "#CC000000",
                "shadow_color": "#A6000000",
                "border_size": 2.5,
                "shadow_offset": 1.5,
                "position": 91,
                "margin_y": 26,
            },
            "broadcast": {
                "font_family": "Arial",
                "font_size": 38,
                "font_scale": 100,
                "bold": True,
                "italic": False,
                "text_color": "#FFFFFFFF",
                "background_color": "#4D000000",
                "border_color": "#FF101010",
                "shadow_color": "#B0000000",
                "border_size": 3.0,
                "shadow_offset": 1.0,
                "position": 90,
                "margin_y": 24,
            },
            "minimal": {
                "font_family": "Arial",
                "font_size": 36,
                "font_scale": 95,
                "bold": False,
                "italic": False,
                "text_color": "#FFF8F8F8",
                "background_color": "#22000000",
                "border_color": "#33000000",
                "shadow_color": "#66000000",
                "border_size": 0.5,
                "shadow_offset": 0.5,
                "position": 92,
                "margin_y": 20,
            },
            "high_contrast": {
                "font_family": "Arial",
                "font_size": 46,
                "font_scale": 105,
                "bold": True,
                "italic": False,
                "text_color": "#FFFFFF00",
                "background_color": "#B0000000",
                "border_color": "#FF000000",
                "shadow_color": "#FF000000",
                "border_size": 4.0,
                "shadow_offset": 2.0,
                "position": 88,
                "margin_y": 30,
            },
        }
        payload = presets.get(str(key), {})
        if not payload:
            return
        self._load_settings(payload)
        self._update_preview()

    def _wrap_row(self, layout: QHBoxLayout, parent: QWidget) -> QWidget:
        host = QWidget(parent)
        host.setLayout(layout)
        return host

    def _build_color_button(self, key: str, label: str, parent: QWidget) -> QPushButton:
        btn = QPushButton(label, parent)
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda _=False, color_key=key: self._pick_color(color_key))
        self._color_buttons[key] = btn
        return btn

    def _connect_preview_signal(self, widget: QWidget) -> None:
        if isinstance(widget, QFontComboBox):
            widget.currentFontChanged.connect(lambda _font: self._update_preview())
        elif isinstance(widget, (QSpinBox, QDoubleSpinBox, QSlider)):
            widget.valueChanged.connect(lambda _value: self._update_preview())
        elif isinstance(widget, QCheckBox):
            widget.toggled.connect(lambda _checked: self._update_preview())

    def _load_settings(self, settings: Dict[str, Any]) -> None:
        merged = dict(self._defaults)
        merged.update(dict(settings or {}))

        font = QFont(str(merged.get("font_family", "Arial") or "Arial"))
        self._font_combo.setCurrentFont(font)
        self._font_size.setValue(int(merged.get("font_size", 42) or 42))
        self._font_scale.setValue(int(merged.get("font_scale", 100) or 100))
        self._bold.setChecked(bool(merged.get("bold", False)))
        self._italic.setChecked(bool(merged.get("italic", False)))
        self._enabled_on_load.setChecked(bool(merged.get("enabled_on_load", True)))
        self._force_override.setChecked(bool(merged.get("force_override", True)))
        self._border_size.setValue(float(merged.get("border_size", 3.0) or 3.0))
        self._shadow_offset.setValue(float(merged.get("shadow_offset", 1.5) or 1.5))
        self._position_spin.setValue(int(merged.get("position", 92) or 92))
        self._margin_y.setValue(int(merged.get("margin_y", 24) or 24))

        for key in ("text_color", "background_color", "border_color", "shadow_color"):
            self._color_values[key] = self._normalize_color(str(merged.get(key, self._defaults.get(key, "#FFFFFFFF"))))
            self._refresh_color_button(key)

    def _normalize_color(self, value: str) -> str:
        color = QColor(str(value or "").strip())
        if not color.isValid():
            color = QColor("#FFFFFFFF")
        return color.name(QColor.HexArgb).upper()

    def _refresh_color_button(self, key: str) -> None:
        btn = self._color_buttons.get(key)
        if btn is None:
            return
        color = QColor(self._color_values.get(key, "#FFFFFFFF"))
        fg = "#091017" if color.lightnessF() >= 0.62 else "#F7FAFF"
        btn.setText(color.name(QColor.HexArgb).upper())
        btn.setStyleSheet(
            f"background: {color.name(QColor.HexArgb)};"
            f"color: {fg};"
            "border: 1px solid rgba(255,255,255,0.18);"
            "border-radius: 13px;"
            "padding: 8px 12px;"
            "font-weight: 700;"
        )

    def _pick_color(self, key: str) -> None:
        current = QColor(self._color_values.get(key, "#FFFFFFFF"))
        chosen = QColorDialog.getColor(current, self, "Choose subtitle color", QColorDialog.ShowAlphaChannel)
        if not chosen.isValid():
            return
        self._color_values[key] = chosen.name(QColor.HexArgb).upper()
        self._refresh_color_button(key)
        self._update_preview()

    def _preview_css_color(self, value: str) -> str:
        color = QColor(str(value or "#FFFFFFFF"))
        if not color.isValid():
            color = QColor("#FFFFFFFF")
        return f"rgba({color.red()}, {color.green()}, {color.blue()}, {color.alphaF():.3f})"

    def _update_preview(self) -> None:
        settings = self.current_settings()
        preview_font = QFont(str(settings.get("font_family", "Arial") or "Arial"))
        preview_font.setPointSize(int(settings.get("font_size", 42) or 42))
        preview_font.setBold(bool(settings.get("bold", False)))
        preview_font.setItalic(bool(settings.get("italic", False)))
        self._preview_label.setFont(preview_font)

        border_size = float(settings.get("border_size", 3.0) or 0.0)
        shadow_offset = float(settings.get("shadow_offset", 1.5) or 0.0)
        scale = max(0.5, float(settings.get("font_scale", 100) or 100) / 100.0)
        self._preview_label.setStyleSheet(
            "padding: 10px 18px;"
            "border-radius: 12px;"
            f"color: {self._preview_css_color(str(settings.get('text_color', '#FFFFFFFF')))};"
            f"background: {self._preview_css_color(str(settings.get('background_color', '#80000000')))};"
            f"border: {border_size:.1f}px solid {self._preview_css_color(str(settings.get('border_color', '#FF000000')))};"
        )
        self._preview_label.setMinimumWidth(int(320 * scale))
        self._preview_label.setMaximumWidth(int(640 * scale))

        top_weight = max(0, int(settings.get("position", 92) or 0))
        bottom_weight = max(0, 100 - top_weight)
        preview_layout = self._preview_label.parentWidget().layout() if self._preview_label.parentWidget() is not None else None
        if preview_layout is not None:
            preview_layout.setStretch(1, max(1, top_weight))
            preview_layout.setStretch(3, max(1, bottom_weight))
        self._preview_label.setContentsMargins(20, 14, 20, max(12, int(settings.get("margin_y", 24) or 24)))
        self._preview_label.setToolTip(
            f"Outline {border_size:.1f}px, shadow {shadow_offset:.1f}px, position {top_weight}%"
        )

    def _reset_defaults(self) -> None:
        self._load_settings(self._defaults)
        self._update_preview()

    def _apply_current_settings(self) -> None:
        if callable(self._on_apply):
            self._on_apply(self.current_settings())

    def _save_and_close(self) -> None:
        self._apply_current_settings()
        self.accept()
