from __future__ import annotations

from typing import Callable, Dict, Optional, Sequence, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from omega.shuffle.intake import (
    ENDING_OPTIONS,
    ENERGY_OPTIONS,
    ENTRY_MODES,
    FAMILIARITY_OPTIONS,
    FOCUS_OPTIONS,
    INTENSITY_OPTIONS,
    NIGHT_KIND_OPTIONS,
    PACE_OPTIONS,
    TIME_OPTIONS,
    VARIETY_OPTIONS,
    advanced_toggle_rows,
    default_intake,
    intake_label,
)
from omega.shuffle.models import SmartShuffleIntake, SmartShufflePlan, SmartShuffleResult


class _OptionSelector(QGroupBox):
    def __init__(self, title: str, attr_name: str, options: Sequence[Tuple[str, str]], columns: int = 3, parent: Optional[QWidget] = None) -> None:
        super().__init__(title, parent)
        self.attr_name = str(attr_name)
        self._buttons: Dict[str, QPushButton] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        layout = QGridLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(10)

        for index, (value, label) in enumerate(options):
            btn = QPushButton(str(label), self)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setProperty("smartOption", True)
            btn.setMinimumHeight(38)
            self._group.addButton(btn)
            self._buttons[str(value)] = btn
            row = int(index // max(1, columns))
            col = int(index % max(1, columns))
            layout.addWidget(btn, row, col)

    def value(self) -> str:
        for key, btn in self._buttons.items():
            if btn.isChecked():
                return key
        return next(iter(self._buttons.keys()), "")

    def set_value(self, value: str) -> None:
        key = str(value or "")
        btn = self._buttons.get(key)
        if btn is None and self._buttons:
            btn = next(iter(self._buttons.values()))
        if btn is not None:
            btn.setChecked(True)


class SmartShuffleDialog(QDialog):
    def __init__(
        self,
        *,
        plan_builder: Callable[[SmartShuffleIntake], SmartShuffleResult],
        initial_mode: str = "smart_shuffle",
        selected_titles: Sequence[str] = (),
        library_count: int = 0,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._plan_builder = plan_builder
        self._selected_result: Optional[SmartShuffleResult] = None
        self._intake = default_intake(initial_mode)
        self._selectors: Dict[str, _OptionSelector] = {}
        self._advanced_toggles: Dict[str, QCheckBox] = {}
        self._selected_titles = tuple(str(x) for x in (selected_titles or ()) if str(x).strip())
        self._library_count = int(max(0, library_count))

        self.setWindowTitle("Omega Smart Shuffle")
        self.setMinimumSize(1120, 760)
        self.setModal(True)
        self._apply_style()

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        header = QFrame(self)
        header.setObjectName("smartHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(18, 18, 18, 18)
        header_layout.setSpacing(12)

        header_text = QVBoxLayout()
        title = QLabel("Smart Shuffle", header)
        title.setObjectName("smartTitle")
        subtitle = QLabel(self._header_subtitle(), header)
        subtitle.setObjectName("smartSubtitle")
        header_text.addWidget(title)
        header_text.addWidget(subtitle)
        header_layout.addLayout(header_text, 1)

        self._confidence_chip = QLabel("", header)
        self._confidence_chip.setObjectName("confidenceChip")
        self._confidence_chip.hide()
        header_layout.addWidget(self._confidence_chip, 0, Qt.AlignRight | Qt.AlignTop)
        root.addWidget(header)

        self._pages = QStackedWidget(self)
        root.addWidget(self._pages, 1)

        self._entry_page = self._build_entry_page()
        self._intake_page = self._build_intake_page()
        self._preview_page = self._build_preview_page()
        self._pages.addWidget(self._entry_page)
        self._pages.addWidget(self._intake_page)
        self._pages.addWidget(self._preview_page)
        self._pages.setCurrentWidget(self._entry_page)

    def selected_result(self) -> Optional[SmartShuffleResult]:
        return self._selected_result

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QDialog {
                background: #071118;
                color: #f2f6fa;
            }
            QFrame#smartHeader {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #0e1f2b, stop:1 #132a24);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 20px;
            }
            QLabel#smartTitle {
                font-size: 30px;
                font-weight: 700;
                color: #f8fbff;
            }
            QLabel#smartSubtitle {
                color: rgba(235,243,251,0.82);
                font-size: 14px;
            }
            QLabel#confidenceChip {
                background: rgba(255,255,255,0.10);
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 16px;
                padding: 8px 12px;
                color: #f6f9fc;
                font-weight: 600;
            }
            QGroupBox {
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 18px;
                margin-top: 14px;
                font-weight: 700;
                color: #ebf2f8;
                background: rgba(255,255,255,0.03);
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }
            QPushButton[smartOption="true"] {
                background: rgba(255,255,255,0.05);
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 14px;
                padding: 10px 14px;
                color: #f2f6fa;
                font-weight: 600;
                text-align: center;
            }
            QPushButton[smartOption="true"]:checked {
                background: rgba(116,212,173,0.18);
                border: 1px solid rgba(116,212,173,0.48);
            }
            QPushButton[smartModeCard="true"] {
                background: rgba(255,255,255,0.04);
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 20px;
                padding: 20px;
                color: #f2f6fa;
                text-align: left;
            }
            QPushButton[smartModeCard="true"]:hover {
                background: rgba(255,255,255,0.08);
            }
            QPushButton[primary="true"] {
                background: #7ad0ae;
                border: none;
                border-radius: 16px;
                padding: 12px 18px;
                color: #061017;
                font-weight: 700;
            }
            QPushButton[secondary="true"] {
                background: rgba(255,255,255,0.06);
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 16px;
                padding: 12px 18px;
                color: #eef5fb;
                font-weight: 600;
            }
            QCheckBox {
                spacing: 10px;
                color: #e5eef7;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 5px;
                border: 1px solid rgba(255,255,255,0.18);
                background: rgba(255,255,255,0.04);
            }
            QCheckBox::indicator:checked {
                background: #7ad0ae;
                border-color: #7ad0ae;
            }
            QFrame#segmentCard {
                background: rgba(255,255,255,0.04);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 18px;
            }
            QLabel#segmentRole {
                color: #7ad0ae;
                font-weight: 700;
                letter-spacing: 0.5px;
            }
            QLabel#segmentTitle {
                color: #f8fbff;
                font-size: 16px;
                font-weight: 700;
            }
            QLabel#mutedLabel {
                color: rgba(233,241,248,0.76);
            }
            QLabel#badgeLabel {
                background: rgba(255,255,255,0.08);
                border-radius: 10px;
                padding: 4px 8px;
                color: #f5f8fb;
            }
            """
        )

    def _header_subtitle(self) -> str:
        if self._selected_titles:
            return f"{len(self._selected_titles)} selected titles are weighted up, but the engine can still pull from your verified library for a better full session."
        return f"Build a premium watch session from {self._library_count} verified library items without the browsing fatigue."

    def _build_entry_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        intro = QLabel("Choose how much control you want tonight.", page)
        intro.setObjectName("mutedLabel")
        layout.addWidget(intro)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)
        layout.addLayout(grid)

        for index, (mode_key, label, desc) in enumerate(ENTRY_MODES):
            btn = QPushButton(f"{label}\n\n{desc}", page)
            btn.setProperty("smartModeCard", True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(138)
            btn.clicked.connect(lambda _=False, mk=str(mode_key): self._on_mode_selected(mk))
            grid.addWidget(btn, int(index // 2), int(index % 2))

        layout.addStretch(1)
        return page

    def _build_intake_page(self) -> QWidget:
        page = QWidget(self)
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        scroller = QScrollArea(page)
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QFrame.NoFrame)
        content = QWidget(scroller)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 10, 0)
        content_layout.setSpacing(14)

        selectors = [
            ("Current energy", "current_energy", ENERGY_OPTIONS, 5),
            ("What kind of night is this?", "night_kind", NIGHT_KIND_OPTIONS, 4),
            ("Focus availability", "focus_availability", FOCUS_OPTIONS, 4),
            ("Available time", "available_time", TIME_OPTIONS, 5),
            ("Familiarity preference", "familiarity_preference", FAMILIARITY_OPTIONS, 5),
            ("Variety preference", "variety_preference", VARIETY_OPTIONS, 5),
            ("Emotional intensity", "emotional_intensity", INTENSITY_OPTIONS, 5),
            ("Tonight's pace", "tonight_pace", PACE_OPTIONS, 5),
            ("End-of-night preference", "end_preference", ENDING_OPTIONS, 5),
        ]
        for title, attr, options, columns in selectors:
            selector = _OptionSelector(title, attr, options, columns=columns, parent=content)
            self._selectors[str(attr)] = selector
            content_layout.addWidget(selector)

        advanced = QGroupBox("Advanced levers", content)
        advanced_layout = QGridLayout(advanced)
        advanced_layout.setContentsMargins(12, 12, 12, 12)
        advanced_layout.setHorizontalSpacing(16)
        advanced_layout.setVerticalSpacing(10)
        for index, (attr, label) in enumerate(advanced_toggle_rows()):
            chk = QCheckBox(str(label), advanced)
            self._advanced_toggles[str(attr)] = chk
            advanced_layout.addWidget(chk, int(index // 2), int(index % 2))
        content_layout.addWidget(advanced)
        content_layout.addStretch(1)

        scroller.setWidget(content)
        outer.addWidget(scroller, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        back_btn = QPushButton("Back", page)
        back_btn.setProperty("secondary", True)
        back_btn.clicked.connect(lambda: self._pages.setCurrentWidget(self._entry_page))
        preview_btn = QPushButton("Preview Session", page)
        preview_btn.setProperty("primary", True)
        preview_btn.clicked.connect(self._generate_preview)
        buttons.addWidget(back_btn)
        buttons.addWidget(preview_btn)
        outer.addLayout(buttons)
        return page

    def _build_preview_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        top = QFrame(page)
        top.setObjectName("segmentCard")
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(18, 18, 18, 18)
        top_layout.setSpacing(6)
        self._preview_session_name = QLabel("", top)
        self._preview_session_name.setObjectName("smartTitle")
        self._preview_tone = QLabel("", top)
        self._preview_tone.setObjectName("segmentRole")
        self._preview_summary = QLabel("", top)
        self._preview_summary.setWordWrap(True)
        self._preview_summary.setObjectName("mutedLabel")
        self._preview_meta = QLabel("", top)
        self._preview_meta.setObjectName("mutedLabel")
        top_layout.addWidget(self._preview_session_name)
        top_layout.addWidget(self._preview_tone)
        top_layout.addWidget(self._preview_summary)
        top_layout.addWidget(self._preview_meta)
        layout.addWidget(top)

        self._preview_segments_scroll = QScrollArea(page)
        self._preview_segments_scroll.setWidgetResizable(True)
        self._preview_segments_scroll.setFrameShape(QFrame.NoFrame)
        self._preview_segments_root = QWidget(self._preview_segments_scroll)
        self._preview_segments_layout = QVBoxLayout(self._preview_segments_root)
        self._preview_segments_layout.setContentsMargins(0, 0, 8, 0)
        self._preview_segments_layout.setSpacing(12)
        self._preview_segments_scroll.setWidget(self._preview_segments_root)
        layout.addWidget(self._preview_segments_scroll, 1)

        self._preview_explanations = QLabel("", page)
        self._preview_explanations.setWordWrap(True)
        self._preview_explanations.setObjectName("mutedLabel")
        layout.addWidget(self._preview_explanations)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        adjust_btn = QPushButton("Adjust Intake", page)
        adjust_btn.setProperty("secondary", True)
        adjust_btn.clicked.connect(lambda: self._pages.setCurrentWidget(self._intake_page))
        regen_btn = QPushButton("Regenerate", page)
        regen_btn.setProperty("secondary", True)
        regen_btn.clicked.connect(self._generate_preview)
        start_btn = QPushButton("Start Session", page)
        start_btn.setProperty("primary", True)
        start_btn.clicked.connect(self.accept)
        buttons.addWidget(adjust_btn)
        buttons.addWidget(regen_btn)
        buttons.addWidget(start_btn)
        layout.addLayout(buttons)
        return page

    def _on_mode_selected(self, mode: str) -> None:
        self._intake = default_intake(mode)
        self._sync_intake_to_inputs()
        if mode in {"trust_me", "continue_momentum", "surprise"}:
            self._generate_preview()
            return
        self._pages.setCurrentWidget(self._intake_page)

    def _sync_intake_to_inputs(self) -> None:
        for attr, selector in self._selectors.items():
            selector.set_value(str(getattr(self._intake, attr, "") or ""))
        for attr, chk in self._advanced_toggles.items():
            chk.setChecked(bool(getattr(self._intake, attr, False)))

    def _collect_intake(self) -> SmartShuffleIntake:
        values = dict(self._intake.__dict__)
        for attr, selector in self._selectors.items():
            values[str(attr)] = selector.value()
        for attr, chk in self._advanced_toggles.items():
            values[str(attr)] = bool(chk.isChecked())
        return SmartShuffleIntake(**values)

    def _generate_preview(self) -> None:
        intake = self._collect_intake()
        try:
            result = self._plan_builder(intake)
        except Exception as exc:
            QMessageBox.warning(self, "Smart Shuffle", str(exc) or "Could not build a Smart Shuffle session.")
            return
        self._selected_result = result
        self._intake = intake
        self._render_preview(result.plan)
        self._pages.setCurrentWidget(self._preview_page)

    def _render_preview(self, plan: SmartShufflePlan) -> None:
        self._preview_session_name.setText(str(plan.session_name))
        self._preview_tone.setText(str(plan.tone_banner))
        self._preview_summary.setText(str(plan.summary))
        meta_bits = [
            str(plan.mode_label),
            f"{int(plan.estimated_runtime_minutes)} min",
            "Protected arcs on" if plan.protected_arc_active else "Flexible session",
            str(plan.confidence_label),
        ]
        self._preview_meta.setText("  •  ".join(meta_bits))
        self._preview_explanations.setText("\n".join(f"• {line}" for line in plan.explanation_lines))
        self._confidence_chip.setText(f"{plan.confidence_label}  {int(plan.confidence_score * 100)}%")
        self._confidence_chip.show()

        while self._preview_segments_layout.count():
            item = self._preview_segments_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        for idx, seg in enumerate(plan.segments, start=1):
            self._preview_segments_layout.addWidget(self._make_segment_card(seg, idx, len(plan.segments)))
        self._preview_segments_layout.addStretch(1)

    def _make_segment_card(self, seg: SmartShuffleSegment, index: int, total: int) -> QWidget:
        card = QFrame(self._preview_segments_root)
        card.setObjectName("segmentCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        role = QLabel(f"{index}/{total}  {seg.role.replace('_', ' ').title()}", card)
        role.setObjectName("segmentRole")
        title = QLabel(str(seg.title), card)
        title.setObjectName("segmentTitle")
        meta = QLabel(f"{int(seg.runtime_minutes)} min  •  {'Protected run' if seg.protected_run else 'Flexible'}  •  {int(seg.confidence * 100)}% match", card)
        meta.setObjectName("mutedLabel")
        explanation = QLabel(str(seg.explanation), card)
        explanation.setWordWrap(True)
        explanation.setObjectName("mutedLabel")

        badges = QHBoxLayout()
        badges.setSpacing(8)
        for badge in seg.badges:
            chip = QLabel(str(badge), card)
            chip.setObjectName("badgeLabel")
            badges.addWidget(chip)
        badges.addStretch(1)

        layout.addWidget(role)
        layout.addWidget(title)
        layout.addWidget(meta)
        layout.addLayout(badges)
        layout.addWidget(explanation)
        return card


class SmartShuffleNowPlayingStrip(QFrame):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("smartShuffleNowPlayingStrip")
        self.setVisible(False)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.buttons: Dict[str, QPushButton] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        top = QHBoxLayout()
        text = QVBoxLayout()
        self.eyebrow = QLabel("Smart Shuffle active", self)
        self.eyebrow.setObjectName("stripEyebrow")
        self.title_label = QLabel("", self)
        self.title_label.setObjectName("stripTitle")
        self.meta_label = QLabel("", self)
        self.meta_label.setObjectName("stripMuted")
        text.addWidget(self.eyebrow)
        text.addWidget(self.title_label)
        text.addWidget(self.meta_label)
        top.addLayout(text, 1)

        self.arc_label = QLabel("", self)
        self.arc_label.setObjectName("stripMuted")
        top.addWidget(self.arc_label, 0, Qt.AlignRight | Qt.AlignTop)
        root.addLayout(top)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        for key, label in [
            ("stay_on_show", "Stay On This Show"),
            ("switch_sooner", "Switch Sooner"),
            ("soft_landing", "Soft Landing"),
            ("more_familiar", "More Familiar"),
            ("more_adventurous", "More Adventurous"),
        ]:
            btn = QPushButton(str(label), self)
            btn.setObjectName("stripButton")
            btn.setCursor(Qt.PointingHandCursor)
            self.buttons[str(key)] = btn
            actions.addWidget(btn)
        actions.addStretch(1)
        root.addLayout(actions)
        self.apply_palette()

    def apply_palette(
        self,
        *,
        primary_hex: str = "#5CA0FF",
        secondary_hex: str = "#4FD4B3",
        text_hex: str = "#F5F8FB",
        muted_hex: str = "#B8C0D4",
        border_hex: str = "#2A3449",
        surface_hex: str = "#141A29",
    ) -> None:
        primary = QColor(str(primary_hex or "#5CA0FF"))
        if not primary.isValid():
            primary = QColor("#5CA0FF")
        secondary = QColor(str(secondary_hex or "#4FD4B3"))
        if not secondary.isValid():
            secondary = QColor("#4FD4B3")
        self.setStyleSheet(
            f"""
            QFrame#smartShuffleNowPlayingStrip {{
                background: rgba(10, 16, 24, 232);
                border: 1px solid {border_hex};
                border-radius: 18px;
            }}
            QLabel#stripEyebrow {{
                color: rgba({secondary.red()}, {secondary.green()}, {secondary.blue()}, 224);
                font-weight: 800;
                letter-spacing: 1px;
            }}
            QLabel#stripTitle {{
                color: {text_hex};
                font-size: 16px;
                font-weight: 800;
            }}
            QLabel#stripMuted {{
                color: {muted_hex};
            }}
            QPushButton#stripButton {{
                background: rgba({primary.red()}, {primary.green()}, {primary.blue()}, 38);
                border: 1px solid rgba({primary.red()}, {primary.green()}, {primary.blue()}, 128);
                border-radius: 12px;
                padding: 8px 12px;
                color: {text_hex};
                font-weight: 700;
            }}
            QPushButton#stripButton:hover {{
                background: rgba({primary.red()}, {primary.green()}, {primary.blue()}, 54);
            }}
            """
        )

    def set_plan(self, plan: SmartShufflePlan, current_index: int, current_title: str = "") -> None:
        idx = int(max(0, current_index)) + 1
        total = max(1, len(plan.segments))
        self.title_label.setText(str(current_title or plan.session_name))
        self.meta_label.setText(f"{idx}/{total}  •  {plan.mode_label}  •  {plan.estimated_runtime_minutes} min planned")
        self.arc_label.setText("Protected arc active" if plan.protected_arc_active else "Flexible session")
        self.setVisible(True)



