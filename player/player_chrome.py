from __future__ import annotations

from typing import Any, Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QGraphicsDropShadowEffect,
    QLabel,
    QPushButton,
    QSlider,
    QWidget,
)

CONTROLS_BAR_HEIGHT = 51


def _rgba(value: str, alpha: int) -> str:
    color = QColor(str(value or "").strip())
    if not color.isValid():
        color = QColor("#000000")
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {max(0, min(255, int(alpha)))})"


def build_controls_stylesheet(container_name: str, palette: Optional[Dict[str, Any]] = None) -> str:
    cfg = dict(palette or {})
    bar_top = str(cfg.get("bar_top", "#1A1E28") or "#1A1E28")
    bar_bottom = str(cfg.get("bar_bottom", "#0A0D14") or "#0A0D14")
    panel = str(cfg.get("panel", "#0B1118") or "#0B1118")
    panel_alt = str(cfg.get("panel_alt", "#121A24") or "#121A24")
    text = str(cfg.get("text", "#F4F7FF") or "#F4F7FF")
    muted = str(cfg.get("muted_text", "#B4C0D8") or "#B4C0D8")
    border = str(cfg.get("border", "#2A3449") or "#2A3449")
    primary = str(cfg.get("primary", "#5CA0FF") or "#5CA0FF")
    accent = str(cfg.get("accent", "#4FD4B3") or "#4FD4B3")
    danger = str(cfg.get("danger", "#E46666") or "#E46666")
    surface_alpha = int(cfg.get("surface_alpha", 236) or 236)
    panel_alpha = int(cfg.get("panel_alpha", 228) or 228)
    button_alpha = int(cfg.get("button_alpha", 20) or 20)
    radius = int(cfg.get("radius", 14) or 14)
    button_fill = _rgba(panel, max(28, min(255, button_alpha + 116)))
    button_hover = _rgba(panel_alt, max(48, min(255, button_alpha + 136)))
    ghost_fill = _rgba(panel_alt, max(40, min(255, button_alpha + 100)))
    combo_fill = _rgba(panel_alt, max(44, min(255, panel_alpha)))
    list_fill = _rgba(panel, max(56, min(255, panel_alpha)))
    return f"""
    QWidget#{container_name} {{
        background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                                    stop:0 {_rgba(bar_top, surface_alpha)},
                                    stop:1 {_rgba(bar_bottom, surface_alpha)});
        border-top: 1px solid {border};
    }}

    QWidget#{container_name} QPushButton {{
        color: {text};
        background: {button_fill};
        border: 1px solid {border};
        border-radius: {max(8, radius - 5)}px;
        padding: 3px 9px;
        font-size: 11px;
        font-weight: 600;
    }}

    QWidget#{container_name} QPushButton:hover {{
        background: {button_hover};
        border: 1px solid {primary};
    }}

    QWidget#{container_name} QPushButton:pressed {{
        background: {_rgba(panel, max(48, min(255, button_alpha + 88)))};
    }}

    QWidget#{container_name} QPushButton[chromeRole="primary"] {{
        background: {_rgba(primary, max(170, min(255, button_alpha + 140)))};
        border: 1px solid {primary};
        color: {text};
        font-weight: 700;
    }}

    QWidget#{container_name} QPushButton[chromeRole="primary"]:hover {{
        background: {_rgba(primary, 255)};
    }}

    QWidget#{container_name} QPushButton[chromeRole="accent"] {{
        background: {_rgba(accent, max(166, min(255, button_alpha + 138)))};
        border: 1px solid {accent};
    }}

    QWidget#{container_name} QPushButton[chromeRole="danger"] {{
        background: {_rgba(danger, max(170, min(255, button_alpha + 138)))};
        border: 1px solid {danger};
    }}

    QWidget#{container_name} QPushButton[chromeRole="ghost"] {{
        background: {ghost_fill};
        border: 1px solid {border};
        color: {text};
    }}

    QWidget#{container_name} QLabel[chromeRole="time"] {{
        color: {text};
        font-family: Consolas, 'Courier New', monospace;
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.4px;
        padding: 0px 4px;
    }}

    QWidget#{container_name} QLabel[chromeRole="muted"] {{
        color: {muted};
        font-size: 11px;
        padding-right: 4px;
    }}

    QWidget#{container_name} QSlider[chromeRole="seek"]::groove:horizontal {{
        height: 4px;
        background: {_rgba(panel_alt, max(60, min(255, panel_alpha - 46)))};
        border-radius: 2px;
    }}

    QWidget#{container_name} QSlider[chromeRole="seek"]::sub-page:horizontal {{
        background: {primary};
        border-radius: 2px;
    }}

    QWidget#{container_name} QSlider[chromeRole="seek"]::handle:horizontal {{
        width: 12px;
        margin: -6px 0;
        background: {text};
        border-radius: 5px;
        border: 1px solid {border};
    }}

    QWidget#{container_name} QSlider[chromeRole="volume"]::groove:horizontal {{
        height: 4px;
        background: {_rgba(panel_alt, max(60, min(255, panel_alpha - 46)))};
        border-radius: 2px;
    }}

    QWidget#{container_name} QSlider[chromeRole="volume"]::sub-page:horizontal {{
        background: {accent};
        border-radius: 2px;
    }}

    QWidget#{container_name} QSlider[chromeRole="volume"]::handle:horizontal {{
        width: 10px;
        margin: -6px 0;
        background: {text};
        border-radius: 5px;
        border: 1px solid {border};
    }}

    QWidget#{container_name} QComboBox[chromeRole="combo"] {{
        color: {text};
        background: {combo_fill};
        border: 1px solid {border};
        border-radius: {max(8, radius - 5)}px;
        padding: 4px 8px;
    }}

    QWidget#{container_name} QComboBox[chromeRole="combo"]:hover {{
        border: 1px solid {primary};
    }}

    QWidget#{container_name} QComboBox[chromeRole="combo"]::drop-down {{
        border: none;
        width: 24px;
    }}

    QWidget#{container_name} QComboBox[chromeRole="combo"]::down-arrow {{
        image: none;
        width: 0px;
        height: 0px;
    }}

    QWidget#{container_name} QComboBox QAbstractItemView {{
        background: {list_fill};
        color: {text};
        border: 1px solid {border};
        selection-background-color: {primary};
        selection-color: {text};
    }}
    """


