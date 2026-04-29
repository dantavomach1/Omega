from __future__ import annotations

from typing import Any, Mapping

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


def _color(value: Any, fallback: str) -> QColor:
    color = QColor(str(value or "").strip())
    if not color.isValid():
        color = QColor(str(fallback or "#000000"))
    if not color.isValid():
        color = QColor("#000000")
    return color


def _mix(left: QColor, right: QColor, ratio: float) -> QColor:
    t = max(0.0, min(1.0, float(ratio)))
    return QColor(
        int(round((left.red() * (1.0 - t)) + (right.red() * t))),
        int(round((left.green() * (1.0 - t)) + (right.green() * t))),
        int(round((left.blue() * (1.0 - t)) + (right.blue() * t))),
        int(round((left.alpha() * (1.0 - t)) + (right.alpha() * t))),
    )


def _text_on(color: QColor) -> QColor:
    luminance = (
        (0.299 * float(color.red()))
        + (0.587 * float(color.green()))
        + (0.114 * float(color.blue()))
    )
    return QColor("#0A0E14") if luminance >= 162.0 else QColor("#F6F9FF")


def apply_omega_palette(
    app: QApplication | None,
    colors: Mapping[str, Any] | None = None,
    *,
    category: str = "dark_transparent",
) -> None:
    """
    Keep the global Qt palette aligned with Omega's active art direction.

    The large theme stylesheet still does the heavy lifting, but this keeps
    native Qt surfaces and dialogs from falling back to generic grey chrome.
    """

    if app is None:
        return

    app.setStyle("Fusion")

    payload = colors if isinstance(colors, Mapping) else {}
    background = _color(payload.get("background"), "#05070B")
    background_alt = _color(payload.get("background_alt"), "#0F1320")
    surface = _color(payload.get("surface_soft", payload.get("card")), "#121826")
    surface_strong = _color(payload.get("surface_strong", payload.get("background_alt")), "#182133")
    text = _color(payload.get("text"), "#F4F7FF")
    muted = _color(payload.get("muted_text"), "#B4C0D8")
    primary = _color(payload.get("primary"), "#5CA0FF")
    secondary = _color(payload.get("secondary"), "#4FD4B3")
    border = _color(payload.get("border"), "#2A3449")
    is_light = str(category or "").strip().casefold().startswith("light")

    window = _mix(background, surface, 0.14 if is_light else 0.18)
    base = _mix(surface, background, 0.10 if is_light else 0.24)
    alt_base = _mix(surface_strong, background_alt, 0.12 if is_light else 0.18)
    button = _mix(surface, background_alt, 0.08 if is_light else 0.14)
    tooltip = _mix(surface_strong, background, 0.08 if is_light else 0.18)
    highlight = _mix(primary, secondary, 0.18)
    highlight_text = _text_on(highlight)
    shadow = _mix(background, border, 0.12 if is_light else 0.08)
    disabled_text = _mix(text, background, 0.54 if is_light else 0.68)
    disabled_surface = _mix(button, background, 0.30 if is_light else 0.42)
    link = _mix(primary, secondary, 0.10)

    palette = QPalette()
    palette.setColor(QPalette.Window, window)
    palette.setColor(QPalette.WindowText, text)
    palette.setColor(QPalette.Base, base)
    palette.setColor(QPalette.AlternateBase, alt_base)
    palette.setColor(QPalette.ToolTipBase, tooltip)
    palette.setColor(QPalette.ToolTipText, text)
    palette.setColor(QPalette.Text, text)
    palette.setColor(QPalette.Button, button)
    palette.setColor(QPalette.ButtonText, text)
    palette.setColor(QPalette.BrightText, QColor("#FFFFFF"))
    palette.setColor(QPalette.Light, _mix(button, text, 0.12 if is_light else 0.08))
    palette.setColor(QPalette.Midlight, _mix(button, border, 0.18))
    palette.setColor(QPalette.Mid, border)
    palette.setColor(QPalette.Dark, shadow)
    palette.setColor(QPalette.Shadow, _mix(background, shadow, 0.35))
    palette.setColor(QPalette.Highlight, highlight)
    palette.setColor(QPalette.HighlightedText, highlight_text)
    palette.setColor(QPalette.Link, link)
    palette.setColor(QPalette.LinkVisited, _mix(link, text, 0.18))
    try:
        palette.setColor(QPalette.PlaceholderText, muted)
    except Exception:
        pass

    disabled_group = QPalette.Disabled
    palette.setColor(disabled_group, QPalette.WindowText, disabled_text)
    palette.setColor(disabled_group, QPalette.Text, disabled_text)
    palette.setColor(disabled_group, QPalette.ButtonText, disabled_text)
    palette.setColor(disabled_group, QPalette.Base, disabled_surface)
    palette.setColor(disabled_group, QPalette.AlternateBase, _mix(disabled_surface, background, 0.24))
    palette.setColor(disabled_group, QPalette.Button, disabled_surface)
    palette.setColor(disabled_group, QPalette.Highlight, _mix(highlight, background, 0.42))
    try:
        palette.setColor(disabled_group, QPalette.PlaceholderText, _mix(muted, background, 0.46))
    except Exception:
        pass

    app.setPalette(palette)


def apply_dark_palette(app: QApplication) -> None:
    apply_omega_palette(app)
