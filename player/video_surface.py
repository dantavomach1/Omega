# omega/player/video_surface.py

from __future__ import annotations

from PySide6.QtCore import Qt, QEvent, QTimer, Signal, QPoint, QRect, QSize
from PySide6.QtWidgets import (
    QWidget,
    QPushButton,
    QLabel,
    QSlider,
    QComboBox,
    QHBoxLayout,
    QVBoxLayout,
    QStyle,
    QStyleOptionSlider,
)

from omega.player.player_chrome import (
    CONTROLS_BAR_HEIGHT,
    apply_controls_container_chrome,
    apply_controls_shadow,
    configure_combo,
    configure_control_button,
    configure_control_slider,
    configure_time_label,
)


def fmt_ms(ms: int) -> str:
    if ms < 0:
        ms = 0
    sec = ms // 1000
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


class ClickableVideoSurface(QWidget):
    clicked = Signal()
    doubleClicked = Signal()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.doubleClicked.emit()
        super().mouseDoubleClickEvent(e)


class JumpSlider(QSlider):
    jumpRequested = Signal(int)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            opt = QStyleOptionSlider()
            self.initStyleOption(opt)
            handle_rect = self.style().subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderHandle, self)
            pos = event.position().toPoint()
            if not handle_rect.contains(pos):
                span = self.width() if self.orientation() == Qt.Horizontal else self.height()
                if span > 0:
                    coord = pos.x() if self.orientation() == Qt.Horizontal else (span - pos.y())
                    value = QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), coord, span)
                    self.setValue(int(value))
                    self.jumpRequested.emit(int(value))
                    event.accept()
                    return
        super().mousePressEvent(event)