def _polish(widget: QWidget) -> None:
    try:
        st = widget.style()
        if st is not None:
            st.unpolish(widget)
            st.polish(widget)
        widget.update()
    except Exception:
        pass


def apply_controls_container_chrome(container: Optional[QWidget], container_name: str, palette: Optional[Dict[str, Any]] = None) -> None:
    if container is None:
        return
    container.setObjectName(container_name)
    container.setAttribute(Qt.WA_StyledBackground, True)
    container.setStyleSheet(build_controls_stylesheet(container_name, palette))
    _polish(container)


def apply_controls_shadow(container: Optional[QWidget], palette: Optional[Dict[str, Any]] = None) -> None:
    if container is None:
        return
    try:
        cfg = dict(palette or {})
        radius = int(cfg.get("radius", 14) or 14)
        shadow_alpha = int(cfg.get("shadow_alpha", 150) or 150)
        effect = QGraphicsDropShadowEffect(container)
        effect.setBlurRadius(max(18, float(radius * 2)))
        effect.setOffset(0, -1)
        effect.setColor(QColor(0, 0, 0, max(0, min(255, shadow_alpha))))
        container.setGraphicsEffect(effect)
    except Exception:
        pass


def configure_control_button(
    button: Optional[QPushButton],
    *,
    role: str,
    text: str,
    min_w: int,
    tooltip: str,
) -> None:
    if button is None:
        return

    button.setText(text)
    button.setProperty("chromeRole", role)
    button.setCursor(Qt.PointingHandCursor)
    button.setFocusPolicy(Qt.NoFocus)
    button.setMinimumHeight(26)
    button.setMaximumHeight(26)
    button.setMinimumWidth(int(min_w))
    button.setMaximumWidth(16777215)
    button.setToolTip(tooltip)
    _polish(button)


def configure_control_slider(slider: Optional[QSlider], role: str, *, min_w: int = 80) -> None:
    if slider is None:
        return
    slider.setProperty("chromeRole", role)
    slider.setMinimumHeight(18)
    slider.setMaximumHeight(18)
    slider.setMinimumWidth(int(min_w))
    slider.setMaximumWidth(16777215)
    _polish(slider)


def configure_time_label(label: Optional[QLabel]) -> None:
    if label is None:
        return
    label.setProperty("chromeRole", "time")
    label.setAlignment(Qt.AlignVCenter | Qt.AlignHCenter)
    label.setMinimumWidth(112)
    label.setMaximumHeight(20)
    _polish(label)


def configure_combo(combo: Optional[QComboBox], *, min_w: int = 150) -> None:
    if combo is None:
        return
    combo.setProperty("chromeRole", "combo")
    combo.setMinimumHeight(24)
    combo.setMaximumHeight(24)
    combo.setMinimumWidth(int(min_w))
    combo.setMaximumWidth(300)
    _polish(combo)


def configure_muted_label(label: Optional[QLabel], text: str = "Vol") -> None:
    if label is None:
        return
    label.setText(text)
    label.setProperty("chromeRole", "muted")
    label.setAlignment(Qt.AlignVCenter | Qt.AlignRight)
    _polish(label)