class FullscreenVideoWindow(QWidget):
    requestExitFullscreen = Signal()
    requestTogglePlayPause = Signal()
    requestSeekRelative = Signal(int)
    requestStop = Signal()
    requestNext = Signal()
    requestPrev = Signal()
    requestSeekToPos = Signal(int)  # 0..1000
    requestVolume = Signal(int)
    requestSubtitlePick = Signal(object)
    requestAudioPick = Signal(object)
    controlsVisibilityChanged = Signal(bool)

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setStyleSheet("background-color: black;")
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

        self.videoSurface = ClickableVideoSurface(self)
        self.videoSurface.setObjectName("fsVideoSurface")
        self.videoSurface.setStyleSheet("background-color: black;")
        self.videoSurface.setMouseTracking(True)
        self.videoSurface.setFocusPolicy(Qt.StrongFocus)

        self.videoSurface.setAttribute(Qt.WA_NativeWindow, True)
        self.videoSurface.setAttribute(Qt.WA_DontCreateNativeAncestors, True)
        self.videoSurface.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.videoSurface.setAttribute(Qt.WA_PaintOnScreen, True)
        self._chrome_palette = {}
        self._controls_height = max(90, int(CONTROLS_BAR_HEIGHT * 1.8))

        # Floating controls window
        self.controls = QWidget(self)
        self.controls.setObjectName("fsControls")
        self.controls.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        try:
            self.controls.setWindowFlag(Qt.WindowDoesNotAcceptFocus, True)
        except Exception:
            pass
        self.controls.setAttribute(Qt.WA_StyledBackground, True)
        self.controls.setAttribute(Qt.WA_TranslucentBackground, True)
        self.controls.setMouseTracking(True)
        self.controls.setMinimumHeight(self._controls_height)
        self.controls.setMaximumHeight(self._controls_height)

        root = QVBoxLayout(self.controls)
        root.setContentsMargins(12, 8, 12, 10)
        root.setSpacing(6)
        seek_row = QHBoxLayout()
        seek_row.setContentsMargins(0, 0, 0, 0)
        seek_row.setSpacing(8)
        transport_row = QHBoxLayout()
        transport_row.setContentsMargins(0, 0, 0, 0)
        transport_row.setSpacing(6)
        root.addLayout(seek_row)
        root.addLayout(transport_row)

        self.prevBtn = QPushButton("Prev")
        self.backBtn = QPushButton("-10s")
        self.playPauseBtn = QPushButton("Play")
        self.fwdBtn = QPushButton("+10s")
        self.nextBtn = QPushButton("Next")

        self.timeLbl = QLabel("0:00 / 0:00")
        self.seek = JumpSlider(Qt.Horizontal)
        self.seek.setRange(0, 1000)
        self.seek.setTracking(True)

        self.subs = QComboBox()
        self.audio = QComboBox()

        self.vol = QSlider(Qt.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(80)

        self.stopBtn = QPushButton("Stop")
        self.fullBtn = QPushButton("Exit Fullscreen")

        seek_row.addWidget(self.timeLbl)
        seek_row.addWidget(self.seek, 1)

        transport_row.addWidget(self.prevBtn)
        transport_row.addWidget(self.backBtn)
        transport_row.addWidget(self.playPauseBtn)
        transport_row.addWidget(self.fwdBtn)
        transport_row.addWidget(self.nextBtn)
        transport_row.addStretch(1)
        transport_row.addWidget(self.subs)
        transport_row.addWidget(self.audio)
        transport_row.addWidget(self.vol)
        transport_row.addWidget(self.stopBtn)
        transport_row.addWidget(self.fullBtn)

        self._apply_chrome()

        self._hideTimer = QTimer(self)
        self._hideTimer.setSingleShot(True)
        self._hideTimer.timeout.connect(self._hide_controls)

        self._controlsVisible = True
        self._userDragging = False
        self._ignoreSeekSignals = False
        self._activation_zone_h = 160

        self.videoSurface.clicked.connect(self.requestTogglePlayPause.emit)
        self.videoSurface.doubleClicked.connect(self.requestExitFullscreen.emit)

        self.fullBtn.clicked.connect(self.requestExitFullscreen.emit)
        self.playPauseBtn.clicked.connect(self.requestTogglePlayPause.emit)
        self.stopBtn.clicked.connect(self.requestStop.emit)
        self.backBtn.clicked.connect(lambda: self.requestSeekRelative.emit(-10_000))
        self.fwdBtn.clicked.connect(lambda: self.requestSeekRelative.emit(10_000))
        self.prevBtn.clicked.connect(self.requestPrev.emit)
        self.nextBtn.clicked.connect(self.requestNext.emit)

        self.vol.valueChanged.connect(self.requestVolume.emit)

        self.seek.sliderPressed.connect(self._on_seek_pressed)
        self.seek.sliderReleased.connect(self._on_seek_released)
        self.seek.valueChanged.connect(self._on_seek_changed)
        self.seek.jumpRequested.connect(lambda value: self.requestSeekToPos.emit(int(value)))

        self.subs.currentIndexChanged.connect(lambda _i: self.requestSubtitlePick.emit(self.subs.currentData()))
        self.audio.currentIndexChanged.connect(lambda _i: self.requestAudioPick.emit(self.audio.currentData()))

        self.installEventFilter(self)
        self.videoSurface.installEventFilter(self)
        self.controls.installEventFilter(self)

        self._layout()
        self.controls.show()

    def _apply_chrome(self) -> None:
        apply_controls_container_chrome(self.controls, "fsControls", palette=self._chrome_palette)
        apply_controls_shadow(self.controls, palette=self._chrome_palette)

        configure_control_button(self.prevBtn, role="transport", text="Prev", min_w=54, tooltip="Previous item")
        configure_control_button(self.backBtn, role="transport", text="-10s", min_w=54, tooltip="Seek backward 10 seconds")
        configure_control_button(self.playPauseBtn, role="primary", text="Play", min_w=72, tooltip="Toggle play or pause")
        configure_control_button(self.fwdBtn, role="transport", text="+10s", min_w=54, tooltip="Seek forward 10 seconds")
        configure_control_button(self.nextBtn, role="transport", text="Next", min_w=54, tooltip="Next item")
        configure_control_button(self.stopBtn, role="danger", text="Stop", min_w=56, tooltip="Stop playback")
        configure_control_button(self.fullBtn, role="accent", text="Exit Fullscreen", min_w=124, tooltip="Exit fullscreen")

        configure_control_slider(self.seek, "seek", min_w=320)
        configure_control_slider(self.vol, "volume", min_w=110)
        configure_time_label(self.timeLbl)
        configure_combo(self.subs, min_w=170)
        configure_combo(self.audio, min_w=170)

    def set_chrome_palette(self, palette: dict | None) -> None:
        self._chrome_palette = dict(palette or {})
        self._apply_chrome()
        self._layout()

    def _layout(self):
        self.videoSurface.setGeometry(0, 0, self.width(), self.height())

        h = int(self._controls_height)
        top_left = self.mapToGlobal(QPoint(0, self.height() - h))
        self.controls.setGeometry(top_left.x(), top_left.y(), self.width(), h)
        self.controls.raise_()

    def _global_window_rect(self) -> QRect:
        tl = self.mapToGlobal(QPoint(0, 0))
        return QRect(tl.x(), tl.y(), self.width(), self.height())

    def _global_controls_rect(self) -> QRect:
        g = self.controls.geometry()
        return QRect(g.x(), g.y(), g.width(), g.height())

    def _global_activation_rect(self) -> QRect:
        win_rect = self._global_window_rect()
        return QRect(
            win_rect.x(),
            win_rect.y() + win_rect.height() - self._activation_zone_h,
            win_rect.width(),
            self._activation_zone_h,
        )

    def _event_global_pos(self, obj, event) -> QPoint | None:
        try:
            return event.globalPosition().toPoint()
        except Exception:
            pass
        try:
            pos = event.position().toPoint()
        except Exception:
            try:
                pos = event.pos()
            except Exception:
                pos = None
        if pos is None:
            return None
        try:
            widget = obj if isinstance(obj, QWidget) else self
            return widget.mapToGlobal(pos)
        except Exception:
            return None

    def _handle_pointer_activity(self, global_pos: QPoint | None) -> None:
        if not self.isVisible():
            return
        if self._userDragging:
            self._show_controls()
            self._hideTimer.stop()
            return
        if global_pos is None:
            self._show_controls()
            self._hideTimer.start(1800)
            return

        if self._global_controls_rect().contains(global_pos):
            self._show_controls()
            self._hideTimer.stop()
            return

        if self._global_activation_rect().contains(global_pos):
            self._show_controls()
            self._hideTimer.start(1800)
            return

        if self._controlsVisible:
            self._hideTimer.start(900)

    def showEvent(self, e):
        super().showEvent(e)
        self.activateWindow()
        self.raise_()
        self.setFocus(Qt.ActiveWindowFocusReason)
        self.videoSurface.setFocus(Qt.ActiveWindowFocusReason)
        QTimer.singleShot(0, self._layout)
        QTimer.singleShot(0, self._show_controls)
        self._hideTimer.start(1800)

    def hideEvent(self, e):
        super().hideEvent(e)
        was_visible = bool(self._controlsVisible)
        self.controls.hide()
        self._controlsVisible = False
        self._hideTimer.stop()
        if was_visible:
            self.controlsVisibilityChanged.emit(False)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._layout()

    def moveEvent(self, e):
        super().moveEvent(e)
        self._layout()

    def eventFilter(self, obj, event):
        et = event.type()
        if et in (QEvent.MouseMove, QEvent.HoverMove, QEvent.Enter):
            self._handle_pointer_activity(self._event_global_pos(obj, event))
        elif et == QEvent.Leave:
            if not self._userDragging and self._controlsVisible:
                self._hideTimer.start(500)
        elif et == QEvent.KeyPress:
            if event.key() == Qt.Key_Escape:
                self.requestExitFullscreen.emit()
                return True
            if event.key() == Qt.Key_Space:
                self.requestTogglePlayPause.emit()
                return True
        return super().eventFilter(obj, event)

    def _show_controls(self):
        if not self._controlsVisible:
            self.controls.show()
            self._controlsVisible = True
            self.controlsVisibilityChanged.emit(True)
        self._layout()
        self.controls.raise_()

    def _hide_controls(self):
        if self._userDragging:
            return
        self.controls.hide()
        if self._controlsVisible:
            self._controlsVisible = False
            self.controlsVisibilityChanged.emit(False)

    def _on_seek_pressed(self):
        self._userDragging = True
        self._show_controls()
        self._hideTimer.stop()

    def _on_seek_released(self):
        self._userDragging = False
        self.requestSeekToPos.emit(int(self.seek.value()))
        self._hideTimer.start(1200)

    def _on_seek_changed(self, _v: int):
        if self._ignoreSeekSignals:
            return
        if self._userDragging:
            self._show_controls()

    def set_time(self, cur_ms: int, dur_ms: int):
        if not self._userDragging:
            self._ignoreSeekSignals = True
            try:
                if dur_ms > 0:
                    self.seek.setValue(int((cur_ms / dur_ms) * 1000))
                else:
                    self.seek.setValue(0)
            finally:
                self._ignoreSeekSignals = False
        self.timeLbl.setText(f"{fmt_ms(cur_ms)} / {fmt_ms(dur_ms)}")


class FloatingMiniPlayer(QWidget):
    requestReturnToPlayer = Signal()
    requestTogglePlayPause = Signal()
    requestToggleMute = Signal()
    requestSeekRelative = Signal(int)
    requestPrevEpisode = Signal()
    requestNextEpisode = Signal()
    requestFullscreen = Signal()
    requestCloseMini = Signal()
    requestSeekToPos = Signal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("floatingMiniPlayer")
        self.setWindowFlags(Qt.SubWindow | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setMouseTracking(True)
        self.setMinimumSize(320, 208)
        self.resize(420, 248)
        self._drag_active = False
        self._resize_mode = ""
        self._drag_origin = QPoint()
        self._drag_start_pos = QPoint()
        self._drag_start_geo = QRect()
        self._resize_margin = 10

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)
        self.returnBtn = QPushButton("Now Playing", self)
        self.returnBtn.clicked.connect(self.requestReturnToPlayer.emit)
        self.statusLbl = QLabel("Mini Player", self)
        self.statusLbl.setStyleSheet("color: rgba(240,244,255,210); font-size: 11px; font-weight: 600;")
        self.fullscreenBtn = QPushButton("Full", self)
        self.fullscreenBtn.setMaximumWidth(56)
        self.fullscreenBtn.clicked.connect(self.requestFullscreen.emit)
        self.closeBtn = QPushButton("X", self)
        self.closeBtn.setMaximumWidth(36)
        self.closeBtn.clicked.connect(self.requestCloseMini.emit)
        header.addWidget(self.returnBtn, 0)
        header.addWidget(self.statusLbl, 1)
        header.addWidget(self.fullscreenBtn, 0)
        header.addWidget(self.closeBtn, 0)
        root.addLayout(header)

        self.videoFrame = QWidget(self)
        self.videoFrame.setObjectName("floatingMiniVideoFrame")
        self.videoFrame.setStyleSheet("background: rgba(0,0,0,210); border-radius: 12px;")
        video_l = QVBoxLayout(self.videoFrame)
        video_l.setContentsMargins(0, 0, 0, 0)
        video_l.setSpacing(0)
        self.videoSlot = QWidget(self.videoFrame)
        self.videoSlot.setObjectName("floatingMiniVideoSlot")
        self.videoSlot.setAttribute(Qt.WA_StyledBackground, True)
        self.videoSlot.setStyleSheet("background: black; border-radius: 12px;")
        self.videoSlot.setMinimumHeight(108)
        self.placeholder = QLabel("Mini player follows playback here.", self.videoSlot)
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.placeholder.setWordWrap(True)
        self.placeholder.setStyleSheet("color: rgba(255,255,255,160); padding: 12px;")
        slot_l = QVBoxLayout(self.videoSlot)
        slot_l.setContentsMargins(0, 0, 0, 0)
        slot_l.setSpacing(0)
        slot_l.addWidget(self.placeholder, 1)
        video_l.addWidget(self.videoSlot, 1)
        root.addWidget(self.videoFrame, 1)

        self.progress = JumpSlider(Qt.Horizontal, self)
        self.progress.setRange(0, 1000)
        self.progress.setTracking(False)
        self.progress.jumpRequested.connect(lambda value: self.requestSeekToPos.emit(int(value)))
        root.addWidget(self.progress)

        transport = QHBoxLayout()
        transport.setContentsMargins(0, 0, 0, 0)
        transport.setSpacing(6)
        self.prevEpisodeBtn = QPushButton("Prev Ep", self)
        self.prevEpisodeBtn.clicked.connect(self.requestPrevEpisode.emit)
        self.skipBackBtn = QPushButton("-10s", self)
        self.skipBackBtn.clicked.connect(lambda: self.requestSeekRelative.emit(-10_000))
        self.playPauseBtn = QPushButton("Pause", self)
        self.playPauseBtn.clicked.connect(self.requestTogglePlayPause.emit)
        self.skipForwardBtn = QPushButton("+10s", self)
        self.skipForwardBtn.clicked.connect(lambda: self.requestSeekRelative.emit(10_000))
        self.nextEpisodeBtn = QPushButton("Next Ep", self)
        self.nextEpisodeBtn.clicked.connect(self.requestNextEpisode.emit)
        transport.addWidget(self.prevEpisodeBtn)
        transport.addWidget(self.skipBackBtn)
        transport.addWidget(self.playPauseBtn)
        transport.addWidget(self.skipForwardBtn)
        transport.addWidget(self.nextEpisodeBtn)
        root.addLayout(transport)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(6)
        self.muteBtn = QPushButton("Mute", self)
        self.muteBtn.clicked.connect(self.requestToggleMute.emit)
        self.timeLbl = QLabel("0:00 / 0:00", self)
        self.timeLbl.setStyleSheet("color: rgba(240,244,255,200); font-size: 10px;")
        controls.addWidget(self.muteBtn)
        controls.addStretch(1)
        controls.addWidget(self.timeLbl)
        root.addLayout(controls)

        self.setStyleSheet(
            "QWidget#floatingMiniPlayer {"
            "background: rgba(11, 15, 24, 228);"
            "border: 1px solid rgba(255,255,255,0.18);"
            "border-radius: 16px;"
            "}"
            "QWidget#floatingMiniPlayer QPushButton {"
            "background: rgba(255,255,255,0.08);"
            "color: rgba(248,250,255,228);"
            "border: 1px solid rgba(255,255,255,0.16);"
            "border-radius: 10px;"
            "padding: 6px 10px;"
            "font-size: 11px;"
            "font-weight: 700;"
            "}"
            "QWidget#floatingMiniPlayer QPushButton:hover {"
            "background: rgba(255,255,255,0.14);"
            "border-color: rgba(255,255,255,0.24);"
            "}"
            "QWidget#floatingMiniPlayer QSlider::groove:horizontal {"
            "height: 6px;"
            "border-radius: 3px;"
            "background: rgba(255,255,255,0.14);"
            "}"
            "QWidget#floatingMiniPlayer QSlider::handle:horizontal {"
            "width: 14px;"
            "margin: -4px 0;"
            "border-radius: 7px;"
            "background: rgba(255,255,255,0.9);"
            "}"
        )

    def set_video_widget(self, widget: QWidget | None) -> None:
        layout = self.videoSlot.layout()
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            child = item.widget()
            if child is not None:
                try:
                    child.setParent(None)
                except Exception:
                    pass
        if widget is None:
            self.placeholder.setParent(self.videoSlot)
            layout.addWidget(self.placeholder, 1)
            self.placeholder.show()
            return
        try:
            widget.setParent(self.videoSlot)
        except Exception:
            pass
        layout.addWidget(widget, 1)
        widget.show()

    def set_playback_state(self, *, paused: bool, muted: bool) -> None:
        self.playPauseBtn.setText("Play" if paused else "Pause")
        self.muteBtn.setText("Unmute" if muted else "Mute")

    def set_time(self, cur_ms: int, dur_ms: int) -> None:
        if dur_ms > 0:
            self.progress.setValue(int(max(0.0, min(1.0, float(cur_ms) / float(dur_ms))) * 1000.0))
        else:
            self.progress.setValue(0)
        self.timeLbl.setText(f"{fmt_ms(cur_ms)} / {fmt_ms(dur_ms)}")

    def _hit_resize_mode(self, pos: QPoint) -> str:
        left = pos.x() <= self._resize_margin
        right = pos.x() >= self.width() - self._resize_margin
        top = pos.y() <= self._resize_margin
        bottom = pos.y() >= self.height() - self._resize_margin
        if left and top:
            return "top_left"
        if right and top:
            return "top_right"
        if left and bottom:
            return "bottom_left"
        if right and bottom:
            return "bottom_right"
        return ""

    def _apply_cursor_for_pos(self, pos: QPoint) -> None:
        mode = self._hit_resize_mode(pos)
        cursor = Qt.ArrowCursor
        if mode in {"top_left", "bottom_right"}:
            cursor = Qt.SizeFDiagCursor
        elif mode in {"top_right", "bottom_left"}:
            cursor = Qt.SizeBDiagCursor
        self.setCursor(cursor)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        pos = event.position().toPoint()
        self._resize_mode = self._hit_resize_mode(pos)
        self._drag_origin = event.globalPosition().toPoint()
        self._drag_start_geo = self.geometry()
        if self._resize_mode:
            event.accept()
            return
        header_h = max(34, self.returnBtn.height() + 10)
        if pos.y() <= header_h:
            self._drag_active = True
            self._drag_start_pos = self.pos()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        if self._resize_mode:
            delta = event.globalPosition().toPoint() - self._drag_origin
            geo = QRect(self._drag_start_geo)
            min_w = max(320, self.minimumWidth())
            min_h = max(208, self.minimumHeight())
            if "left" in self._resize_mode:
                new_left = min(geo.right() - min_w, geo.left() + delta.x())
                geo.setLeft(new_left)
            if "right" in self._resize_mode:
                geo.setRight(max(geo.left() + min_w, geo.right() + delta.x()))
            if "top" in self._resize_mode:
                new_top = min(geo.bottom() - min_h, geo.top() + delta.y())
                geo.setTop(new_top)
            if "bottom" in self._resize_mode:
                geo.setBottom(max(geo.top() + min_h, geo.bottom() + delta.y()))
            self.setGeometry(geo.normalized())
            event.accept()
            return
        if self._drag_active:
            delta = event.globalPosition().toPoint() - self._drag_origin
            self.move(self._drag_start_pos + delta)
            event.accept()
            return
        self._apply_cursor_for_pos(pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_active = False
        self._resize_mode = ""
        self._apply_cursor_for_pos(event.position().toPoint())
        super().mouseReleaseEvent(event)

    def set_subtitle_choices(self, items: list[tuple[str, object]]):
        if not hasattr(self, "subs"):
            return
        self.subs.blockSignals(True)
        try:
            self.subs.clear()
            for label, data in items:
                self.subs.addItem(label, data)
        finally:
            self.subs.blockSignals(False)

    def set_audio_choices(self, items: list[tuple[str, object]]):
        if not hasattr(self, "audio"):
            return
        self.audio.blockSignals(True)
        try:
            self.audio.clear()
            for label, data in items:
                self.audio.addItem(label, data)
        finally:
            self.audio.blockSignals(False)


