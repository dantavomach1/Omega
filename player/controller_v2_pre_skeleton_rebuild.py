# =========================
# omega/player/controller.py
# =========================
from __future__ import annotations

import os
import re
import json
import time
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, List, Tuple, Type
from collections import defaultdict
from difflib import SequenceMatcher

from PySide6.QtCore import QObject, Qt, QRect, QTimer, QEvent
from PySide6.QtGui import QFont, QCursor
from PySide6.QtWidgets import (
    QMainWindow,
    QApplication,
    QWidget,
    QScrollArea,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLayout,
    QSizePolicy,
    QFrame,
    QLabel,
    QPushButton,
    QToolButton,
    QComboBox,
    QStackedWidget,
    QSlider,
    QMessageBox,
    QFileDialog,
)

from omega.widgets.rail_shell import RailShell, SnapConfig
from omega.library import LibraryManager, LibraryScanner, migrate_sources_txt_to_library_json

try:
    from omega.ui.qt_utils import dprint as _qt_dprint, safe_find, fmt_ms
except Exception:
    _qt_dprint = None


    def safe_find(*args, **kwargs):  # type: ignore
        return None


    def fmt_ms(x):  # type: ignore
        return str(x)


def dprint(*args, **kwargs):
    try:
        if _qt_dprint is not None:
            _qt_dprint(*args, **kwargs)
        else:
            print(*args)
    except Exception:
        try:
            print(*args)
        except Exception:
            pass


try:
    dprint  # type: ignore[name-defined]
except Exception:
    def dprint(*args, **kwargs):  # type: ignore[no-redef]
        try:
            print(*args)
        except Exception:
            pass


def _dbg_widget(w: Optional[QWidget], name: str) -> None:
    try:
        if w is None:
            dprint(f"[DBG][{name}] None")
            return
        sp = w.sizePolicy()
        dprint(
            f"[DBG][{name}] obj={w.objectName()} cls={type(w).__name__} "
            f"geo=({w.x()},{w.y()},{w.width()}x{w.height()}) "
            f"minW={w.minimumWidth()} maxW={w.maximumWidth()} "
            f"hPolicy={sp.horizontalPolicy()} vPolicy={sp.verticalPolicy()} "
            f"parent={w.parent().objectName() if w.parent() else None}"
        )
    except Exception as e:
        dprint(f"[DBG][{name}] error:", e)


# ============================================================
# ADD / CHANGE 1: Imports
# (ANCHOR LINE — insert AFTER this exact line)
# from omega.ui.qt_utils import d
# ============================================================

from omega.ui.posters import apply_poster
from omega.ui.thumbnails import EpisodeThumbnailer
from omega.app.contracts import ShowGroup, EpisodeRef
from omega.app.text_naming import (
    NameCleaner,
    parse_season_episode,
    episode_fallback_label,
    extract_episode_title_from_filename,
)
from omega.library.metadata_cache import MetadataCache, MetadataProvider
from omega.player.mpv_backend import MPVBackend
from omega.ui.poster_art_dialog import PosterArtDialog, MissingArtItem


# ============================================================
# T U N I N G   Z O N E
# ============================================================

@dataclass(frozen=True)
class ChildSpec:
    name: str
    cls: Type[QWidget]
    geom: QRect
    stylesheet: str
    font: QFont
    text: str
    alignment: Qt.Alignment


@dataclass(frozen=True)
class CardTemplate:
    root_cls: Type[QWidget]
    root_size: QRect
    root_stylesheet: str
    root_font: QFont
    children: Dict[str, ChildSpec]


@dataclass(frozen=True)
class HomeLayoutTuning:
    # ============================================================
    # PRIORITY KNOBS (layout positioning + sizing + min/max clamps)
    # ------------------------------------------------------------
    # If you only touch ONE area while tuning layout, touch these:
    # - Pads: move content inside the Home viewport (left/right/top/bottom)
    # - Lane/Gutters: constrain or allow edge-to-edge width
    # - Card sizing + visible counts: determines how many cards fit and how big
    # - Spacing: row spacing + card spacing
    # - Rail pads: extra breathing room to hit a target “Netflix-like” feel
    # ============================================================

    # --- Vertical rhythm (rows) ---
    row_block_spacing_px: int = 50  # Vertical space BETWEEN rail blocks (row to row).
    row_block_title_to_rail_spacing_px: int = 8  # Vertical space BETWEEN a row title and its rail.

    # --- Home content padding (inside the Home scroll viewport) ---
    # These do NOT move the "viewport" itself; they pad the *contents* within it.
    home_content_pad_left_px: int = 0  # Left padding inside Home (adds space before rails).
    home_content_pad_right_px: int = 0  # Right padding inside Home (adds space after rails).
    home_content_pad_top_px: int = 70  # Top padding before first row.
    home_content_pad_bottom_px: int = 80  # Bottom padding after last row.

    # --- Center lane (only used when edge_to_edge=False) ---
    # "Center lane" = a fixed-width content lane centered in the viewport,
    # with gutters on both sides.
    center_lane_max_width_px: int = 10000  # Max width of the centered lane (clamped by viewport).
    center_lane_gutter_ratio: float = 0.0  # Gutters as % of viewport width (0.08 = ~8% each side).
    center_lane_gutter_min_px: int = 0  # Minimum gutter on each side.
    center_lane_gutter_max_px: int = 0  # Maximum gutter on each side.

    # --- Card size clamps (core “bigger/smaller” knobs) ---
    card_w_min_px: int = 320  # Minimum card width (responsive clamp lower bound).
    card_w_max_px: int = 320  # Maximum card width (responsive clamp upper bound).
    card_h_min_px: int = 170  # Minimum card height.
    card_h_max_px: int = 170  # Maximum card height.

    # --- How many cards we TRY to show across in the visible lane ---
    # This influences the “target cell size” math used to pick a card width.
    visible_cards_min: int = 5  # Lower bound for visible card count target.
    visible_cards_max: int = 6  # Upper bound for visible card count target.

    # --- Show merge heuristics (Library “same show across folders” grouping) ---
    # When scanning multiple sources, we try to merge "Dragon Ball Z" vs "Dragonball Z" etc.
    show_merge_fuzzy_threshold: float = 0.92  # Similarity threshold (0–1). Higher = stricter merging.
    show_merge_length_diff_cutoff: int = 6  # If name lengths differ more than this, don't merge.
    show_merge_min_name_len: int = 4  # Ignore fuzzy merge for super-short names (too noisy).

    # --- Target cell sizing (how we pick card width from the available lane width) ---
    # Think of "target cell" as: card_width + spacing (per card slot).
    target_cell_divisor: float = 6.0  # lane_width / divisor -> desired cell size before clamping.
    target_cell_min_px: int = 300  # Clamp: minimum target cell size.
    target_cell_max_px: int = 380  # Clamp: maximum target cell size.

    # --- Horizontal spacing between cards inside rails ---
    card_spacing_ratio_of_lane: float = 0.0  # Optional: spacing as % of lane width (usually 0).
    card_spacing_min_px: int = 20  # Minimum inter-card spacing.
    card_spacing_max_px: int = 20  # Maximum inter-card spacing.

    # --- Rail inner padding (space inside each rail's scrolling area, around the cards) ---
    rail_inner_pad_left_px: int = 0  # Left padding inside the rail (before first card).
    rail_inner_pad_right_px: int = 0  # Right padding inside the rail (after last card).
    rail_inner_pad_top_px: int = 0  # Top padding inside the rail.
    rail_inner_pad_bottom_px: int = 0  # Bottom padding inside the rail.
    rail_overflow_padding_px: int = 1  # Tiny safety pad to prevent overflow/clip edges.

    # --- Rail gutter (extra margin at the *edges* of the viewport/lane for rails) ---
    # In edge-to-edge mode this is typically 0; in centered-lane mode it can be >0.
    rail_gutter_min_px: int = 0  # Minimum gutter applied to RailShell overlays/chevrons.
    rail_gutter_max_px: int = 0  # Maximum gutter.
    rail_gutter_ratio: float = 0.0  # Gutter as % of lane/viewport width.
    narrow_window_threshold_px: int = 9000  # If viewport is narrower than this, use “narrow” ratios.
    narrow_window_gutter_ratio: float = 0.0  # Alternate gutter ratio for narrow windows.

    # --- Title padding (left/right inset for the title row) ---
    rail_title_pad_left_px: int = 0  # Left padding for the title line.
    rail_title_pad_right_px: int = 0  # Right padding for the title line.
    rail_title_min_h_px: int = 40  # Title row minimum height.
    rail_title_max_h_px: int = 200  # Title row maximum height.

    # --- Rail vertical padding (extra height around cards to form a rail “band”) ---
    # This is what makes rails feel less cramped vertically.
    rail_pad_min_px: int = 20  # Minimum extra padding added into rail height.
    rail_pad_max_px: int = 40  # Maximum extra padding.
    rail_pad_ratio_of_card_h: float = 0.15  # Rail padding proportional to card height.

    # --- Optional "hero" space at the top of Home (reserved area above first rail) ---
    hero_space_ratio_of_viewport_h: float = 0.0  # Hero height as % of viewport height.
    hero_space_min_px: int = 0  # Hero min height.
    hero_space_max_px: int = 0  # Hero max height.

    # --------------------------------------------------------
    # EDGE-TO-EDGE MODE
    # --------------------------------------------------------
    edge_to_edge: bool = True  # True: rails run flush to viewport width (no center lane).
    edge_safe_inset_px: int = 0  # Optional small inset (like 8–20px) even in edge-to-edge.

    # --- Rail visual affordances ---
    rail_fade_px: int = 100  # Width of left/right fade overlays on rails.
    snap_page_steps: int = 5  # Chevron click moves this many “card steps”.

    # --- Responsive rebuild / thumbnail background work ---
    resize_debounce_ms: int = 120  # Delay after resize before rebuilding responsive layout.
    thumbs_pump_interval_ms: int = 400  # How often thumbnail worker pumps queued thumbnail jobs.
    thumbs_initial_scan_delay_ms: int = 800  # Delay before starting initial thumbnail scan after launch.


@dataclass(frozen=True)
class CardOverlayTuning:
    show_title_height_px: int = 70  # Show card title bar height.
    show_title_pad_top_px: int = 10  # Padding above show title text inside the fade bar.
    episode_title_height_px: int = 54  # Episode card title bar height.
    episode_title_pad_top_px: int = 8  # Padding above episode title text.
    fade_default_height_px: int = 58  # Default gradient/fade overlay height.
    fade_min_height_px: int = 44  # Minimum fade overlay height.
    fade_pad_left_px: int = 14  # Left padding for text/buttons inside fade overlay.
    fade_pad_right_px: int = 14  # Right padding for text/buttons inside fade overlay.
    more_btn_w_px: int = 26  # "..." button width.
    more_btn_h_px: int = 26  # "..." button height.
    poster_radius_px: int = 18  # Rounded-corner radius for posters.


@dataclass(frozen=True)
class InlineExpanderTuning:
    outer_spacing_px: int = 0  # Extra spacing around the inline expander container.
    top_bar_spacing_px: int = 12  # Spacing between controls in the expander top bar.
    episodes_spacing_px: int = 18  # Horizontal spacing between episode cards.
    episodes_row_spacing_px: int = 20  # Vertical spacing between episode rows (if wrapping).
    close_btn_w_px: int = 36  # Close button width.
    season_box_min_w_px: int = 180  # Minimum width for the season dropdown.
    episode_card_scale: float = 0.92  # Episode cards scale relative to show cards.
    episode_rail_extra_px: int = 38  # Extra pixels added to episode rail height.
    fallback_episode_scroll_h_px: int = 190  # Fallback height for episode scroll area.
    ensure_visible_delay_ms: int = 20  # Delay before auto-scrolling to ensure expander is visible.
    ensure_visible_y_margin_px: int = 40  # Vertical margin when ensuring expander visibility.


@dataclass(frozen=True)
class PlayerTuning:
    ui_tick_interval_ms: int = 250  # UI refresh tick for time labels/slider updates.
    seek_lock_release_ms: int = 650  # Debounce window for seek slider to avoid jitter.
    seek_slider_max: int = 1000  # Slider range (0..max); maps to time.
    seek_slider_page_step: int = 25  # Page step (keyboard) for slider.
    seek_jump_back_ms: int = 10_000  # Jump back amount (ms).
    seek_jump_fwd_ms: int = 10_000  # Jump forward amount (ms).
    seek_lock_release_tolerance_ms: int = 900  # Tolerance for "settling" after seek before re-sync.


@dataclass(frozen=True)
class OmegaTuning:
    home: HomeLayoutTuning = HomeLayoutTuning()
    overlays: CardOverlayTuning = CardOverlayTuning()
    inline: InlineExpanderTuning = InlineExpanderTuning()
    player: PlayerTuning = PlayerTuning()


# ============================================================
# PlayerController
# ============================================================

class PlayerController(QObject):
    # ============================================================
    # VIEWPORT / LAYOUT DEBUG (one-shot, high-signal)
    # ============================================================
    def _sp_name(self, w: QWidget) -> str:
        try:
            sp = w.sizePolicy()
            return f"H={int(sp.horizontalPolicy())} V={int(sp.verticalPolicy())} HS={int(sp.horizontalStretch())} VS={int(sp.verticalStretch())}"
        except Exception:
            return "H=? V=?"

    def _dbg_geom(self, tag: str, w: Optional[QWidget]):
        if w is None:
            print(f"[DBG][{tag}] <None>")
            return
        try:
            g = w.geometry()
            print(
                f"[DBG][{tag}] {w.__class__.__name__} name={w.objectName()} "
                f"geom=({g.x()},{g.y()},{g.width()}x{g.height()}) "
                f"size=({w.width()}x{w.height()}) "
                f"min=({w.minimumWidth()}x{w.minimumHeight()}) "
                f"max=({w.maximumWidth()}x{w.maximumHeight()}) "
                f"sp={self._sp_name(w)}"
            )
        except Exception as e:
            print(f"[DBG][{tag}] error: {e}")

    def _home_force_expand_policies(self):
        """
        Hard-override any Qt Designer size constraints that cause the Home page
        to render as a tiny 'island' inside a big black viewport.
        """
        hs = getattr(self, "homeScrollArea", None)
        hc = getattr(self, "homeScrollContents", None)
        hcontent = getattr(self, "homeContent", None)

        if hs is None or hc is None:
            print("[HOME][CRUNCH][WARN] homeScrollArea/homeScrollContents missing; cannot force expand policies.")
            return

        # 1) Make the scroll area behave like a real viewport host
        hs.setWidgetResizable(True)
        hs.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # 2) Remove accidental fixed sizing from Designer (common cause of "crunch")
        for w in (hc, hcontent):
            if w is None:
                continue
            w.setMinimumSize(0, 0)
            w.setMaximumSize(16777215, 16777215)  # Qt "no real max" sentinel
            w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

        # 3) Also force the scroll-area internal widget (usually scrollAreaWidgetContents)
        try:
            internal = hs.widget()
            if internal is not None:
                internal.setMinimumSize(0, 0)
                internal.setMaximumSize(16777215, 16777215)
                internal.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        except Exception:
            pass

    def _home_debug_crunch_snapshot(self, where: str):
        """
        Prints the exact widgets that matter for crunching.
        Send me this log after you run once.
        """
        print(f"\n[HOME][CRUNCH][SNAPSHOT] where={where}")
        hs = getattr(self, "homeScrollArea", None)
        vp = hs.viewport() if hs is not None else None
        self._dbg_geom("homeScrollArea", hs)
        self._dbg_geom("homeScrollArea.viewport", vp)
        self._dbg_geom("homeScrollContents", getattr(self, "homeScrollContents", None))
        self._dbg_geom("homeContent", getattr(self, "homeContent", None))

        # Useful: current scroll positions
        try:
            hbar = hs.horizontalScrollBar()
            vbar = hs.verticalScrollBar()
            print(f"[DBG][scrollbars] H={hbar.value()}/{hbar.maximum()} V={vbar.value()}/{vbar.maximum()}")
        except Exception:
            pass

    def _home_uncrunch_now(self, reason: str):
        """
        One function you can call safely multiple times:
        - forces expand policies
        - clamps any accidental minWidth islands
        - resets horizontal scroll to 0
        - prints one snapshot
        """
        self._home_force_expand_policies()

        hs = getattr(self, "homeScrollArea", None)
        if hs is not None:
            try:
                hs.horizontalScrollBar().setValue(0)
            except Exception:
                pass

        # If you have a center-lane width updater, run it AFTER forcing policies.
        if hasattr(self, "_home_update_center_lane_width"):
            try:
                self._home_update_center_lane_width()
            except Exception as e:
                print(f"[HOME][CRUNCH][WARN] _home_update_center_lane_width failed: {e}")

        self._home_debug_crunch_snapshot(where=reason)

    VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".m4v", ".mov", ".wmv", ".webm"}
    IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

    # ============================================================
    # VIEWPORT / LAYOUT DEBUG (one-shot, high-signal)
    # ============================================================

    def __init__(self, win: QMainWindow):
        super().__init__(win)

        self.win = win
        self.T = OmegaTuning()
        self.tuning = self.T  # legacy alias for older helper methods

        # ------------------------------------------------------------
        # Unified debug printer (so we can call self._dprint everywhere)
        # ------------------------------------------------------------
        self._dprint = dprint  # type: ignore[attr-defined]

        self._app_root = Path(__file__).resolve().parents[2]
        self._media_dir = self._app_root / "Media"
        self._shows_dir = self._media_dir / "Shows"
        self._cache_dir = self._media_dir / ".omega_cache"
        self._meta_cache_file = self._cache_dir / "metadata_cache.json"

        try:
            os.environ["PATH"] = str(self._app_root) + os.pathsep + os.environ.get("PATH", "")
        except Exception:
            pass

        dprint("PlayerController init.")
        dprint("[PATH] app_root:", self._app_root)
        dprint("[PATH] shows_dir:", self._shows_dir)

        self._library_file = self._media_dir / "library.json"
        self._library = LibraryManager()
        self._library.ensure_default_source()
        self._scanner = LibraryScanner(video_exts=self.VIDEO_EXTS)

        msg = migrate_sources_txt_to_library_json(self._media_dir / "sources.txt", self._library_file)
        if msg:
            dprint("[LIBRARY][MIGRATE]", msg)

        self._meta_cache = MetadataCache(self._meta_cache_file)
        self._meta_provider = MetadataProvider()

        self._thumbs = EpisodeThumbnailer(self._cache_dir, timestamp_sec=300)
        self._thumb_pump_timer = QTimer(self)
        self._thumb_pump_timer.setInterval(int(self.T.home.thumbs_pump_interval_ms))
        self._thumb_pump_timer.timeout.connect(self._thumbs_pump_done_queue)
        self._thumb_pump_timer.start()
        QTimer.singleShot(int(self.T.home.thumbs_initial_scan_delay_ms), self._thumbs_queue_missing_for_library)

        # Page wiring
        self.pages: QStackedWidget = safe_find(win, "pages", QStackedWidget, required=True)
        self.homePage: QWidget = safe_find(win, "homePage", QWidget, required=True)
        self.playerPage: QWidget = safe_find(win, "playerPage", QWidget, required=True)
        self.searchPage: QWidget = safe_find(win, "searchPage", QWidget, required=True)

        self.navHomeBtn: QPushButton = safe_find(win, "navHomeBtn", QPushButton, required=True)
        self.navSearchBtn: QPushButton = safe_find(win, "navSearchBtn", QPushButton, required=True)
        self.navPlayerBtn: QPushButton = safe_find(win, "navPlayerBtn", QPushButton, required=True)
        self._shell_wire_navigation()

        # Home module
        self._home_init_widgets()
        self._home_wire_tools_actions()
        self._home_apply_scroll_policies()

        # Release any giant fixed widths baked into Designer widgets
        def _unfix_width(w: Optional[QWidget], label: str) -> None:
            if w is None:
                return
            try:
                min_w = int(w.minimumWidth())
                max_w = int(w.maximumWidth())
                cur_w = int(w.width())
                if min_w == max_w and min_w >= 2000:
                    dprint(f"[LAYOUT][UNFIX] {label} had fixed width min=max={min_w}. Breaking it.")
                    w.setMinimumWidth(0)
                    w.setMaximumWidth(16777215)
                if min_w >= 2000:
                    dprint(f"[LAYOUT][UNFIX] {label} minWidth={min_w} too large. Resetting to 0.")
                    w.setMinimumWidth(0)
                w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
                w.updateGeometry()
                dprint(f"[LAYOUT][UNFIX] {label} now min={w.minimumWidth()} max={w.maximumWidth()} cur={cur_w}")
            except Exception as e:
                dprint(f"[LAYOUT][UNFIX][WARN] {label}:", e)

        _unfix_width(safe_find(self.win, "libraryRoot", QWidget, required=False), "libraryRoot")
        _unfix_width(safe_find(self.win, "libraryLeft", QWidget, required=False), "libraryLeft")
        _unfix_width(self.homeScrollArea, "homeScrollArea")
        _unfix_width(self.homeScrollContents, "homeScrollContents")

        # One-shot sanity clamp (in case Designer saved 10k x 10k geometries).
        try:
            self._layout_sanity_clamp_mega_geometries(where='init-post-unfix')
        except Exception:
            pass

        try:
            if self.homeScrollArea is not None:
                self.homeScrollArea.setWidgetResizable(True)
                self.homeScrollArea.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
                self.homeScrollArea.viewport().setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
                self.homeScrollArea.updateGeometry()
        except Exception:
            pass

        # Debounced responsive rebuild
        self._home_rail_shells: List[RailShell] = []
        self._home_last_profile: Optional[dict] = None
        self._home_resize_debounce = QTimer(self)
        self._home_resize_debounce.setSingleShot(True)
        self._home_resize_debounce.timeout.connect(self._home_rebuild_responsive_now)

        # Cache the last viewport size we reacted to. Prevents resize/rebuild feedback loops.
        self._home_last_viewport_size = (-1, -1)

        # Watch Home scroll viewport for resize events
        try:
            if self.homeScrollArea is not None:
                self.homeScrollArea.viewport().installEventFilter(self)
                self._home_install_best_scroll_routing()

                try:
                    wh = self.win.windowHandle()
                    if wh is not None:
                        def _on_screen_changed(*_args):
                            self._home_update_center_lane_width()
                            self._home_on_viewport_resized()

                        wh.screenChanged.connect(_on_screen_changed)
                except Exception:
                    pass
        except Exception:
            pass

        # Player module
        self._player_init_widgets()
        self._player_init_backend_or_warn()
        self._player_wire_controls()

        try:
            setattr(self.win, "play_path", self.play_path)
        except Exception:
            pass

        dprint("PlayerController initialized.")

        # Single post-show layout pass — fires after Qt has shown the window
        QTimer.singleShot(0, self._home_rebuild_responsive_now)

    # ============================================================
    # SHELL: navigation
    # ============================================================

    def _shell_wire_navigation(self) -> None:
        def go(page: QWidget) -> None:
            try:
                self.pages.setCurrentWidget(page)
            except Exception as e:
                dprint("[NAV][WARN] Could not switch page:", e)

        self.navHomeBtn.clicked.connect(lambda: go(self.homePage))
        self.navSearchBtn.clicked.connect(lambda: go(self.searchPage))
        self.navPlayerBtn.clicked.connect(lambda: go(self.playerPage))

    # ============================================================
    # Home "best-app" scrolling + resize rebuild (UNIFIED eventFilter)
    # ============================================================
    # ============================================================
    # Home resize rebuild + wheel policy
    # ============================================================
    def _home_register_wheel_blocker(self, maybe_scrollarea: object) -> None:
        """
        Register a horizontal rail's QScrollArea so wheel input does NOT scroll it.
        If the rail ignores wheel events, Qt will pass the wheel to the parent
        (the Home vertical scroll area), which is exactly what we want.
        """
        if maybe_scrollarea is None:
            return

        # Only real QScrollArea instances have viewport()
        if not hasattr(maybe_scrollarea, "viewport"):
            return

        if not hasattr(self, "_home_wheel_blockers"):
            self._home_wheel_blockers = set()

        self._home_wheel_blockers.add(maybe_scrollarea)
        try:
            maybe_scrollarea.installEventFilter(self)
        except Exception:
            pass
        try:
            maybe_scrollarea.viewport().installEventFilter(self)
        except Exception:
            pass

    def _home_is_wheel_blocker_obj(self, obj: object) -> bool:
        """
        True if obj is one of our registered rail QScrollAreas or their viewports.
        """
        blockers = getattr(self, "_home_wheel_blockers", None)
        if not blockers:
            return False

        for sa in blockers:
            if obj is sa:
                return True
            try:
                if obj is sa.viewport():
                    return True
            except Exception:
                pass

        return False

    # ============================================================
    # EVENT FILTER (single unified implementation)
    # - Resize: triggers responsive rebuild
    # - Wheel: routes wheel to horizontal rails ONLY when cursor is over a RailShell
    #          otherwise lets the Home QScrollArea do NORMAL vertical scrolling
    # ============================================================
    def eventFilter(self, obj, event):
        try:
            # ------------------------------------------------------------
            # HOME viewport wheel routing (critical: do NOT swallow all wheel)
            # ------------------------------------------------------------
            if self.homeScrollArea is not None and obj is self.homeScrollArea.viewport():
                et = event.type()

                # -------------------------
                # 1) RESIZE -> responsive
                # -------------------------
                if et == QEvent.Resize:
                    # Keep the Home viewport width pinned to the actual window/layout (prevents 10k+ widths)
                    self._home_lock_viewport_to_window("eventFilter.Resize")
                    vw = int(self.homeScrollArea.viewport().width())
                    vh = int(self.homeScrollArea.viewport().height())

                    # Prevent feedback loops: only react when the *viewport size* actually changes.
                    last = getattr(self, "_home_last_viewport_size", (-1, -1))
                    cur = (vw, vh)
                    if cur == last:
                        return False
                    self._home_last_viewport_size = cur

                    self._dprint(f"[EVT][HOME_VIEWPORT][RESIZE] vw={vw} vh={vh} obj={obj.objectName()}")

                    # Debounced responsive rebuild (correct method name)
                    if hasattr(self, "_home_on_viewport_resized"):
                        self._home_on_viewport_resized()
                    else:
                        # fallback: if you renamed it later
                        if hasattr(self, "_home_rebuild_responsive_debounced"):
                            self._home_rebuild_responsive_debounced()

                # -------------------------
                # 2) WHEEL -> route to rail only if cursor is actually over a RailShell
                # -------------------------
                if et == QEvent.Wheel:
                    # Global cursor position -> widgetAt -> climb parents to find RailShell
                    try:
                        from PySide6.QtWidgets import QApplication
                        gp = event.globalPosition().toPoint()  # Qt6: QPoint
                        w = QApplication.widgetAt(gp)
                    except Exception:
                        w = None

                    dy = event.angleDelta().y()
                    dx = event.angleDelta().x()

                    # Debug the wheel BEFORE deciding what to do
                    wname = getattr(w, "objectName", lambda: "")()
                    wcls = type(w).__name__ if w is not None else "None"
                    self._dprint(f"[EVT][HOME_VIEWPORT][WHEEL] dx={dx} dy={dy} under={wcls}:{wname}")

                    # Walk up parents to find a RailShell instance
                    rail = None
                    p = w
                    hop = 0
                    while p is not None and hop < 25:
                        if type(p).__name__ == "RailShell":
                            rail = p
                            break
                        p = p.parentWidget()
                        hop += 1

                    # If we found a rail under the cursor: consume and route horizontally
                    if rail is not None:
                        self._dprint(
                            f"[EVT][HOME_VIEWPORT][WHEEL] ROUTE -> RailShell id={getattr(rail, 'rail_id', 'unknown')}")
                        try:
                            # RailShell should already support wheel; if not, just pass event to its scroll area
                            if hasattr(rail, "handle_wheel"):
                                rail.handle_wheel(event)
                            else:
                                # Fallback: push horizontal scroll directly
                                sc = getattr(rail, "sc", None)
                                if sc is not None and sc.horizontalScrollBar() is not None:
                                    sb = sc.horizontalScrollBar()
                                    step = int(abs(dy) / 120) * 80
                                    if dy < 0:
                                        sb.setValue(sb.value() + step)
                                    else:
                                        sb.setValue(sb.value() - step)
                        except Exception as e:
                            self._dprint(f"[EVT][HOME_VIEWPORT][WHEEL][ERR] rail route failed: {e}")
                        return True  # we handled it; do NOT let vertical scroll happen in this case

                    # Otherwise: DO NOT CONSUME THE WHEEL.
                    # Let the QScrollArea do normal vertical scrolling.
                    self._dprint("[EVT][HOME_VIEWPORT][WHEEL] PASS -> QScrollArea vertical scroll")
                    return False

            return super().eventFilter(obj, event)

        except Exception as e:
            # Never break event loop—log and fall through
            try:
                self._dprint(f"[EVT][ERR] eventFilter exception: {e}")
            except Exception:
                pass
            return super().eventFilter(obj, event)

    # ============================================================
    # HOME: bottom chevron test button (page-down)
    # ============================================================
    def _home_install_page_down_button(self) -> None:
        """
        Debug/test: add a bottom chevron that scrolls the Home page down when clicked.
        This proves whether vertical scrolling is possible (i.e., scrollbar max > 0).
        """
        if getattr(self, "homeScrollArea", None) is None:
            return

        # Create once
        if getattr(self, "_home_page_down_btn", None) is None:
            btn = QToolButton(self.homeScrollArea.viewport())
            btn.setObjectName("homePageDownBtn")
            btn.setText("▼")  # plain chevron glyph
            btn.setAutoRaise(True)
            btn.setCursor(Qt.PointingHandCursor)

            # Keep it subtle and clickable
            btn.setStyleSheet("""
                QToolButton#homePageDownBtn {
                    background: rgba(0,0,0,140);
                    border: 1px solid rgba(255,255,255,60);
                    border-radius: 18px;
                    padding: 8px 12px;
                    color: white;
                    font-size: 18px;
                }
                QToolButton#homePageDownBtn:hover {
                    background: rgba(0,0,0,190);
                    border: 1px solid rgba(255,255,255,110);
                }
            """)

            btn.clicked.connect(self._home_page_down_click)
            btn.show()

            self._home_page_down_btn = btn

        # Position now
        self._home_position_page_down_button()

    # ============================================================
    # SCROLL DEBUG: print viewport + content sizes and scrollbar ranges
    # ============================================================
    def _dbg_home_scroll_state(self, tag=""):
        try:
            if self.homeScrollArea is None:
                self._dprint(f"[DBG][SCROLL]{tag} homeScrollArea=None")
                return

            vp = self.homeScrollArea.viewport()
            vp_w = vp.width()
            vp_h = vp.height()

            w = self.homeScrollArea.widget()  # should be homeScrollContents
            wn = w.objectName() if w is not None else "None"
            wc = type(w).__name__ if w is not None else "None"

            vbar = self.homeScrollArea.verticalScrollBar()
            hbar = self.homeScrollArea.horizontalScrollBar()

            self._dprint(
                f"[DBG][SCROLL]{tag} viewport={vp_w}x{vp_h} widget={wc}:{wn} "
                f"vbar(range={vbar.minimum()}..{vbar.maximum()} val={vbar.value()}) "
                f"hbar(range={hbar.minimum()}..{hbar.maximum()} val={hbar.value()})"
            )

            # Also: if we can see homeContent, report its sizeHint/geo
            if getattr(self, "homeContent", None) is not None:
                hc = self.homeContent
                g = hc.geometry()
                sh = hc.sizeHint()
                self._dprint(
                    f"[DBG][SCROLL]{tag} homeContent geo=({g.x()},{g.y()},{g.width()}x{g.height()}) "
                    f"sizeHint=({sh.width()}x{sh.height()})"
                )

            # ============================================================
            # CRITICAL: Make scroll content compute real height (allow vertical scroll)
            # ============================================================
            try:
                if self.homeScrollContents is not None:
                    self.homeScrollContents.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
                    self._dprint("[HOME][SCROLL] homeScrollContents policy -> Expanding/Minimum")

                if getattr(self, "homeContent", None) is not None:
                    self.homeContent.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
                    self._dprint("[HOME][SCROLL] homeContent policy -> Expanding/Minimum")

                if self.homeScrollArea is not None:
                    self.homeScrollArea.setWidgetResizable(True)
                    self.homeScrollArea.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
                    self.homeScrollArea.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                    self._dprint("[HOME][SCROLL] homeScrollArea resizable=True vbar=AsNeeded hbar=Off")
            except Exception as e:
                self._dprint(f"[HOME][SCROLL][ERR] policy setup failed: {e}")

        except Exception as e:
            self._dprint(f"[DBG][SCROLL]{tag}[ERR] {e}")

    def _home_position_page_down_button(self) -> None:
        """
        Keep the chevron pinned to the bottom-center of the Home viewport.
        """
        btn = getattr(self, "_home_page_down_btn", None)
        if btn is None:
            return
        if getattr(self, "homeScrollArea", None) is None:
            return

        vp = self.homeScrollArea.viewport()
        vw = vp.width()
        vh = vp.height()

        # Button size (use sizeHint so style/padding are respected)
        sh = btn.sizeHint()
        bw = sh.width()
        bh = sh.height()

        margin_bottom = 18
        x = max(0, (vw - bw) // 2)
        y = max(0, vh - bh - margin_bottom)

        btn.setGeometry(x, y, bw, bh)
        btn.raise_()

    def _home_page_down_click(self) -> None:
        """
        Scroll down by ~80% of the viewport height.
        Also prints scrollbar range so we can confirm if scrolling is even possible.
        """
        if getattr(self, "homeScrollArea", None) is None:
            return

        vbar = self.homeScrollArea.verticalScrollBar()
        vp_h = self.homeScrollArea.viewport().height()

        # Debug: prove whether scrolling is possible
        try:
            dprint(
                f"[SCROLL][TEST] vbar range: min={vbar.minimum()} max={vbar.maximum()} cur={vbar.value()} vp_h={vp_h}")
        except Exception:
            pass

        step = int(max(120, vp_h * 0.80))
        vbar.setValue(min(vbar.maximum(), vbar.value() + step))

    # ============================================================
    # HOME: clamp oversized widgets to real window width
    # ============================================================

    def _home_force_clamp_to_window_width(self):
        from PySide6.QtWidgets import QSplitter

        cw = None
        try:
            cw = self.win.centralWidget()
        except Exception:
            pass

        win_w = self.win.width()
        cw_w = cw.width() if cw is not None else win_w
        if cw_w <= 0:
            cw_w = win_w
        if cw_w <= 0:
            cw_w = 1800

        dprint(f"[CLAMP] win_w={win_w} cw_w={cw_w}")

        try:
            splitters = self.win.findChildren(QSplitter)
        except Exception:
            splitters = []

        for i, sp in enumerate(splitters):
            try:
                sizes = sp.sizes()

                # ------------------------------------------------------------
                # HOME EDGE-TO-EDGE SNAP (fixes the "mystery vertical line")
                #
                # If the Home view lives inside a QSplitter (e.g. left pane + right pane),
                # and the splitter's *other* pane is empty/hidden, Qt will still reserve
                # width for it. The visible symptom is exactly what you drew:
                #   - content stops at a vertical boundary
                #   - everything to the right is "dead" empty space
                # That boundary is the QSplitter handle / pane edge.
                #
                # For Home, we want the scroll area viewport to consume 100% of the width.
                # ------------------------------------------------------------
                try:
                    home_sa = getattr(self, "homeScrollArea", None)
                    if home_sa is not None:
                        def _contains(child: QWidget, target: QWidget) -> bool:
                            return (child is target) or (hasattr(child, "isAncestorOf") and child.isAncestorOf(target))

                        idx_home = -1
                        for k in range(sp.count()):
                            w = sp.widget(k)
                            if w is not None and _contains(w, home_sa):
                                idx_home = k
                                break

                        # Only handle the common 2-pane splitter case.
                        if idx_home != -1 and sp.count() == 2:
                            other = 1 - idx_home

                            # Hide/collapse the other pane so it can't steal width.
                            try:
                                sp.setCollapsible(other, True)
                                sp.widget(other).setVisible(False)
                            except Exception:
                                pass

                            # Kill the handle so no divider line is visible.
                            try:
                                sp.setHandleWidth(0)
                            except Exception:
                                pass

                            # Give essentially ALL width to Home.
                            sizes_new = [0, 0]
                            sizes_new[idx_home] = max(1, cw_w)
                            sizes_new[other] = 0
                            sp.setSizes(sizes_new)
                            dprint(f"[HOME][SNAP] splitter#{i} sizes {sizes} -> {sizes_new}")
                            continue
                except Exception:
                    pass

                # Default clamp for "exploded" splitters elsewhere in the app.
                if any(s > cw_w * 2 for s in sizes) or sum(sizes) > cw_w * 2:
                    left = max(280, int(cw_w * 0.22))
                    right = max(280, cw_w - left)
                    sp.setSizes([left, right])
                    dprint(f"[CLAMP][SPLITTER#{i}] normalized sizes {sizes} -> {[left, right]}")
            except Exception as e:
                dprint(f"[CLAMP][SPLITTER#{i}][WARN] {e}")

        chain = [
            ("libraryRoot", getattr(self, "libraryRoot", None)),
            ("libraryLeft", getattr(self, "libraryLeft", None)),
            ("homeScrollArea", getattr(self, "homeScrollArea", None)),
            ("homeScrollContents", getattr(self, "homeScrollContents", None)),
        ]
        for name, w in chain:
            if w is None:
                continue
            try:
                w.setMinimumWidth(0)
                w.setMaximumWidth(16777215)
                w.updateGeometry()
                dprint(f"[CLAMP][{name}] reset constraints curW={w.width()}")
            except Exception as e:
                dprint(f"[CLAMP][{name}][WARN] {e}")

        try:
            if getattr(self, "homeScrollArea", None) is not None and self.homeScrollArea.viewport() is not None:
                dprint(f"[CLAMP][VERIFY] homeScrollArea.viewport w={self.homeScrollArea.viewport().width()}")
        except Exception:
            pass

    def _clamp_widget_max_width(self, w: QWidget, max_w: int, tag: str = "") -> None:
        """Hard-cap a widget's width WITHOUT collapsing layout trees."""
        try:
            max_w = max(1, int(max_w))
            # If the widget already has a huge *minimum*, maximumWidth alone won't help.
            if w.minimumWidth() > max_w:
                dprint(f"[LAYOUT][CLAMP] {tag}{w.objectName()} minimumWidth {w.minimumWidth()} -> {max_w}")
                w.setMinimumWidth(max_w)

            if w.maximumWidth() != max_w:
                dprint(f"[LAYOUT][CLAMP] {tag}{w.objectName()} maximumWidth {w.maximumWidth()} -> {max_w}")
                w.setMaximumWidth(max_w)

            if w.width() > max_w:
                dprint(f"[LAYOUT][CLAMP] {tag}{w.objectName()} width {w.width()} -> {max_w}")
                w.resize(max_w, w.height())
        except Exception as e:
            dprint(f"[LAYOUT][CLAMP][WARN] width clamp failed for {getattr(w, 'objectName', lambda: '?')()}: {e}")

    def _clamp_widget_max_height(self, w: QWidget, max_h: int, tag: str = "") -> None:
        """Hard-cap a widget's height WITHOUT collapsing layout trees."""
        try:
            max_h = max(1, int(max_h))
            if w.minimumHeight() > max_h:
                dprint(f"[LAYOUT][CLAMP] {tag}{w.objectName()} minimumHeight {w.minimumHeight()} -> {max_h}")
                w.setMinimumHeight(max_h)

            if w.maximumHeight() != max_h:
                dprint(f"[LAYOUT][CLAMP] {tag}{w.objectName()} maximumHeight {w.maximumHeight()} -> {max_h}")
                w.setMaximumHeight(max_h)

            if w.height() > max_h:
                dprint(f"[LAYOUT][CLAMP] {tag}{w.objectName()} height {w.height()} -> {max_h}")
                w.resize(w.width(), max_h)
        except Exception as e:
            dprint(f"[LAYOUT][CLAMP][WARN] height clamp failed for {getattr(w, 'objectName', lambda: '?')()}: {e}")

    # ============================================================
    # HOME VIEWPORT LOCK (critical)
    # Ensures the Home scroll viewport width tracks the real window/layout
    # and prevents designer-fixed / accidental 10,000px+ widths.
    # ============================================================
    def _home_lock_viewport_to_window(self, reason: str = "") -> None:
        """
        Hard-reset width constraints on the Home container chain so the QScrollArea viewport
        stays pinned to the window and layouts can do their job.

        This is intentionally repetitive: Qt Designer can leave min/max widths behind,
        and one bad minWidth on a parent will explode the whole chain (what you were seeing
        as ~10000 width on small screens).
        """
        try:
            # Resolve key widgets defensively (works even if attributes weren’t cached)
            win = getattr(self, "win", None) or getattr(self, "MainWindow", None) or self
            cw = None
            try:
                if hasattr(win, "centralWidget"):
                    cw = win.centralWidget()
            except Exception:
                cw = None

            libraryRoot = getattr(self, "libraryRoot", None) or (win.findChild(QWidget, "libraryRoot") if win else None)
            libraryLeft = getattr(self, "libraryLeft", None) or (win.findChild(QWidget, "libraryLeft") if win else None)
            homeScrollArea = getattr(self, "homeScrollArea", None) or (
                win.findChild(QScrollArea, "homeScrollArea") if win else None)
            viewport = None
            try:
                viewport = homeScrollArea.viewport() if homeScrollArea else None
            except Exception:
                viewport = None

            # A helper that strips fixed/min/max widths and forces Expanding horizontal policy
            def _unlock_width(w: QWidget, label: str) -> None:
                if w is None:
                    return
                try:
                    sp = w.sizePolicy()
                    before = (
                    w.width(), w.minimumWidth(), w.maximumWidth(), int(sp.horizontalPolicy()), int(sp.verticalPolicy()))
                    # Kill any fixed widths / leftover designer constraints
                    w.setMinimumWidth(0)
                    w.setMaximumWidth(16777215)

                    # Most containers should expand horizontally and participate in layouts
                    w.setSizePolicy(QSizePolicy.Expanding, sp.verticalPolicy())
                    w.updateGeometry()

                    sp2 = w.sizePolicy()
                    after = (w.width(), w.minimumWidth(), w.maximumWidth(), int(sp2.horizontalPolicy()),
                             int(sp2.verticalPolicy()))
                    dprint(f"[LOCK][{reason}] {label} before(w,min,max,hp,vp)={before} -> after={after}")
                except Exception as e:
                    dprint(f"[LOCK][{reason}][WARN] Failed to unlock {label}: {e}")

            _unlock_width(cw, "centralWidget")
            _unlock_width(libraryRoot, "libraryRoot")
            _unlock_width(libraryLeft, "libraryLeft")
            _unlock_width(homeScrollArea, "homeScrollArea")
            _unlock_width(viewport, "homeScrollArea.viewport")

            # Extra: scroll areas must be resizable; viewport must be allowed to expand
            if homeScrollArea is not None:
                try:
                    homeScrollArea.setWidgetResizable(True)
                    homeScrollArea.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                    homeScrollArea.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
                except Exception:
                    pass

            # Sanity debug: if viewport is still absurdly wide, yell loudly
            try:
                ref_w = (cw.width() if cw else (win.width() if win else 0)) or 0
                vp_w = viewport.width() if viewport else 0
                if ref_w > 0 and vp_w > int(ref_w * 1.35):
                    dprint(
                        f"[LOCK][{reason}][WARN] viewport wider than window ref: viewport={vp_w} ref={ref_w} (check Designer minWidth/fixedWidth)")
            except Exception:
                pass

        except Exception as e:
            dprint(f"[LOCK][{reason}][WARN] _home_lock_viewport_to_window failed: {e}")

    def _layout_sanity_clamp_mega_geometries(self):
        """If any root widgets accidentally end up 10k pixels wide, clamp them.

        This is a defensive "seatbelt" for cases where a minWidth or fixed width
        was set (often by Qt Designer) and then propagated upward.

        Goal: prevent the Home / Library root chain from ballooning off-screen.
        """
        try:
            if not getattr(self.tuning.home, "debug_uncrunch", False):
                return

            # We clamp relative to the *actual* viewport width of the Home scroll area
            # (never desktop geometry).
            vw = None
            try:
                if self.homeScrollArea is not None:
                    vw = int(self.homeScrollArea.viewport().width())
            except Exception:
                vw = None

            if not vw or vw <= 0:
                # Fallback to centralWidget width if viewport is not ready yet.
                try:
                    vw = int(self.centralWidget.width())
                except Exception:
                    vw = 1200

            # Allow some headroom so layouts can breathe, but never explode to 10k.
            hard_cap_w = max(800, int(vw * 1.15))
            hard_cap_h = 20000  # height explosions are less common; keep generous.

            # Collect the usual suspects in the Home/Library geometry chain.
            offenders: List[QWidget] = []
            for name in [
                "centralWidget",
                "libraryRoot",
                "libraryLeft",
                "homeScrollArea",
                "scrollAreaWidgetContents",  # inside homeScrollArea
                "homeScrollContents",
            ]:
                try:
                    w = getattr(self, name, None)
                    if isinstance(w, QWidget):
                        offenders.append(w)
                except Exception:
                    pass

            # Also clamp the scroll-area *viewport* itself; it can inherit a max/min.
            try:
                if self.homeScrollArea is not None:
                    vp = self.homeScrollArea.viewport()
                    if isinstance(vp, QWidget):
                        offenders.append(vp)
            except Exception:
                pass

            # Apply clamps when widgets exceed our sane cap (or have absurd minimums).
            for w in offenders:
                try:
                    if w.width() > hard_cap_w or w.minimumWidth() > hard_cap_w or w.maximumWidth() > hard_cap_w * 4:
                        self._clamp_widget_max_width(w, hard_cap_w, tag="[ROOT] ")
                    if w.height() > hard_cap_h:
                        self._clamp_widget_max_height(w, hard_cap_h, tag="[ROOT] ")
                except Exception:
                    pass

        except Exception as e:
            dprint(f"[LAYOUT][CLAMP][WARN] _layout_sanity_clamp_mega_geometries failed: {e}")

    def _home_setup_center_lane(self) -> None:
        dprint("[DEBUG][CENTER_LANE] Starting setup_center_lane")

        if self.homeScrollContents is None:
            dprint("[DEBUG][CENTER_LANE] homeScrollContents None - abort")
            return
        if getattr(self, "homeContent", None) is None or self.homeContent is None:
            dprint("[DEBUG][CENTER_LANE] homeContent None - abort")
            return

        dprint("[DEBUG][CENTER_LANE] Pre-lay geo: homeScrollContents=", self.homeScrollContents.geometry(),
               " policy=", self.homeScrollContents.sizePolicy())

        lay = self.homeScrollContents.layout()
        if lay is None or not isinstance(lay, QHBoxLayout):
            dprint("[DEBUG][CENTER_LANE] Creating new HBox for homeScrollContents")
            lay = QHBoxLayout(self.homeScrollContents)
            self.homeScrollContents.setLayout(lay)

        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        dprint("[DEBUG][CENTER_LANE] Lay margins/spacing reset")

        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                dprint("[DEBUG][CENTER_LANE] Detaching widget:", w.objectName())
                w.setParent(None)
        # --------------------------------------------------------
        # EDGE-TO-EDGE MODE:
        #   homeScrollContents layout becomes ONLY [homeContent]
        #   no left/right/fill spacers, no centered lane math.
        # --------------------------------------------------------
        if bool(getattr(self.T.home, "edge_to_edge", False)):
            dprint("[DEBUG][CENTER_LANE] Edge-to-edge ON: using homeContent only (no spacers).")

            try:
                # Let homeContent expand to fill the viewport width naturally.
                self.homeContent.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
                self.homeContent.setMinimumWidth(0)
                self.homeContent.setMaximumWidth(16777215)
            except Exception as e:
                dprint("[DEBUG][CENTER_LANE] Edge-to-edge homeContent policy error:", e)

            lay.addWidget(self.homeContent)
            dprint("[DEBUG][CENTER_LANE] Added homeContent (edge-to-edge)")

            # Still run the width updater once (it will early-exit in edge-to-edge mode)
            self._home_update_center_lane_width()

            try:
                lay.activate()
                self.homeScrollContents.updateGeometry()
                dprint("[DEBUG][CENTER_LANE] Edge-to-edge layout activated")
            except Exception as e:
                dprint("[DEBUG][CENTER_LANE] Edge-to-edge activate error:", e)

            return

        self._home_lane_left = QWidget(self.homeScrollContents)
        self._home_lane_left.setObjectName("homeLaneLeftSpacer")
        self._home_lane_left.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Minimum)
        self._home_lane_left.setFixedWidth(0)
        dprint("[DEBUG][CENTER_LANE] Created left spacer")

        self._home_lane_right = QWidget(self.homeScrollContents)
        self._home_lane_right.setObjectName("homeLaneRightSpacer")
        self._home_lane_right.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Minimum)
        self._home_lane_right.setFixedWidth(0)
        dprint("[DEBUG][CENTER_LANE] Created right spacer")

        # Soaks any extra width if scroll contents is incorrectly huge
        self._home_lane_fill = QWidget(self.homeScrollContents)
        self._home_lane_fill.setObjectName("homeLaneFillSpacer")
        self._home_lane_fill.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        dprint("[DEBUG][CENTER_LANE] Created fill spacer")

        try:
            self.homeContent.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
            self.homeContent.setMinimumHeight(0)
            self.homeContent.setMaximumHeight(16777215)
            dprint("[DEBUG][CENTER_LANE] homeContent policy set to Fixed horiz + Expanding vert")
        except Exception as e:
            dprint("[DEBUG][CENTER_LANE] homeContent policy error:", e)

        lay.addWidget(self._home_lane_left)
        dprint("[DEBUG][CENTER_LANE] Added left spacer to lay")
        lay.addWidget(self.homeContent)
        dprint("[DEBUG][CENTER_LANE] Added homeContent to lay")
        lay.addWidget(self._home_lane_right)
        dprint("[DEBUG][CENTER_LANE] Added right spacer to lay")
        lay.addWidget(self._home_lane_fill)
        dprint("[DEBUG][CENTER_LANE] Added fill spacer to lay")

        try:
            dprint(f"[DEBUG][CENTER_LANE] Lay type={type(lay).__name__} count={lay.count()}")
            for i in range(lay.count()):
                it = lay.itemAt(i)
                ww = it.widget() if it else None
                dprint(
                    f"[DEBUG][CENTER_LANE] i={i} widget={(ww.objectName() if ww else None)} geo={(ww.geometry() if ww else 'None')}")
        except Exception as e:
            dprint("[DEBUG][CENTER_LANE] Lay debug error:", e)

        self._home_update_center_lane_width()

        try:
            lay.activate()
            dprint("[DEBUG][CENTER_LANE] Lay activated")
            self.homeScrollContents.layout().activate()
            dprint("[DEBUG][CENTER_LANE] homeScrollContents lay activated")
            self.homeScrollContents.updateGeometry()
            dprint("[DEBUG][CENTER_LANE] homeScrollContents updateGeometry called")
            self.homeScrollContents.adjustSize()
            dprint("[DEBUG][CENTER_LANE] homeScrollContents adjustSize called, new geo=",
                   self.homeScrollContents.geometry())
        except Exception as e:
            dprint("[DEBUG][CENTER_LANE] Force recompute error:", e)

    def _home_update_center_lane_width(self) -> None:
        """
        Keeps Home from going "10,000px wide" and causing black/dead space.

        - If edge_to_edge is ON: do NOT set a huge minimum width.
          Let Qt naturally size it to the viewport (Expanding policy).
        - If edge_to_edge is OFF: use the centered-lane spacers and a fixed content width.
        """
        try:
            if self.homeScrollArea is None or self.homeContent is None:
                return

            vw = int(self.homeScrollArea.viewport().width())
            if vw <= 0:
                return

            # ------------------------------------------------------------
            # EDGE-TO-EDGE MODE (your current mode)
            # ------------------------------------------------------------
            if bool(getattr(self.T.home, "edge_to_edge", False)):
                inset = int(getattr(self.T.home, "edge_safe_inset_px", 0))
                inset = max(0, inset)

                # IMPORTANT: do NOT force homeContent minWidth to vw/usable
                # That is what caused the 9984/10000px explosion.
                self.homeContent.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
                self.homeContent.setMinimumWidth(0)
                self.homeContent.setMaximumWidth(16777215)

                # If you want a tiny inset, apply it as layout margins instead of minWidth.
                try:
                    lay = self.homeScrollContents.layout() if self.homeScrollContents is not None else None
                    if isinstance(lay, QHBoxLayout):
                        lay.setContentsMargins(inset, 0, inset, 0)
                        lay.setSpacing(0)
                except Exception:
                    pass

                try:
                    dprint(f"[HOME][LANE][E2E] vw={vw} inset={inset} homeContentW={self.homeContent.width()}")
                except Exception:
                    pass
                return

            # ------------------------------------------------------------
            # CENTERED-LANE MODE (only if you later turn edge_to_edge OFF)
            # ------------------------------------------------------------
            gutter_ratio = float(getattr(self.T.home, "center_lane_gutter_ratio", 0.0))
            gutter_min = int(getattr(self.T.home, "center_lane_gutter_min_px", 0))
            gutter_max = int(getattr(self.T.home, "center_lane_gutter_max_px", 0))
            max_lane = int(getattr(self.T.home, "center_lane_max_width_px", 10000))

            gutter = int(vw * gutter_ratio)
            gutter = max(gutter_min, min(gutter_max, gutter))

            target_w = max(1, vw - (2 * gutter))
            target_w = min(target_w, max_lane)

            # homeContent fixed width when boxed/centered
            self.homeContent.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
            self.homeContent.setMinimumWidth(target_w)
            self.homeContent.setMaximumWidth(target_w)

            # Adjust spacer widths if they exist
            try:
                extra = max(0, vw - target_w)
                left = extra // 2
                right = extra - left

                if hasattr(self, "_home_lane_left") and self._home_lane_left is not None:
                    self._home_lane_left.setFixedWidth(int(left))
                if hasattr(self, "_home_lane_right") and self._home_lane_right is not None:
                    self._home_lane_right.setFixedWidth(int(right))
            except Exception:
                pass

            try:
                dprint(
                    f"[HOME][LANE][CENTER] vw={vw} gutter={gutter} target_w={target_w} homeContentW={self.homeContent.width()}")
            except Exception:
                pass

        except Exception as e:
            try:
                dprint(f"[HOME][LANE][WARN] update failed: {e}")
            except Exception:
                pass

    # ============================================================
    # PLAYER MODULE: widgets + backend + controls
    # ============================================================

    def _player_init_widgets(self) -> None:
        self.videoFrame: Optional[QFrame] = safe_find(self.win, "videoFrame", QFrame, required=False)
        self.videoHost: Optional[QWidget] = safe_find(self.win, "videoHost", QWidget, required=False)
        self.playerControlsBar: Optional[QWidget] = safe_find(self.win, "playerControlsBar", QWidget, required=False)
        self.playerBackBtn: Optional[QPushButton] = safe_find(self.win, "playerBackBtn", QPushButton, required=False)
        self.playerPrevBtn: Optional[QPushButton] = safe_find(self.win, "playerPrevBtn", QPushButton, required=False)
        self.playerPlayPauseBtn: Optional[QPushButton] = safe_find(self.win, "playerPlayPauseBtn", QPushButton,
                                                                   required=False)
        self.playerFwdBtn: Optional[QPushButton] = safe_find(self.win, "playerFwdBtn", QPushButton, required=False)
        self.playerNextBtn: Optional[QPushButton] = safe_find(self.win, "playerNextBtn", QPushButton, required=False)
        self.playerStopBtn: Optional[QPushButton] = safe_find(self.win, "playerStopBtn", QPushButton, required=False)
        self.playerMuteBtn: Optional[QPushButton] = safe_find(self.win, "playerMuteBtn", QPushButton, required=False)
        self.playerCloseBtn: Optional[QPushButton] = safe_find(self.win, "playerCloseBtn", QPushButton, required=False)
        self.playerFullscreenBtn: Optional[QPushButton] = safe_find(self.win, "playerFullscreenBtn", QPushButton,
                                                                    required=False)
        self.playerSeekSlider: Optional[QSlider] = safe_find(self.win, "playerSeekSlider", QSlider, required=False)
        self.playerTimeLabel: Optional[QLabel] = safe_find(self.win, "playerTimeLabel", QLabel, required=False)
        self.playerVolumeSlider: Optional[QSlider] = safe_find(self.win, "playerVolumeSlider", QSlider, required=False)

        self._mpv: Optional[MPVBackend] = None
        self._current_path: Optional[Path] = None
        self._muted: bool = False
        self._slider_dragging = False
        self._mpv_time_unit: Optional[str] = None
        self._pending_seek_ratio: Optional[float] = None
        self._seek_lock_active = False
        self._seek_lock_target_ms = 0

        self._seek_lock_timer = QTimer(self.win)
        self._seek_lock_timer.setSingleShot(True)
        self._seek_lock_timer.timeout.connect(self._player_release_seek_lock)

        self._ui_timer = QTimer(self)
        self._ui_timer.setInterval(int(self.T.player.ui_tick_interval_ms))
        self._ui_timer.timeout.connect(self._player_tick_ui)

    def _player_init_backend_or_warn(self) -> None:
        if self.videoHost is None:
            dprint("[PLAYER][WARN] videoHost not found. Skipping MPV embed.")
            return

        try:
            if self.videoFrame is not None:
                self.videoFrame.setStyleSheet("background: black;")
            self.videoHost.setStyleSheet("background: black;")
        except Exception:
            pass

        try:
            self._mpv = MPVBackend()
        except Exception as e:
            dprint("[PLAYER][ERROR] MPV init failed:", e)
            QMessageBox.critical(
                self.win,
                "MPV Playback Unavailable",
                "MPV could not be initialized.\n\n"
                f"Details:\n{type(e).__name__}: {e}\n\n"
                "Fix:\n"
                "1) pip install python-mpv\n"
                "2) Ensure libmpv-2.dll is available\n"
                "   - Put MPV folder on PATH, OR\n"
                "   - Put libmpv-2.dll next to your app root\n",
            )
            self._mpv = None
            return

        QTimer.singleShot(0, self._player_attach_to_video_host)
        self._ui_timer.start()

    def _player_attach_to_video_host(self) -> None:
        if self._mpv is None or self.videoHost is None:
            return
        try:
            self.videoHost.setAttribute(Qt.WA_NativeWindow, True)
            self.videoHost.setAttribute(Qt.WA_DontCreateNativeAncestors, True)
            self.videoHost.setAttribute(Qt.WA_OpaquePaintEvent, True)
            self.videoHost.show()
            wid = int(self.videoHost.winId())
            self._mpv.set_wid(wid)
            dprint(f"[PLAYER] MPV attached to videoHost winId={wid}")
        except Exception as e:
            dprint("[PLAYER][ERROR] Failed to attach MPV:", e)

    def _player_wire_controls(self) -> None:
        if self.playerSeekSlider is not None:
            try:
                self.playerSeekSlider.setRange(0, int(self.T.player.seek_slider_max))
                self.playerSeekSlider.setTracking(True)
                self.playerSeekSlider.setSingleStep(1)
                self.playerSeekSlider.setPageStep(int(self.T.player.seek_slider_page_step))
            except Exception:
                pass
            self.playerSeekSlider.sliderPressed.connect(self._player_on_seek_pressed)
            self.playerSeekSlider.sliderReleased.connect(self._player_on_seek_released)
            self.playerSeekSlider.actionTriggered.connect(self._player_on_seek_action_triggered)

        if self.playerVolumeSlider is not None:
            try:
                self.playerVolumeSlider.setRange(0, 100)
            except Exception:
                pass
            if self._mpv is not None:
                try:
                    self.playerVolumeSlider.setValue(self._mpv.get_volume())
                except Exception:
                    pass
            self.playerVolumeSlider.valueChanged.connect(self._player_on_volume_changed)

        if self.playerPlayPauseBtn is not None:
            self.playerPlayPauseBtn.clicked.connect(self._player_on_play_pause_clicked)
        if self.playerStopBtn is not None:
            self.playerStopBtn.clicked.connect(self._player_on_stop_clicked)
        if self.playerBackBtn is not None:
            self.playerBackBtn.clicked.connect(
                lambda: self._player_seek_relative_ms(-int(self.T.player.seek_jump_back_ms)))
        if self.playerFwdBtn is not None:
            self.playerFwdBtn.clicked.connect(
                lambda: self._player_seek_relative_ms(int(self.T.player.seek_jump_fwd_ms)))
        if self.playerMuteBtn is not None:
            self.playerMuteBtn.clicked.connect(self._player_on_mute_clicked)
        if self.playerCloseBtn is not None:
            self.playerCloseBtn.clicked.connect(self._player_on_close_clicked)
        if self.playerFullscreenBtn is not None:
            self.playerFullscreenBtn.clicked.connect(self._player_on_fullscreen_clicked)
        if self.playerTimeLabel is not None:
            self.playerTimeLabel.setText("0:00 / 0:00")

        self._player_sync_play_pause_btn()

    # ============================================================
    # PLAYER MODULE: actions + seek logic + public play_path
    # ============================================================

    def _player_on_play_pause_clicked(self) -> None:
        if self._mpv is None:
            return
        self._mpv.toggle_pause()
        self._player_sync_play_pause_btn()

    def _player_on_stop_clicked(self) -> None:
        if self._mpv is None:
            return
        self._mpv.stop()
        self._player_sync_play_pause_btn()

    def _player_seek_relative_ms(self, delta_ms: int) -> None:
        if self._mpv is None:
            return
        cur_ms = self._player_to_ms(self._mpv.get_time_raw())
        self._player_seek_backend_ms(cur_ms + int(delta_ms))

    def _player_on_mute_clicked(self) -> None:
        if self._mpv is None:
            return
        self._muted = self._mpv.toggle_mute()
        try:
            if self.playerMuteBtn is not None:
                self.playerMuteBtn.setText("Muted" if self._muted else "Mute")
        except Exception:
            pass

    def _player_on_close_clicked(self) -> None:
        try:
            if self._mpv is not None:
                self._mpv.stop()
        except Exception:
            pass
        try:
            self.pages.setCurrentWidget(self.homePage)
        except Exception:
            pass

    def _player_on_fullscreen_clicked(self) -> None:
        dprint("[PLAYER] Fullscreen clicked (Option A will be implemented later)")

    def _player_on_volume_changed(self, v: int) -> None:
        if self._mpv is None:
            return
        self._mpv.set_volume(int(v))

    def _player_maybe_detect_unit(self, dur_raw) -> None:
        if self._mpv_time_unit is not None:
            return
        try:
            d = float(dur_raw)
        except Exception:
            return
        if d <= 0:
            return
        self._mpv_time_unit = "ms" if d >= 100_000 else "seconds"
        dprint(f"[PLAYER] Detected MPV time unit: {self._mpv_time_unit} (dur_raw={dur_raw})")

    def _player_to_ms(self, value_raw) -> int:
        if value_raw is None:
            return 0
        try:
            v = float(value_raw)
        except Exception:
            return 0
        if v <= 0:
            return 0
        unit = self._mpv_time_unit
        if unit is None:
            unit = "ms" if v >= 100_000 else "seconds"
        return int(v * 1000.0) if unit == "seconds" else int(v)

    def _player_seek_backend_ms(self, target_ms: int) -> None:
        if self._mpv is None:
            return
        target_ms = max(0, int(target_ms))
        self._mpv.seek_seconds(float(target_ms) / 1000.0)

    def _player_engage_seek_lock(self, target_ms: int) -> None:
        self._seek_lock_active = True
        self._seek_lock_target_ms = int(max(0, target_ms))
        try:
            self._seek_lock_timer.start(int(self.T.player.seek_lock_release_ms))
        except Exception:
            pass

    def _player_release_seek_lock(self) -> None:
        self._seek_lock_active = False
        self._seek_lock_target_ms = 0

    def _player_on_seek_pressed(self) -> None:
        self._slider_dragging = True

    def _player_on_seek_action_triggered(self, action: int) -> None:
        self._slider_dragging = True

    def _player_on_seek_released(self) -> None:
        if self._mpv is None or self.playerSeekSlider is None:
            self._slider_dragging = False
            return

        try:
            val = int(self.playerSeekSlider.value())
        except Exception:
            val = 0

        denom = float(max(1, int(self.T.player.seek_slider_max)))
        ratio = max(0.0, min(1.0, val / denom))

        dur_raw = self._mpv.get_duration_raw()
        self._player_maybe_detect_unit(dur_raw)
        dur_ms = self._player_to_ms(dur_raw)

        if dur_ms <= 0:
            self._pending_seek_ratio = ratio
            dprint(f"[PLAYER] Seek requested before duration ready; pending ratio={ratio:.3f}")
            self._slider_dragging = False
            return

        target_ms = max(0, min(dur_ms, int(ratio * dur_ms)))
        self._player_engage_seek_lock(target_ms)
        self._player_seek_backend_ms(target_ms)
        self._slider_dragging = False

    def _player_tick_ui(self) -> None:
        if self._mpv is None:
            return

        cur_raw = self._mpv.get_time_raw()
        dur_raw = self._mpv.get_duration_raw()
        self._player_maybe_detect_unit(dur_raw)
        cur_ms = self._player_to_ms(cur_raw)
        dur_ms = self._player_to_ms(dur_raw)

        if dur_ms > 0 and self._pending_seek_ratio is not None:
            ratio = float(self._pending_seek_ratio)
            self._pending_seek_ratio = None
            target_ms = max(0, min(dur_ms, int(ratio * dur_ms)))
            dprint(f"[PLAYER] Applying pending seek: {target_ms}ms (ratio={ratio:.3f})")
            self._player_engage_seek_lock(target_ms)
            self._player_seek_backend_ms(target_ms)

        if self.playerTimeLabel is not None:
            self.playerTimeLabel.setText(f"{fmt_ms(cur_ms)} / {fmt_ms(dur_ms)}")

        if self.playerSeekSlider is not None:
            if self._slider_dragging:
                self._player_sync_play_pause_btn()
                return

            if self._seek_lock_active and dur_ms > 0:
                target = int(self._seek_lock_target_ms)
                if abs(cur_ms - target) <= int(self.T.player.seek_lock_release_tolerance_ms):
                    self._player_release_seek_lock()
                else:
                    ratio = (target / dur_ms) if dur_ms > 0 else 0.0
                    pos = int(max(0.0, min(1.0, ratio)) * int(self.T.player.seek_slider_max))
                    self.playerSeekSlider.setValue(pos)
                    self._player_sync_play_pause_btn()
                    return

            pos = int((cur_ms / dur_ms) * int(self.T.player.seek_slider_max)) if dur_ms > 0 else 0
            self.playerSeekSlider.setValue(pos)

        self._player_sync_play_pause_btn()

    def _player_sync_play_pause_btn(self) -> None:
        if self.playerPlayPauseBtn is None or self._mpv is None:
            return
        try:
            self.playerPlayPauseBtn.setText("Play" if self._mpv.is_paused() else "Pause")
        except Exception:
            pass

    def play_path(self, path: str) -> None:
        p = Path(path)
        self._current_path = p
        dprint("[PLAY] Requested:", p)

        try:
            self.pages.setCurrentWidget(self.playerPage)
        except Exception:
            pass

        if self._mpv is not None and self.videoHost is not None:
            try:
                self._mpv.set_wid(int(self.videoHost.winId()))
            except Exception:
                pass

        if self._mpv is None:
            dprint("[PLAY][WARN] MPV backend not available.")
            return

        self._player_release_seek_lock()
        self._pending_seek_ratio = None
        self._mpv_time_unit = None

        try:
            self._mpv.load(str(p))
            self._mpv.play()
        except Exception as e:
            dprint("[PLAY][ERROR] Failed to load:", e)

        self._player_tick_ui()

    # ============================================================
    # HOME MODULE: widget discovery + donor capture
    # ============================================================

    def _home_init_widgets(self) -> None:
        self.homeScrollArea: Optional[QScrollArea] = safe_find(
            self.homePage,
            "homeScrollArea",
            QScrollArea,
            required=False,
        )

        # Dark gray background for the Home scroll area (and transparent inner layers)
        self._home_apply_dark_gray_background()

        self.homeScrollContents: Optional[QWidget] = None

        if self.homeScrollArea is not None:
            try:
                self.homeScrollArea.setWidgetResizable(True)
                self.homeScrollArea.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                self.homeScrollArea.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
                self.homeScrollArea.setMinimumWidth(0)
            except Exception:
                pass

            carrier = self.homeScrollArea.widget()
            inner = None
            try:
                inner = carrier.findChild(QWidget, "homeScrollContents") if carrier is not None else None
            except Exception:
                inner = None

            self.homeScrollContents = inner if inner is not None else carrier

            try:
                if self.homeScrollArea is not None and self.homeScrollContents is not None:
                    if self.homeScrollArea.widget() is not self.homeScrollContents:
                        try:
                            self.homeScrollContents.setParent(None)
                        except Exception:
                            pass
                        self.homeScrollArea.setWidget(self.homeScrollContents)

                    self.homeScrollArea.setWidgetResizable(True)
                    self.homeScrollContents.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
                    self.homeScrollContents.setMinimumSize(0, 0)
                    self.homeScrollContents.setMaximumSize(16777215, 16777215)
                    self.homeScrollContents.setGeometry(0, 0, 1, 1)
                    self.homeScrollContents.updateGeometry()
                    self.homeScrollArea.viewport().update()
            except Exception as e:
                dprint("[HOME][WARN] Failed to force direct scroll widget:", e)

            self.homeContent: Optional[QWidget] = safe_find(self.homePage, "homeContent", QWidget, required=False)

            # Force the parent chain to expand naturally
            central_widget = self.win.centralWidget()
            if central_widget is not None:
                central_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
                central_widget.setMinimumSize(0, 0)
                central_widget.setMaximumSize(16777215, 16777215)
                central_widget.updateGeometry()

            for name in ("libraryRoot", "libraryLeft"):
                w = safe_find(self.homePage, name, QWidget)
                if w is not None:
                    w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
                    w.setMinimumSize(0, 0)
                    w.setMaximumSize(16777215, 16777215)
                    w.updateGeometry()

            if self.homePage is not None:
                self.homePage.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
                self.homePage.setMinimumSize(0, 0)
                self.homePage.setMaximumSize(16777215, 16777215)
                self.homePage.updateGeometry()

            if self.homeScrollArea is not None:
                self.homeScrollArea.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
                self.homeScrollArea.setMinimumSize(0, 0)
                self.homeScrollArea.setMaximumSize(16777215, 16777215)
                self.homeScrollArea.updateGeometry()
                self.homeScrollArea.viewport().updateGeometry()

            # Debug widths
            dprint("[DEBUG] centralWidget width:", central_widget.width() if central_widget else "None")
            dprint("[DEBUG] libraryRoot width:",
                   safe_find(self.homePage, "libraryRoot", QWidget, required=False).width() if safe_find(self.homePage,
                                                                                                         "libraryRoot",
                                                                                                         QWidget,
                                                                                                         required=False) else "None")
            dprint("[DEBUG] libraryLeft width:",
                   safe_find(self.homePage, "libraryLeft", QWidget, required=False).width() if safe_find(self.homePage,
                                                                                                         "libraryLeft",
                                                                                                         QWidget,
                                                                                                         required=False) else "None")
            dprint("[DEBUG] homeScrollArea width:", self.homeScrollArea.width() if self.homeScrollArea else "None")

            if self.homeContent is None and self.homeScrollContents is not None:
                self.homeContent = QWidget(self.homeScrollContents)
                self.homeContent.setObjectName("homeContent")
                try:
                    self.homeContent.setStyleSheet("background: transparent;")
                except Exception:
                    pass

            if self.homeScrollContents is None:
                self.homeScrollContents = QWidget()
                self.homeScrollContents.setObjectName("homeScrollContents")
                self.homeScrollArea.setWidget(self.homeScrollContents)

            try:
                self.homeScrollContents.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
                self.homeScrollContents.setMinimumHeight(0)
                self.homeScrollContents.setMaximumHeight(16777215)
            except Exception:
                pass

        else:
            dprint("[HOME][WARN] homeScrollArea not found. Rails cannot render.")

        self._donor_scroll = safe_find(self.homePage, "railContinueWatchingScroll", QScrollArea, required=False)
        self._donor_card = safe_find(self.homePage, "cardCW1", QWidget, required=False)

        self._show_card_template: Optional[CardTemplate] = None
        self._donor_scroll_stylesheet = ""
        self._donor_scroll_h_policy = Qt.ScrollBarAlwaysOff

        self._card_h = 500
        self._rail_pad = 1
        self._rail_h = self._card_h + self._rail_pad

        if self._donor_scroll is not None:
            self._donor_scroll_stylesheet = self._donor_scroll.styleSheet() or ""
            try:
                self._donor_scroll_h_policy = self._donor_scroll.horizontalScrollBarPolicy()
            except Exception:
                self._donor_scroll_h_policy = Qt.ScrollBarAlwaysOff

        if self._donor_card is not None:
            self._show_card_template = self._home_capture_card_template(
                card_root=self._donor_card,
                want=["cardCW1Poster", "cardBottomFade", "cardCW1Title", "cardMoreBtn", "cardCW1Click"],
                fallback_w=260,
                fallback_h=145,
            )
            self._card_h = max(self._donor_card.height(), self._donor_card.sizeHint().height(), 145)
            self._rail_h = self._card_h + self._rail_pad
            dprint("[TEMPLATE] card_h:", self._card_h, "rail_h:", self._rail_h)
            self._home_hide_donor_widget(self._donor_scroll)

        self._home_layout: Optional[QVBoxLayout] = None

        if self.homeContent is not None and self.homeScrollContents is not None:
            self._home_setup_center_lane()
            try:
                _dbg_widget(self.homeScrollArea.viewport() if self.homeScrollArea else None, "viewport")
                _dbg_widget(self.homeScrollContents, "homeScrollContents")
                _dbg_widget(self.homeContent, "homeContent")
            except Exception:
                pass
            self._home_layout = self._home_ensure_vbox_layout()
            self._home_install_page_down_button()

        self._inline_expander_widget: Optional[QWidget] = None
        self._rail_id_to_row_block: Dict[str, QWidget] = {}

        self.seasonBox: Optional[QComboBox] = safe_find(self.win, "seasonBox", QComboBox, required=False)
        self.detailsPanel: Optional[QWidget] = safe_find(self.win, "detailsPanel", QWidget, required=False)

        if self.detailsPanel is not None:
            try:
                self.detailsPanel.setVisible(False)
                self.detailsPanel.setMinimumWidth(0)
                self.detailsPanel.setMaximumWidth(0)
                self.detailsPanel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
            except Exception:
                pass

        self.episodesScrollArea: Optional[QScrollArea] = safe_find(self.win, "episodesScrollArea", QScrollArea,
                                                                   required=False)
        self.episodesContents: Optional[QWidget] = safe_find(self.win, "episodesContents", QWidget, required=False)
        self.detailsTitleLabel: Optional[QLabel] = safe_find(self.win, "detailsTitleLabel", QLabel, required=False)
        self.detailsPosterLabel: Optional[QLabel] = safe_find(self.win, "detailsPosterLabel", QLabel, required=False)

        if self.seasonBox is not None:
            self.seasonBox.currentIndexChanged.connect(self._legacy_on_season_changed)

        self._home_set_right_details_visible(False)



    # ============================================================
    # HOME: enforce scroll sizing policies (so vertical scroll actually works)
    # ============================================================
    def _home_apply_scroll_policies(self):
        """Enforce scroll + sizing policies so Home can *actually* scroll vertically.

        The core rule:
        - QScrollArea scrolls when its child widget's *minimum size* exceeds the viewport.
        - So we must ensure:
          1) widgetResizable=True
          2) homeScrollContents/homeContent have vertical QSizePolicy = Minimum/Preferred (NOT Expanding)
          3) layouts use SetMinimumSize so Qt recomputes min size from children
        """
        if self.homeScrollArea is None or self.homeScrollContents is None or self.homeContent is None:
            return

        try:
            # Scroll area behavior
            self.homeScrollArea.setWidgetResizable(True)
            self.homeScrollArea.setFrameShape(QFrame.NoFrame)
            self.homeScrollArea.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.homeScrollArea.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            # Keep content pinned to top so you don't get weird vertical centering
            self.homeScrollArea.setAlignment(Qt.AlignTop)

            # The scroll area child widget (homeScrollContents) should NOT be vertically Expanding,
            # otherwise it tends to 'match viewport height' and you get no vertical scroll.
            self.homeScrollContents.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
            self.homeScrollContents.setMinimumHeight(0)

            # The real stacking container (homeContent) should also be Minimum vertically so its
            # min-height becomes "sum of rows" -> this is what triggers vertical scrolling.
            self.homeContent.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
            self.homeContent.setMinimumHeight(0)

            # Make sure layouts compute minimum sizes from children.
            try:
                lay = self.homeScrollContents.layout()
                if lay is not None:
                    lay.setSizeConstraint(QLayout.SetMinimumSize)
            except Exception:
                pass

            try:
                lay2 = self.homeContent.layout()
                if lay2 is not None:
                    lay2.setSizeConstraint(QLayout.SetMinimumSize)
            except Exception:
                pass

        except Exception:
            # Never let scroll policy enforcement crash the app.
            return

    def _home_finalize_scroll_extent(self):
        """Force a one-tick geometry update after a rebuild so vertical scrolling updates."""
        if self.homeScrollArea is None or self.homeScrollContents is None or self.homeContent is None:
            return

        try:
            # Activate layouts so min-size is up to date
            if self.homeContent.layout() is not None:
                self.homeContent.layout().activate()
            if self.homeScrollContents.layout() is not None:
                self.homeScrollContents.layout().activate()

            # Ask Qt to recompute sizes
            self.homeContent.adjustSize()
            self.homeScrollContents.adjustSize()

            # Nudge scroll area to re-evaluate
            self.homeScrollArea.updateGeometry()
            self.homeScrollArea.viewport().update()
        except Exception:
            pass

    def _home_setup_scroll_hint(self) -> None:
        """Create a bottom-center 'scroll down' chevron overlay INSIDE the homeScrollArea viewport."""
        if self.homeScrollArea is None:
            return

        vp = self.homeScrollArea.viewport()

        # Create once
        if getattr(self, "_homeScrollHint", None) is None:
            hint = QLabel("⌄", vp)  # use a glyph you like; could also be "▼"
            hint.setObjectName("homeScrollHint")
            hint.setAlignment(Qt.AlignCenter)
            hint.setAttribute(Qt.WA_TransparentForMouseEvents, True)  # don't block clicks
            hint.setStyleSheet("""
                QLabel#homeScrollHint {
                    font-size: 28px;
                    background: rgba(0,0,0,120);
                    border-radius: 16px;
                    padding: 6px 10px;
                }
            """)
            hint.hide()
            self._homeScrollHint = hint

            # Update on scroll changes
            try:
                self.homeScrollArea.verticalScrollBar().valueChanged.connect(self._home_update_scroll_hint)
                self.homeScrollArea.verticalScrollBar().rangeChanged.connect(self._home_update_scroll_hint)
            except Exception:
                pass

        # Position it now
        self._home_update_scroll_hint()

    def _home_update_scroll_hint(self) -> None:
        """Reposition + show/hide the bottom chevron based on viewport size and scroll position."""
        if self.homeScrollArea is None:
            return
        hint: QLabel | None = getattr(self, "_homeScrollHint", None)
        if hint is None:
            return

        vp = self.homeScrollArea.viewport()
        rect = vp.rect()

        vbar = self.homeScrollArea.verticalScrollBar()
        maxv = vbar.maximum()
        val = vbar.value()

        # If there's nothing to scroll, hide.
        if maxv <= 0:
            hint.hide()
            return

        # Show if we're not basically at the bottom yet.
        threshold_px = 12
        should_show = val < (maxv - threshold_px)

        if not should_show:
            hint.hide()
            return

        # Bottom-center placement inside the viewport.
        margin_bottom = 18
        hint.adjustSize()
        w = hint.width()
        h = hint.height()

        x = int(rect.center().x() - (w / 2))
        y = int(rect.bottom() - margin_bottom - h)

        hint.move(x, y)
        hint.show()
        hint.raise_()

    # ============================================================
    # HOME MODULE: tools wiring + layout helpers + responsive profile
    # ============================================================
    def _home_apply_dark_gray_background(self) -> None:
        """
        Dark gray Home QScrollArea background.
        Keep viewport/contents transparent to avoid stacked black slabs.
        """
        if not getattr(self, "homeScrollArea", None):
            return

        bg = "#1f1f1f"  # dark gray

        self.homeScrollArea.setStyleSheet(f"""
            QScrollArea#homeScrollArea {{
                background: {bg};
                border: none;
            }}
            QScrollArea#homeScrollArea > QWidget {{
                background: transparent;
            }}
        """)

        # If your code creates/assigns homeScrollContents later, keep it transparent too.
        try:
            if getattr(self, "homeScrollContents", None):
                self.homeScrollContents.setStyleSheet("background: transparent;")
        except Exception:
            pass
    def _home_wire_tools_actions(self) -> None:
        act = safe_find(self.win, "actionLibrary_Maintenance", QObject, required=False)
        if act is None:
            dprint("[TOOLS] actionLibrary_Maintenance not found (ok).")
        else:
            try:
                act.triggered.connect(self._library_ui_add_source)
                dprint("[TOOLS] Wired actionLibrary_Maintenance -> Add Library Source picker")
            except Exception as e:
                dprint("[TOOLS][WARN] Could not wire Library maintenance action:", e)

        act2 = safe_find(self.win, "actionUpdate_Poster_Art", QObject, required=False)
        if act2 is None:
            dprint("[TOOLS] actionUpdate_Poster_Art not found (ok).")
            return
        try:
            act2.triggered.connect(self._ui_open_poster_art_dialog)
            dprint("[TOOLS] Wired actionUpdate_Poster_Art -> Poster Art dialog")
        except Exception as e:
            dprint("[TOOLS][WARN] Could not wire Update Poster Art action:", e)

    def _home_ensure_vbox_layout(self) -> QVBoxLayout:
        dprint("[DEBUG][VBOX] Starting ensure_vbox_layout")

        if getattr(self, "homeContent", None) is None or self.homeContent is None:
            dprint("[DEBUG][VBOX] homeContent None - creating new")
            if self.homeScrollContents is None:
                dprint("[DEBUG][VBOX] homeScrollContents None - fatal")
                raise RuntimeError("homeScrollContents missing; cannot build home layout.")
            self.homeContent = QWidget(self.homeScrollContents)
            self.homeContent.setObjectName("homeContent")
            self._home_setup_center_lane()

        dprint("[DEBUG][VBOX] Pre-lay homeContent geo=", self.homeContent.geometry(), " policy=",
               self.homeContent.sizePolicy())
        lay = self.homeContent.layout()
        if lay is None:
            dprint("[DEBUG][VBOX] Creating new VBox for homeContent")
            lay = QVBoxLayout(self.homeContent)
            self.homeContent.setLayout(lay)

        lay.setContentsMargins(
            int(self.T.home.home_content_pad_left_px),
            int(self.T.home.home_content_pad_top_px),
            int(self.T.home.home_content_pad_right_px),
            int(self.T.home.home_content_pad_bottom_px),
        )
        dprint("[DEBUG][VBOX] Lay margins set:", lay.contentsMargins())
        lay.setSpacing(int(self.T.home.row_block_spacing_px))
        dprint("[DEBUG][VBOX] Lay spacing set:", lay.spacing())

        top_spacer = QWidget(self.homeContent)
        top_spacer.setFixedHeight(int(self.T.home.home_content_pad_top_px))
        top_spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        lay.insertWidget(0, top_spacer)
        dprint("[DEBUG][VBOX] Added top spacer h=", top_spacer.height(), " policy=", top_spacer.sizePolicy())

        lay.setAlignment(Qt.AlignTop)
        dprint("[DEBUG][VBOX] Lay alignment set to AlignTop")
        dprint("[DEBUG][VBOX] Post-lay homeContent geo=", self.homeContent.geometry(), " policy=",
               self.homeContent.sizePolicy())
        return lay

    def _home_get_viewport_width(self) -> int:
        try:
            if getattr(self, "homeContent", None) is not None and self.homeContent is not None:
                w = int(self.homeContent.width())
                if w > 50:
                    return max(1, w)
        except Exception:
            pass
        try:
            if self.homeScrollArea is not None:
                vw = int(self.homeScrollArea.viewport().width())
                if vw > 50:
                    return max(1, vw)
        except Exception:
            pass
        return 1

    def _home_get_viewport_height(self) -> int:
        try:
            if self.homeScrollArea is not None:
                vh = int(self.homeScrollArea.viewport().height())
                if vh > 50:
                    return max(1, vh)
        except Exception:
            pass
        return 1

    def _home_compute_profile(self) -> dict:
        dprint("[DEBUG][PROFILE] Starting compute_profile")

        vw = self._home_get_viewport_width()
        vh = self._home_get_viewport_height()
        dprint("[DEBUG][PROFILE] vw=", vw, " vh=", vh)

        card_w_min = int(self.T.home.card_w_min_px)
        card_w_max = int(self.T.home.card_w_max_px)
        dprint("[DEBUG][PROFILE] card_w min/max=", card_w_min, card_w_max)

        base_w, base_h = 260, 145
        try:
            if self._show_card_template is not None:
                base_w = int(self._show_card_template.root_size.width())
                base_h = int(self._show_card_template.root_size.height())
                dprint("[DEBUG][PROFILE] Donor base w/h=", base_w, base_h)
        except Exception as e:
            dprint("[DEBUG][PROFILE] Donor base error - fallback 260x145:", e)

        aspect = float(base_h) / float(base_w) if base_w > 0 else (145.0 / 260.0)
        dprint("[DEBUG][PROFILE] Aspect ratio=", aspect)

        spacing_min = int(self.T.home.card_spacing_min_px)
        spacing_max = int(self.T.home.card_spacing_max_px)
        dprint("[DEBUG][PROFILE] spacing min/max=", spacing_min, spacing_max)

        gutter_min = int(self.T.home.rail_gutter_min_px)
        gutter_max = int(self.T.home.rail_gutter_max_px)
        dprint("[DEBUG][PROFILE] gutter min/max=", gutter_min, gutter_max)

        visible_min = int(self.T.home.visible_cards_min)
        visible_max = int(self.T.home.visible_cards_max)
        dprint("[DEBUG][PROFILE] visible min/max=", visible_min, visible_max)

        target_cell = int(vw / float(self.T.home.target_cell_divisor))
        target_cell = max(int(self.T.home.target_cell_min_px), min(int(self.T.home.target_cell_max_px), target_cell))
        dprint("[DEBUG][PROFILE] target_cell=", target_cell)

        n = int(round(vw / max(1, target_cell)))
        n = max(visible_min, min(visible_max, n))
        dprint("[DEBUG][PROFILE] visible n=", n)

        gutter = int(vw * float(self.T.home.rail_gutter_ratio))
        gutter = max(gutter_min, min(gutter_max, gutter))
        dprint("[DEBUG][PROFILE] Base gutter=", gutter)

        if vw < int(self.T.home.narrow_window_threshold_px):
            gutter = max(gutter_min, int(vw * float(self.T.home.narrow_window_gutter_ratio)))
            dprint("[DEBUG][PROFILE] Narrow window gutter override=", gutter)

        lane_w = max(1, vw - (2 * gutter))
        dprint("[DEBUG][PROFILE] lane_w=", lane_w)

        spacing = int(lane_w * float(self.T.home.card_spacing_ratio_of_lane))
        spacing = max(spacing_min, min(spacing_max, spacing))
        dprint("[DEBUG][PROFILE] spacing=", spacing)

        raw_card_w = int((lane_w - ((n - 1) * spacing)) / max(1, n))
        card_w = max(card_w_min, min(card_w_max, raw_card_w))
        dprint("[DEBUG][PROFILE] raw_card_w=", raw_card_w, " clamped=", card_w)

        while n > 2:
            test_raw = int((lane_w - ((n - 1) * spacing)) / max(1, n))
            if test_raw >= card_w_min:
                break
            n -= 1
            dprint("[DEBUG][PROFILE] Reduced n to", n, "for min card_w")

        raw_card_w = int((lane_w - ((n - 1) * spacing)) / max(1, n))
        card_w = max(card_w_min, min(card_w_max, raw_card_w))
        dprint("[DEBUG][PROFILE] Final card_w=", card_w)

        card_h = int(card_w * aspect)
        card_h = max(int(self.T.home.card_h_min_px), min(int(self.T.home.card_h_max_px), card_h))
        dprint("[DEBUG][PROFILE] card_h=", card_h)

        rail_pad = int(card_h * float(self.T.home.rail_pad_ratio_of_card_h))
        rail_pad = max(int(self.T.home.rail_pad_min_px), min(int(self.T.home.rail_pad_max_px), rail_pad))
        dprint("[DEBUG][PROFILE] rail_pad=", rail_pad)

        rail_h = int(card_h + rail_pad)
        dprint("[DEBUG][PROFILE] rail_h=", rail_h)

        step_px = int(card_w + spacing)
        dprint("[DEBUG][PROFILE] snap_step=", step_px)

        hero_space = int(vh * float(self.T.home.hero_space_ratio_of_viewport_h))
        hero_space = max(int(self.T.home.hero_space_min_px), min(int(self.T.home.hero_space_max_px), hero_space))
        dprint("[DEBUG][PROFILE] hero_space=", hero_space)

        return {
            "vw": int(vw), "vh": int(vh),
            "gutter": int(gutter), "lane_w": int(lane_w),
            "visible": int(n), "spacing": int(spacing),
            "card_w": int(card_w), "card_h": int(card_h),
            "rail_h": int(rail_h), "snap_step": int(step_px),
            "hero_space": int(hero_space),
        }

    def _home_on_viewport_resized(self) -> None:
        try:
            self._home_resize_debounce.start(int(self.T.home.resize_debounce_ms))
        except Exception:
            pass

    # ============================================================
    # HOME MODULE: rebuild + build rows + rail shell
    # ============================================================

    def _home_rebuild_responsive_now(self) -> None:
        """
        Rebuild rails using the REAL viewport width so rows show more cards on ultrawide.
        """
        if self.homeScrollArea is None or self.homeContent is None:
            return

        vw = int(self.homeScrollArea.viewport().width())

        left_pad = int(getattr(self.tune_home, "page_pad_left", 70)) if hasattr(self, "tune_home") else 70
        right_pad = int(getattr(self.tune_home, "page_pad_right", 70)) if hasattr(self, "tune_home") else 70

        usable_w = max(0, vw - left_pad - right_pad)

        # Make sure lane is updated BEFORE building rails
        self._home_update_center_lane_width()

        # ------------------------------------------------------------
        # IMPORTANT: Pass usable_w into your RailShell / row builders
        # ------------------------------------------------------------
        try:
            dprint(f"[HOME][REBUILD] vw={vw} usable_w={usable_w} homeContentW={self.homeContent.width()}")
            # ------------------------------------------------------------
            # ACTUALLY rebuild the Home rails using the latest viewport sizing
            # ------------------------------------------------------------
            try:
                self._home_build()
            except Exception as e:
                dprint("[HOME][REBUILD][WARN] _home_build failed:", e)

        except Exception:
            pass

        # Example usage:
        # self._build_continue_watching_row(available_w=usable_w)
        # self._build_alpha_rows(available_w=usable_w)
        #
        # OR if you have a single function:
        # self._home_build_all_rows(available_w=usable_w)

        # If your rails are stored in a list and each is a RailShell:
        # for rail in self._home_rails:
        #     rail.set_available_width(usable_w)
        #     rail.rebuild()

        # Finally, kill any accidental horizontal scroll drift:
        try:
            self.homeScrollArea.horizontalScrollBar().setValue(0)
        except Exception:
            pass

        # One-tick finalize so the scroll area recalculates the full vertical extent.
        try:
            QTimer.singleShot(0, self._home_finalize_scroll_extent)
        except Exception:
            pass

    def _home_hide_donor_widget(self, w: Optional[QWidget]) -> None:
        if w is None:
            return
        w.setVisible(False)
        w.setMinimumHeight(0)
        w.setMaximumHeight(0)
        dprint("[DONOR] Hidden donor widget:", w.objectName())

    def _home_capture_card_template(self, card_root: QWidget, want: List[str], fallback_w: int,
                                    fallback_h: int) -> CardTemplate:
        g = card_root.geometry()
        root_w = max(int(g.width()), int(card_root.sizeHint().width()), int(card_root.minimumWidth()), fallback_w)
        root_h = max(int(g.height()), int(card_root.sizeHint().height()), int(card_root.minimumHeight()), fallback_h)
        root_rect = QRect(0, 0, root_w, root_h)

        children: Dict[str, ChildSpec] = {}
        for name in want:
            ch = card_root.findChild(QWidget, name)
            if ch is None:
                dprint("[TEMPLATE][WARN] Missing child on donor card:", name)
                continue
            cg = ch.geometry()
            cw = max(int(cg.width()), int(ch.sizeHint().width()), int(ch.minimumWidth()), 1)
            chh = max(int(cg.height()), int(ch.sizeHint().height()), int(ch.minimumHeight()), 1)
            spec = ChildSpec(
                name=name,
                cls=type(ch),
                geom=QRect(int(cg.x()), int(cg.y()), cw, chh),
                stylesheet=ch.styleSheet() or "",
                font=QFont(ch.font()),
                text=(ch.text() if isinstance(ch, (QLabel, QPushButton, QToolButton)) else ""),
                alignment=(ch.alignment() if isinstance(ch, QLabel) else Qt.Alignment()),
            )
            children[name] = spec

        tmpl = CardTemplate(
            root_cls=type(card_root),
            root_size=root_rect,
            root_stylesheet=card_root.styleSheet() or "",
            root_font=QFont(card_root.font()),
            children=children,
        )
        dprint("[TEMPLATE] Captured card template. root_size:", root_w, "x", root_h, "children:", list(children.keys()))
        return tmpl

    def _home_set_right_details_visible(self, visible: bool) -> None:
        widgets = [self.detailsTitleLabel, self.detailsPosterLabel, self.seasonBox,
                   self.episodesScrollArea, self.episodesContents]
        for w in widgets:
            if w is None:
                continue
            try:
                w.setVisible(bool(visible))
            except Exception:
                pass
        if not visible:
            try:
                self._legacy_clear_episodes_ui()
            except Exception:
                pass

    # ============================================================
    # STUBS / SAFETY (prevents crashes until you wire full features)
    # ============================================================

    def _thumbs_pump_done_queue(self) -> None:
        try:
            # If your EpisodeThumbnailer has a pump/done queue method, call it here.
            # Keeping safe so the UI doesn't crash if thumbnailer is mid-refactor.
            if hasattr(self, "_thumbs") and self._thumbs is not None:
                if hasattr(self._thumbs, "pump_done_queue"):
                    self._thumbs.pump_done_queue()
        except Exception as e:
            dprint("[THUMBS][WARN] pump_done_queue:", e)

    def _thumbs_queue_missing_for_library(self) -> None:
        try:
            # Placeholder: later you'll scan library episodes and queue missing thumbs.
            # For now: no-op to avoid breaking startup.
            return
        except Exception:
            return

    def _library_ui_add_source(self) -> None:
        dprint("[TOOLS] Add source clicked (stub). Implement picker -> library.json add.")

    def _ui_open_poster_art_dialog(self) -> None:
        dprint("[TOOLS] Poster art dialog clicked (stub). Implement PosterArtDialog launch.")

    def _legacy_on_season_changed(self, *_args) -> None:
        # Legacy right-panel season dropdown handler (you’re using inline expander now).
        return

    def _legacy_clear_episodes_ui(self) -> None:
        # Legacy right-panel clear (safe no-op).
        return

    # ============================================================
    # HOME MODULE: show discovery
    # ============================================================

    def _library_gather_all_show_folders(self) -> List[Path]:
        sources = [s.path for s in self._library.list_sources(enabled_only=True)]
        return self._scanner.gather_all_show_folders(self._shows_dir, sources)

    def _home_find_show_poster(self, show_dir: Path) -> Optional[Path]:
        preferred = ["backdrop", "Backdrop", "poster", "Poster", "folder", "Folder", "cover", "Cover"]
        for bn in preferred:
            for ext in self.IMAGE_EXTS:
                cand = show_dir / f"{bn}{ext}"
                if cand.exists():
                    return cand
        try:
            for cand in show_dir.iterdir():
                if cand.is_file() and cand.suffix.lower() in self.IMAGE_EXTS:
                    return cand
        except Exception:
            pass
        return None

    def _home_find_season_poster(self, season_dir: Path) -> Optional[Path]:
        preferred = ["backdrop", "Backdrop", "poster", "Poster", "folder", "Folder", "cover", "Cover"]
        for bn in preferred:
            for ext in self.IMAGE_EXTS:
                cand = season_dir / f"{bn}{ext}"
                if cand.exists():
                    return cand
        try:
            for cand in season_dir.iterdir():
                if cand.is_file() and cand.suffix.lower() in self.IMAGE_EXTS:
                    return cand
        except Exception:
            pass
        return None

    def _home_list_shows_merged(self) -> List[ShowGroup]:
        raw_show_dirs: List[Path] = []
        for show_dir in self._library_gather_all_show_folders():
            if not show_dir.exists() or not show_dir.is_dir():
                continue
            if show_dir.name.casefold() in {"shows", "movies", "media"}:
                continue
            raw_show_dirs.append(show_dir)

        def canon(name: str) -> str:
            return (NameCleaner.clean(name) or name).casefold().strip()

        def similar(a: str, b: str) -> float:
            return SequenceMatcher(None, a, b).ratio()

        FUZZY_THRESHOLD = float(self.T.home.show_merge_fuzzy_threshold)
        groups: Dict[str, List[Path]] = {}

        for sd in raw_show_dirs:
            key = canon(sd.name) or sd.name.casefold().strip()
            if key in groups:
                groups[key].append(sd)
                continue
            matched = None
            for existing_key in list(groups.keys()):
                if abs(len(existing_key) - len(key)) >= int(self.T.home.show_merge_length_diff_cutoff):
                    continue
                if len(existing_key) < int(self.T.home.show_merge_min_name_len) or len(key) < int(
                        self.T.home.show_merge_min_name_len):
                    continue
                if similar(existing_key, key) >= FUZZY_THRESHOLD:
                    matched = existing_key
                    break
            if matched is not None:
                groups[matched].append(sd)
            else:
                groups[key] = [sd]

        out: List[ShowGroup] = []
        for _gkey, dirs in groups.items():
            primary_dir = dirs[0]
            poster = None
            for d in dirs:
                poster = self._home_find_show_poster(d)
                if poster is not None:
                    break
            mtime = 0.0
            for d in dirs:
                try:
                    mtime = max(mtime, float(d.stat().st_mtime))
                except Exception:
                    pass
            cached = self._meta_cache.get_show_title(primary_dir)
            cleaned = NameCleaner.clean(primary_dir.name)
            base = cached or cleaned or primary_dir.name
            display = self._meta_provider.get_show_display_title(primary_dir, base)
            if not cached and display:
                self._meta_cache.set_show_title(primary_dir, display)
            out.append(ShowGroup(display, primary_dir, poster, mtime, dirs))

        dprint("[SHOWS] Found:", len(out), "merged show groups.")
        return out

    # ============================================================
    # HOME MODULE: build rows + rail shell
    # ============================================================
    # ============================================================
    # HOME RAIL FILTER HELPERS (lightweight, heuristic, non-destructive)
    # ============================================================

    def _home__norm_title(self, s: str) -> str:
        try:
            return (s or "").casefold().strip()
        except Exception:
            return str(s).casefold().strip()

    def _home__infer_year_from_group(self, sg: ShowGroup) -> Optional[int]:
        """
        Best-effort year inference from folder/title (e.g. "Show Name (1997)" or "... 2012 ...").
        If not found, returns None.
        """
        candidates: List[str] = []
        try:
            candidates.append(str(getattr(sg, "display_title", "") or ""))
        except Exception:
            pass
        try:
            pd = getattr(sg, "primary_dir", None)
            if pd is not None:
                candidates.append(str(pd.name))
                candidates.append(str(pd))
        except Exception:
            pass

        year = None
        for text in candidates:
            try:
                m = re.search(r"(19\d{2}|20\d{2})", str(text))
                if m:
                    y = int(m.group(1))
                    if 1900 <= y <= 2099:
                        year = y
                        break
            except Exception:
                continue
        return year

    # ============================================================
    # ADD / CHANGE 3: Best-app scroll behavior (vertical page + horizontal rails)
    #
    # What this implements (Netflix/Disney+/Prime style):
    # - Mouse wheel / trackpad vertical scroll => page (vertical)
    # - If the mouse is OVER a rail OR a rail has focus:
    #     * shift+wheel => horizontal rail scroll
    #     * trackpad horizontal gesture (or horizontal delta dominates) => horizontal rail scroll
    # - Otherwise => vertical page scroll
    #
    # Paste these methods INSIDE your controller class (same indentation as other def's).
    # ============================================================

    def _home_install_best_scroll_routing(self) -> None:
        """
        Installs 'best apps' scroll routing:
        - Vertical wheel scrolls the HOME page (homeScrollArea)
        - Horizontal gestures (or Shift+wheel) scroll the rail you’re over (or focused).
        """
        try:
            if getattr(self, "homeScrollArea", None) is None:
                return

            # We only need the viewport to be filtered; we do NOT want to fight Qt's own
            # wheel handling elsewhere unless we intentionally reroute it.
            vp = self.homeScrollArea.viewport()
            vp.installEventFilter(self)

            # Cache: list of rail QScrollArea widgets we can route into
            self._home_rail_scroll_areas = self._home_find_all_rail_scroll_areas()

            dprint(f"[SCROLL] Installed best-app routing. rails_found={len(self._home_rail_scroll_areas)}")

            # Lock the Home viewport width to the window/layout on startup (and again after show)
            self._home_lock_viewport_to_window("init")
            QTimer.singleShot(0, lambda: self._home_lock_viewport_to_window("post-show"))

        except Exception as e:
            dprint(f"[SCROLL][WARN] Failed to install best-app routing: {e}")

    def _home_find_all_rail_scroll_areas(self) -> list:
        """
        Finds all QScrollArea rails under homeScrollContents.
        We purposely avoid relying on exact object names beyond 'rail' and 'Scroll'.
        """
        rails = []
        root = getattr(self, "homeScrollContents", None)
        if root is None:
            return rails

        try:
            # Collect all QScrollAreas in the Home tree
            all_scrolls = root.findChildren(QScrollArea)
            for sa in all_scrolls:
                name = sa.objectName() or ""
                # Heuristic: your rails are typically named like railSomethingScroll
                if name.startswith("rail") and "Scroll" in name:
                    rails.append(sa)
        except Exception:
            pass

        return rails

    def _home_pick_target_rail_for_input(self, global_pos) -> "QScrollArea | None":
        """
        Chooses the rail to scroll horizontally:
        1) If cursor is currently over a rail (or its children), use that rail.
        2) Else, if a rail (or a child) currently has focus, use that rail.
        3) Else, None.
        """
        # 1) Hover-based
        try:
            w = QApplication.widgetAt(global_pos)
            rail = self._home_walk_up_to_rail_scroll_area(w)
            if rail is not None:
                return rail
        except Exception:
            pass

        # 2) Focus-based
        try:
            fw = QApplication.focusWidget()
            rail = self._home_walk_up_to_rail_scroll_area(fw)
            if rail is not None:
                return rail
        except Exception:
            pass

        return None

    def _home_walk_up_to_rail_scroll_area(self, w) -> "QScrollArea | None":
        """Walks up parents until we hit a known rail QScrollArea (or None)."""
        if w is None:
            return None

        # If we already cached rails, use identity comparison for safety
        cached = getattr(self, "_home_rail_scroll_areas", None) or []

        cur = w
        while cur is not None:
            if isinstance(cur, QScrollArea):
                if cur in cached:
                    return cur
                # fallback heuristic if cache is empty
                name = cur.objectName() or ""
                if name.startswith("rail") and "Scroll" in name:
                    return cur
            cur = cur.parent()

        return None

    def _home_scroll_vert_page(self, dy: int) -> bool:
        """Scroll the vertical page by dy (positive dy = scroll down)."""
        try:
            sa = self.homeScrollArea
            sb = sa.verticalScrollBar()
            sb.setValue(sb.value() + dy)
            return True
        except Exception:
            return False

    def _home_scroll_horz_rail(self, rail_sa: QScrollArea, dx: int) -> bool:
        """Scroll a rail horizontally by dx (positive dx = scroll right)."""
        try:
            hb = rail_sa.horizontalScrollBar()
            hb.setValue(hb.value() + dx)
            return True
        except Exception:
            return False

    def _home_wheel_to_dx_dy(self, event) -> tuple[int, int]:
        """
        Converts a QWheelEvent into (dx, dy) in pixels-like units.
        Uses pixelDelta when present (trackpads), otherwise angleDelta.
        """
        # Trackpads often populate pixelDelta; mice usually populate angleDelta.
        pd = event.pixelDelta()
        if not pd.isNull():
            return int(pd.x()), int(pd.y())

        ad = event.angleDelta()
        # angleDelta is in 1/8 degree units; 120 is one notch. Scale gently.
        # We keep it conservative to avoid hyperspeed.
        scale = 1  # keep it simple and predictable
        return int(ad.x() * scale), int(ad.y() * scale)

    def _home__filter_by_keywords(self, shows: List[ShowGroup], keywords: List[str]) -> List[ShowGroup]:
        """
        Keyword match against display title + primary path string.
        """
        kws = [self._home__norm_title(k) for k in (keywords or []) if k]
        if not kws:
            return list(shows)

        out: List[ShowGroup] = []
        for sg in shows:
            title = self._home__norm_title(getattr(sg, "display_title", "") or "")
            path_s = ""
            try:
                pd = getattr(sg, "primary_dir", None)
                if pd is not None:
                    path_s = self._home__norm_title(str(pd))
            except Exception:
                path_s = ""

            blob = f"{title} {path_s}"
            hit = False
            for k in kws:
                if k and (k in blob):
                    hit = True
                    break
            if hit:
                out.append(sg)
        return out

    def _home__bucket_by_decade(self, shows: List[ShowGroup], decade_start: int) -> List[ShowGroup]:
        """
        Decade rails: 1980s/1990s/2000s/2010s/2020s.
        Uses inferred year; if none, it won't include the show.
        """
        out: List[ShowGroup] = []
        lo = int(decade_start)
        hi = int(decade_start + 9)
        for sg in shows:
            y = self._home__infer_year_from_group(sg)
            if y is None:
                continue
            if lo <= y <= hi:
                out.append(sg)
        return out

    def _home_build(self) -> None:
        dprint("[DEBUG][BUILD] Starting home_build")

        if self._home_layout is None or self._show_card_template is None:
            dprint("[DEBUG][BUILD] Layout or template None - abort")
            return

        prof = self._home_compute_profile()
        self._home_last_profile = dict(prof)
        dprint("[DEBUG][BUILD] Profile saved")

        self._home_rail_shells = []
        dprint("[DEBUG][BUILD] Cleared rail_shells")

        # Clear existing rows
        while self._home_layout.count():
            item = self._home_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                dprint("[DEBUG][BUILD] Removing widget:", w.objectName())
                w.setParent(None)
                w.deleteLater()
        dprint("[DEBUG][BUILD] Layout cleared, count now=", self._home_layout.count())

        # Base show set
        shows = self._home_list_shows_merged()

        # --- Core sorting we already had ---
        new_arrivals = sorted(shows, key=lambda x: x.group_mtime, reverse=True)
        a_to_z = sorted(shows, key=lambda x: x.display_title.casefold())

        # ============================================================
        # NEW RAIL COMPUTATIONS (real + lightweight heuristics)
        # ============================================================

        # Recently Watched:
        # We don't yet have real watch-state timestamps stored, so we approximate
        # with "most recently modified show folder(s)" as a proxy.
        recently_watched = list(new_arrivals)

        # Anime / Cartoons (keyword + path heuristic)
        anime = self._home__filter_by_keywords(shows, ["anime"])
        cartoons = self._home__filter_by_keywords(shows, ["cartoon", "cartoons", "animation", "animated"])

        # Decades (best-effort year extraction from title/folder)
        y1980s = self._home__bucket_by_decade(shows, 1980)
        y1990s = self._home__bucket_by_decade(shows, 1990)
        y2000s = self._home__bucket_by_decade(shows, 2000)
        y2010s = self._home__bucket_by_decade(shows, 2010)
        y2020s = self._home__bucket_by_decade(shows, 2020)

        # Haven’t watched in a while:
        # Without watch history, we approximate with the OLDEST modified folders first.
        havent_watched_in_a_while = sorted(shows, key=lambda x: x.group_mtime)

        # Haven’t watched at all:
        # Placeholder until we have real watch-state (watched/unwatched) persisted.
        havent_watched_at_all = list(a_to_z)

        # ============================================================
        # FALLBACKS (so every rail is populated even if heuristics are empty)
        # ============================================================

        def ensure_populated(lst: List[ShowGroup], fallback: List[ShowGroup]) -> List[ShowGroup]:
            return lst if lst else list(fallback)

        anime = ensure_populated(anime, a_to_z)
        cartoons = ensure_populated(cartoons, a_to_z)

        y1980s = ensure_populated(y1980s, a_to_z)
        y1990s = ensure_populated(y1990s, a_to_z)
        y2000s = ensure_populated(y2000s, a_to_z)
        y2010s = ensure_populated(y2010s, a_to_z)
        y2020s = ensure_populated(y2020s, a_to_z)

        # Keep these always populated by design
        recently_watched = ensure_populated(recently_watched, a_to_z)
        havent_watched_in_a_while = ensure_populated(havent_watched_in_a_while, a_to_z)
        havent_watched_at_all = ensure_populated(havent_watched_at_all, a_to_z)

        # ============================================================
        # BUILD ROWS (order exactly as you requested)
        # ============================================================

        def add_row(title: str, items: List[ShowGroup]) -> None:
            block = self._home_make_row_block(title, items, prof)
            self._home_layout.addWidget(block)
            dprint(f"[DEBUG][BUILD] Added rail '{title}' items={len(items)} lay count={self._home_layout.count()}")

        add_row("Recently Watched", recently_watched)
        add_row("Anime", anime)
        add_row("Cartoons", cartoons)
        add_row("1980s", y1980s)
        add_row("1990s", y1990s)
        add_row("2000s", y2000s)
        add_row("2010s", y2010s)
        add_row("2020s", y2020s)
        add_row("Haven’t Watched In A While", havent_watched_in_a_while)
        add_row("Haven’t Watched At All", havent_watched_at_all)

        self._home_layout.addStretch(1)
        dprint("[DEBUG][BUILD] Added stretch, lay count=", self._home_layout.count())

        # Apply gutter to all shells (same as before)
        g = int(prof.get("gutter", 0))
        dprint("[DEBUG][BUILD] Gutter g=", g)
        for shell in self._home_rail_shells:
            try:
                shell.set_gutter(g)
                dprint("[DEBUG][BUILD] Set gutter on shell")
            except Exception as e:
                dprint("[DEBUG][BUILD] Shell gutter error:", e)

        dprint(
            "[DEBUG][BUILD][RESPONSIVE] vw=", prof.get("vw"),
            "| gutter=", prof.get("gutter"),
            "| visible=", prof.get("visible"),
            "| card=", f"{prof.get('card_w')}x{prof.get('card_h')}",
            "| spacing=", prof.get("spacing"),
        )
        dprint("[DEBUG][BUILD] Build complete - forcing update on homeContent")

        # Force a layout pass and update the scroll hint using the REAL class method
        try:
            self._layout_sanity_clamp_mega_geometries()
        except Exception:
            pass

        try:
            self._home_update_scroll_hint()
        except Exception:
            pass

        self.homeContent.updateGeometry()

    def _home_make_row_block(self, title_text: str, show_items: List[ShowGroup], prof: dict) -> QWidget:
        dprint("[DEBUG][ROW_BLOCK] Starting make_row_block for", title_text, "items=", len(show_items))

        host = self.homeContent if self.homeContent is not None else self.homeScrollContents
        if host is None:
            host = self.homePage
        dprint("[DEBUG][ROW_BLOCK] Host=", host.objectName() if host else "None")

        block = QWidget(host)
        block.setStyleSheet("background: transparent;")
        block.setObjectName("homeRowBlock")
        block.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        block.setMinimumWidth(0)
        dprint("[DEBUG][ROW_BLOCK] Block created, policy=", block.sizePolicy())

        v = QVBoxLayout(block)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(int(self.T.home.row_block_title_to_rail_spacing_px))
        dprint("[DEBUG][ROW_BLOCK] V lay spacing=", v.spacing())

        title_wrap = QWidget(block)
        title_wrap.setObjectName("homeRailTitleWrap")
        title_wrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        title_wrap.setMinimumWidth(0)
        dprint("[DEBUG][ROW_BLOCK] Title wrap policy=", title_wrap.sizePolicy())

        title_h = QHBoxLayout(title_wrap)
        title_h.setContentsMargins(0, 0, 0, 0)
        title_h.setSpacing(0)
        dprint("[DEBUG][ROW_BLOCK] Title h lay created")

        title = QLabel(title_text, title_wrap)
        title.setStyleSheet("color: white; background: transparent;")
        title.setObjectName("homeRailTitle")
        title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        title.setMinimumHeight(int(self.T.home.rail_title_min_h_px))
        title.setMaximumHeight(int(self.T.home.rail_title_max_h_px))
        dprint("[DEBUG][ROW_BLOCK] Title min/max h=", title.minimumHeight(), title.maximumHeight())

        left_pad = int(self.T.home.rail_title_pad_left_px)
        right_pad = int(self.T.home.rail_title_pad_right_px)
        dprint("[DEBUG][ROW_BLOCK] Title pads l/r=", left_pad, right_pad)

        left_spacer = QWidget(title_wrap)
        left_spacer.setFixedWidth(left_pad)
        right_spacer = QWidget(title_wrap)
        right_spacer.setFixedWidth(right_pad)

        title_h.addWidget(left_spacer)
        dprint("[DEBUG][ROW_BLOCK] Added title left spacer")
        title_h.addWidget(title, 1)
        dprint("[DEBUG][ROW_BLOCK] Added title label")
        title_h.addWidget(right_spacer)
        dprint("[DEBUG][ROW_BLOCK] Added title right spacer")

        rail_id = f"rail::{title_text}::{id(block)}"
        rail_shell = self._home_make_show_rail_shell(show_items, rail_id=str(rail_id), parent=block, prof=prof)
        dprint("[DEBUG][ROW_BLOCK] Rail shell created for id=", rail_id)

        self._rail_id_to_row_block[str(rail_id)] = block

        v.addWidget(title_wrap)
        dprint("[DEBUG][ROW_BLOCK] Added title_wrap to v lay, v count=", v.count())
        v.addWidget(rail_shell)
        dprint("[DEBUG][ROW_BLOCK] Added rail_shell to v lay, v count=", v.count())

        title_h_calc = int(self.T.home.rail_title_min_h_px)
        spacing_calc = int(self.T.home.row_block_title_to_rail_spacing_px)
        rail_h_calc = int(prof.get("rail_h", 195))
        block_min_h = title_h_calc + spacing_calc + rail_h_calc
        block.setMinimumHeight(block_min_h)
        dprint("[DEBUG][ROW_BLOCK] Block min_h set to", block_min_h)

        rail_shell.updateGeometry()
        dprint("[DEBUG][ROW_BLOCK] rail_shell updateGeometry called")
        block.updateGeometry()
        dprint("[DEBUG][ROW_BLOCK] block updateGeometry called, final geo=", block.geometry())

        return block

    def _home_make_show_rail_shell(
            self,
            show_items: List[ShowGroup],
            rail_id: str,
            parent: Optional[QWidget] = None,
            prof: Optional[dict] = None,
    ) -> RailShell:
        dprint("[DEBUG][RAIL_SHELL] Starting make_show_rail_shell for id=", rail_id, "items=", len(show_items))

        if prof is None:
            prof = self._home_compute_profile()

        card_w = int(prof.get("card_w", 260))
        card_h = int(prof.get("card_h", 145))
        spacing = int(prof.get("spacing", 30))
        rail_h = int(prof.get("rail_h", self._rail_h))
        gutter = int(prof.get("gutter", 0))
        step_px = int(prof.get("snap_step", card_w + spacing))
        dprint("[DEBUG][RAIL_SHELL] Prof vals: card_w/h=", card_w, card_h, " spacing=", spacing, " rail_h=", rail_h,
               " gutter=", gutter, " step_px=", step_px)

        sc = QScrollArea(parent or self.homeContent or self.homeScrollContents)
        sc.setObjectName(f"railScroll::{rail_id}")
        sc.setStyleSheet(self._donor_scroll_stylesheet)
        sc.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # Allow horizontal scroll as needed; hide scrollbar for clean look
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        sc.setStyleSheet(
            sc.styleSheet() + "\nQScrollBar:horizontal { height: 0px; background: transparent; }"
        )
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        # Make absolutely sure the rail scroll area itself has no padding/frame gaps.
        try:
            sc.setContentsMargins(0, 0, 0, 0)
            sc.viewport().setContentsMargins(0, 0, 0, 0)
        except Exception:
            pass

        sc.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        sc.setMinimumHeight(rail_h)
        sc.setMaximumHeight(16777215)
        sc.setProperty("rail_id", str(rail_id))
        dprint("[DEBUG][RAIL_SHELL] sc created, policy=", sc.sizePolicy(), " min_h=", sc.minimumHeight())

        content = QWidget()
        content.setObjectName("continueWatchingCardBase")

        h = QHBoxLayout(content)
        h.setContentsMargins(
            int(self.T.home.rail_inner_pad_left_px),
            int(self.T.home.rail_inner_pad_top_px),
            int(self.T.home.rail_inner_pad_right_px),
            int(self.T.home.rail_inner_pad_bottom_px),
        )
        h.setSpacing(spacing)
        dprint("[DEBUG][RAIL_SHELL] Content h lay margins=", h.contentsMargins(), " spacing=", h.spacing())

        for sg in show_items:
            card = self._home_make_show_card(
                parent=content,
                show_group=sg,
                rail_id=str(rail_id),
                card_w=card_w,
                card_h=card_h,
            )
            h.addWidget(card)
            dprint("[DEBUG][RAIL_SHELL] Added card to h lay")

        h.addStretch(0)
        dprint("[DEBUG][RAIL_SHELL] Added stretch to h lay")

        sc.setWidget(content)
        dprint("[DEBUG][RAIL_SHELL] Set content as sc widget")

        try:
            n = int(len(show_items))
            total_w = (n * card_w) + ((n - 1) * spacing) if n > 0 else 0
            total_w += int(self.T.home.rail_overflow_padding_px)
            content.setMinimumWidth(int(total_w))
            content.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
            dprint("[DEBUG][RAIL_SHELL] Content min_w=", total_w, " policy=", content.sizePolicy())
        except Exception as e:
            dprint("[DEBUG][RAIL_SHELL] Content min_w error:", e)

        shell = RailShell(
            sc,
            gutter_px=gutter,
            fade_px=int(self.T.home.rail_fade_px),
            snap=SnapConfig(step_px=int(step_px), page_steps=int(self.T.home.snap_page_steps)),
            parent=parent or self.homeContent or self.homeScrollContents,
        )
        # Wheel must NOT scroll this horizontal rail (chevrons only).
        # Ignoring wheel here lets the Home vertical scroll area receive the wheel naturally.
        self._home_register_wheel_blocker(getattr(shell, "sc", None))

        dprint("[DEBUG][RAIL_SHELL] Shell created")

        shell.setMinimumHeight(rail_h)
        shell.setMaximumHeight(16777215)
        dprint("[DEBUG][RAIL_SHELL] Shell min/max h=", shell.minimumHeight(), shell.maximumHeight())

        try:
            self._home_rail_shells.append(shell)
            dprint("[DEBUG][RAIL_SHELL] Added to rail_shells")
        except Exception as e:
            dprint("[DEBUG][RAIL_SHELL] rail_shells append error:", e)

        try:
            if hasattr(shell, "refresh_overflow_ui"):
                QTimer.singleShot(0, shell.refresh_overflow_ui)
                QTimer.singleShot(40, shell.refresh_overflow_ui)
                dprint("[DEBUG][RAIL_SHELL] Scheduled refresh_overflow_ui")
        except Exception as e:
            dprint("[DEBUG][RAIL_SHELL] refresh_overflow_ui error:", e)

        shell.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        shell.setMinimumWidth(0)
        dprint("[DEBUG][RAIL_SHELL] Shell policy=", shell.sizePolicy(), " min_w=0")
        dprint("[DEBUG][RAIL_SHELL] make_show_rail_shell complete, shell geo=", shell.geometry())
        return shell

    def _home_dock_overlays_to_fade(self, created: Dict[str, QWidget], card: QWidget, card_w: int, card_h: int,
                                    kind: str) -> None:
        if str(kind).casefold() == "episode":
            title_h = int(self.T.overlays.episode_title_height_px)
            title_pad_top = int(self.T.overlays.episode_title_pad_top_px)
        else:
            title_h = int(self.T.overlays.show_title_height_px)
            title_pad_top = int(self.T.overlays.show_title_pad_top_px)

        try:
            card.setStyleSheet((card.styleSheet() or "") + "\nbackground-color: #000;")
        except Exception:
            pass

        poster_lbl = created.get("cardCW1Poster")
        if isinstance(poster_lbl, QLabel):
            try:
                poster_lbl.setGeometry(0, 0, card_w, card_h)
                poster_lbl.setStyleSheet((poster_lbl.styleSheet() or "") + "\nbackground-color: #000;")
                poster_lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            except Exception:
                pass

        fade = created.get("cardBottomFade")
        fade_h = int(self.T.overlays.fade_default_height_px)

        if isinstance(fade, QWidget):
            try:
                donor_h = int(fade.geometry().height()) if fade.geometry().height() > 0 else fade_h
                fade_h = donor_h if donor_h > 0 else fade_h
            except Exception:
                pass
            if fade_h < int(self.T.overlays.fade_min_height_px):
                fade_h = int(self.T.overlays.fade_default_height_px)
            try:
                fade.setGeometry(0, card_h - fade_h, card_w, fade_h)
                if not (fade.styleSheet() or "").strip():
                    fade.setStyleSheet(
                        "QWidget { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
                        "stop:0 rgba(0,0,0,0), stop:1 rgba(0,0,0,200)); border: none; }"
                    )
            except Exception:
                pass

        pad_l = int(self.T.overlays.fade_pad_left_px)
        pad_r = int(self.T.overlays.fade_pad_right_px)
        fade_top_y = card_h - fade_h

        more_btn = created.get("cardMoreBtn")
        more_w = int(self.T.overlays.more_btn_w_px)
        more_h = int(self.T.overlays.more_btn_h_px)
        more_x = card_w - pad_r - more_w
        more_y = fade_top_y + (fade_h - more_h) // 2

        if isinstance(more_btn, (QPushButton, QToolButton)):
            try:
                more_btn.setGeometry(more_x, more_y, more_w, more_h)
                more_btn.raise_()
            except Exception:
                pass

        title = created.get("cardCW1Title")
        title_x = pad_l
        title_y = fade_top_y + title_pad_top
        title_w = max(10, more_x - pad_l - 10)

        if isinstance(title, QLabel):
            try:
                title.setGeometry(title_x, title_y, title_w, title_h)
                title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                title.setStyleSheet("color: white; background: transparent;")
                title.raise_()
            except Exception:
                pass

    # ============================================================
    # HOME MODULE: show cards + inline expander + episodes
    # ============================================================

    def _home_on_show_clicked(self) -> None:
        sender = self.sender()
        if sender is None:
            dprint("[CLICK][WARN] sender() is None")
            return

        show_dirs: List[Path] = []
        show_dirs_json = sender.property("show_dirs")
        if show_dirs_json:
            try:
                arr = json.loads(str(show_dirs_json))
                if isinstance(arr, list):
                    show_dirs = [Path(str(x)) for x in arr if x]
            except Exception:
                show_dirs = []

        show_dir_str = sender.property("show_dir")
        if not show_dirs and show_dir_str:
            show_dirs = [Path(str(show_dir_str))]

        show_title = sender.property("show_title") or ""
        rail_id = sender.property("rail_id") or ""

        if not show_dirs:
            dprint("[CLICK][WARN] No show_dir(s) found on sender.")
            return

        primary = show_dirs[0]
        display_title = str(show_title) if show_title else (NameCleaner.clean(primary.name) or primary.name)
        dprint("[CLICK] Show:", display_title, "| dirs:", len(show_dirs), "| rail_id:", rail_id)

        self._home_set_right_details_visible(False)

        try:
            self._home_activate_inline_expander(str(rail_id), show_dirs, display_title)
        except Exception as e:
            dprint("[INLINE][WARN] Failed to activate expander:", e)

    def _home_close_inline_expander(self) -> None:
        exp = getattr(self, "_inline_expander_widget", None)
        if exp is None:
            return
        try:
            if self._home_layout is not None:
                self._home_layout.removeWidget(exp)
        except Exception:
            pass
        try:
            exp.setParent(None)
            exp.deleteLater()
        except Exception:
            pass
        self._inline_expander_widget = None
        try:
            if self.homeScrollContents is not None:
                self.homeScrollContents.update()
            if self.homeScrollArea is not None:
                self.homeScrollArea.viewport().update()
        except Exception:
            pass

    def _home_activate_inline_expander(self, rail_id: str, show_dirs: List[Path], display_title: str) -> None:
        if self._home_layout is None or self.homeScrollContents is None:
            return
        self._home_close_inline_expander()
        row_block = self._rail_id_to_row_block.get(str(rail_id))
        insert_index = 1
        if row_block is not None:
            try:
                insert_index = self._home_layout.indexOf(row_block) + 1
            except Exception:
                insert_index = 1

        expander = self._home_build_inline_expander(show_dirs, display_title)
        self._inline_expander_widget = expander
        last_index = max(0, self._home_layout.count() - 1)
        insert_index = min(insert_index, last_index)
        self._home_layout.insertWidget(insert_index, expander)

        try:
            if self.homeScrollArea is not None:
                delay = int(self.T.inline.ensure_visible_delay_ms)
                y_margin = int(self.T.inline.ensure_visible_y_margin_px)
                QTimer.singleShot(delay, lambda w=expander: self.homeScrollArea.ensureWidgetVisible(w, 0, y_margin))
        except Exception:
            pass

    def _home_build_inline_expander(self, show_dirs: List[Path], display_title: str) -> QWidget:
        t = self.T.inline
        lane_parent = self.homeContent if self.homeContent is not None else self.homeScrollContents
        root = QWidget(lane_parent)
        root.setObjectName("inlineEpisodesExpander")
        root.setStyleSheet("background: #000000; border-top: 1px solid rgba(255,255,255,35);")

        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(int(t.outer_spacing_px))

        top = QWidget(root)
        top.setObjectName("inlineEpisodesTopBar")
        top.setStyleSheet("background: #000000;")

        top_h = QHBoxLayout(top)
        top_h.setContentsMargins(0, 0, 0, 0)
        top_h.setSpacing(int(t.top_bar_spacing_px))

        title = QLabel(display_title, top)
        title.setObjectName("inlineEpisodesTitle")
        title.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        title.setStyleSheet("background: transparent; color: white;")

        close_btn = QPushButton("X", top)
        close_btn.setObjectName("inlineEpisodesCloseBtn")
        close_btn.setFixedWidth(int(t.close_btn_w_px))
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setFocusPolicy(Qt.NoFocus)
        close_btn.setStyleSheet(
            "background: transparent; color: white; border: 1px solid rgba(255,255,255,0.18); border-radius: 8px;"
        )

        season = QComboBox(top)
        season.setObjectName("inlineSeasonBox")
        season.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        season.setMinimumWidth(int(t.season_box_min_w_px))
        season.setStyleSheet("""
            QComboBox {
                background: #000000; color: #FFFFFF;
                border: 1px solid rgba(255,255,255,0.12); border-radius: 10px;
                padding: 6px 10px;
            }
            QComboBox:hover { border: 1px solid rgba(255,255,255,0.18); }
            QComboBox:focus { border: 1px solid rgba(255,255,255,0.22); }
            QComboBox::drop-down { border: none; width: 26px; }
            QComboBox::down-arrow { image: none; width: 0px; height: 0px; }
            QComboBox QAbstractItemView {
                background: #000000; color: #FFFFFF;
                border: 1px solid rgba(255,255,255,0.12); outline: none;
                selection-background-color: rgba(255,255,255,0.14);
                selection-color: #FFFFFF; padding: 6px;
            }
        """)

        top_h.addWidget(title)
        top_h.addSpacing(180)
        top_h.addWidget(close_btn)
        top_h.addWidget(season)
        top_h.addStretch(1)

        sc = QScrollArea(root)
        sc.setObjectName("inlineEpisodesScroll")
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        sc.setHorizontalScrollBarPolicy(self._donor_scroll_h_policy)
        sc.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sc.setStyleSheet("background: #000000; border: none;")
        try:
            sc.viewport().setStyleSheet("background: #000000; border: none;")
        except Exception:
            pass

        content = QWidget(sc)
        content.setObjectName("inlineEpisodesContent")
        content.setStyleSheet("background: #000000; border: none;")

        content_h = QHBoxLayout(content)
        content_h.setContentsMargins(0, 0, 0, 0)
        content_h.setSpacing(int(t.episodes_spacing_px))
        content_h.addStretch(1)
        sc.setWidget(content)

        try:
            base_h = int(self._show_card_template.root_size.height()) if self._show_card_template else 145
            episode_card_h = int(base_h * float(t.episode_card_scale))
            sc.setFixedHeight(int(episode_card_h + int(t.episode_rail_extra_px)))
        except Exception:
            sc.setFixedHeight(500)

        outer.addWidget(top)
        outer.addWidget(sc)

        root.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        root.setMinimumHeight(top.sizeHint().height() + sc.height() + int(t.outer_spacing_px))

        try:
            root.setProperty("show_dirs", json.dumps([str(p) for p in show_dirs]))
        except Exception:
            root.setProperty("show_dirs", "[]")
        root.setProperty("display_title", str(display_title))

        close_btn.clicked.connect(self._home_close_inline_expander)
        self._home_inline_populate_seasons(root, season, content)
        season.currentIndexChanged.connect(lambda idx: self._home_inline_on_season_changed(root, season, content, idx))

        return root

    def _home_inline_populate_seasons(self, expander_root: QWidget, season_box: QComboBox,
                                      episodes_content: QWidget) -> None:
        show_dirs: List[Path] = []
        show_dirs_json = expander_root.property("show_dirs")
        if show_dirs_json:
            try:
                arr = json.loads(str(show_dirs_json))
                if isinstance(arr, list):
                    show_dirs = [Path(str(x)) for x in arr if x]
            except Exception:
                show_dirs = []

        if not show_dirs:
            dprint("[INLINE][SEASONS][WARN] No show_dirs on expander root.")
            return

        seasons = self._home_find_season_groups_for_show_dirs(show_dirs)
        season_box.blockSignals(True)
        season_box.clear()
        for label, season_dirs in seasons:
            season_box.addItem(label, json.dumps([str(p) for p in season_dirs]))
        season_box.blockSignals(False)

        if season_box.count() <= 0:
            dprint("[INLINE][SEASONS] No seasons found.")
            return

        season_box.setCurrentIndex(0)
        data = season_box.itemData(0)
        try:
            first_dirs = [Path(str(x)) for x in json.loads(str(data)) if x]
        except Exception:
            first_dirs = []
        self._home_inline_populate_episodes(expander_root, first_dirs, episodes_content)

    def _home_inline_on_season_changed(self, expander_root: QWidget, season_box: QComboBox, episodes_content: QWidget,
                                       index: int) -> None:
        if index < 0:
            return
        data = season_box.itemData(index)
        if not data:
            return
        try:
            season_dirs = [Path(str(x)) for x in json.loads(str(data)) if x]
        except Exception:
            season_dirs = []
        self._home_inline_populate_episodes(expander_root, season_dirs, episodes_content)

    def _home_inline_populate_episodes(self, expander_root: QWidget, season_dirs: List[Path],
                                       episodes_content: QWidget) -> None:
        if episodes_content is None:
            return
        try:
            episodes_content.setStyleSheet("background: #000000; border: none;")
        except Exception:
            pass

        show_dirs: List[Path] = []
        show_dirs_json = expander_root.property("show_dirs")
        if show_dirs_json:
            try:
                arr = json.loads(str(show_dirs_json))
                if isinstance(arr, list):
                    show_dirs = [Path(str(x)) for x in arr if x]
            except Exception:
                show_dirs = []

        if not show_dirs:
            dprint("[INLINE][EP][WARN] No show_dirs on expander root.")
            return

        pairs = self._home_list_episode_files_multi(season_dirs=season_dirs, show_dirs=show_dirs)
        dprint("[INLINE][EP] Found:", len(pairs), "episodes across", len(season_dirs), "season folders.")

        lay = episodes_content.layout()
        if lay is None:
            lay = QHBoxLayout(episodes_content)
            episodes_content.setLayout(lay)

        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

        try:
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(int(self.T.inline.episodes_spacing_px))
        except Exception:
            pass

        season_poster = None
        for sd in season_dirs:
            season_poster = self._home_find_season_poster(sd)
            if season_poster is not None:
                break

        season_num = None
        try:
            if season_dirs:
                m = re.search(r"(\d+)", season_dirs[0].name)
                if m:
                    season_num = int(m.group(1))
        except Exception:
            season_num = None

        display_title = str(expander_root.property("display_title") or "")

        def global_key(ep: EpisodeRef):
            name = ep.episode_path.stem
            s_num, e_num = parse_season_episode(name)
            if s_num is not None and e_num is not None:
                return (0, s_num, e_num, name.casefold())
            if e_num is not None:
                return (1, 0, e_num, name.casefold())
            m3 = re.match(r"0*(\d{1,3})", name)
            if m3:
                return (2, 0, int(m3.group(1)), name.casefold())
            return (9, 0, 0, name.casefold())

        pairs.sort(key=global_key)

        for idx, ep in enumerate(pairs, start=1):
            card = self._home_make_episode_card(
                parent=episodes_content,
                show_root_dir=ep.show_root_dir,
                episode_path=ep.episode_path,
                season_poster=season_poster,
                show_display_title=display_title,
                season_num=season_num,
                index_1_based=idx,
            )
            try:
                card.setStyleSheet("background: transparent;")
                card.setAttribute(Qt.WA_StyledBackground, True)
            except Exception:
                pass
            lay.addWidget(card)

        lay.addStretch(1)
        episodes_content.update()

    def _home_find_season_groups_for_show_dirs(self, show_dirs: List[Path]) -> List[Tuple[str, List[Path]]]:
        season_map: Dict[int, List[Path]] = defaultdict(list)
        for sd in show_dirs:
            if not sd.exists() or not sd.is_dir():
                continue
            found_any = False
            try:
                for p in sd.iterdir():
                    if not p.is_dir():
                        continue
                    name = p.name.strip()
                    m = re.search(r"(season)\s*[_-]*\s*(\d+)", name, re.IGNORECASE)
                    if m:
                        season_map[int(m.group(2))].append(p)
                        found_any = True
                        continue
                    m2 = re.fullmatch(r"s(\d{1,2})", name, re.IGNORECASE)
                    if m2:
                        season_map[int(m2.group(1))].append(p)
                        found_any = True
                        continue
            except Exception:
                pass
            if not found_any:
                season_map[1].append(sd)

        if not season_map:
            return []
        return [(f"Season {num}", season_map[num]) for num in sorted(season_map.keys())]

    def _home_list_episode_files_multi(self, season_dirs: List[Path], show_dirs: List[Path]) -> List[EpisodeRef]:
        out: List[EpisodeRef] = []
        seen: set[str] = set()
        show_roots = {str(p): p for p in show_dirs}

        def episode_sort_key(ep_path: Path):
            name = ep_path.stem
            s_num, e_num = parse_season_episode(name)
            if s_num is not None and e_num is not None:
                return (0, s_num, e_num, name.casefold())
            if e_num is not None:
                return (1, 0, e_num, name.casefold())
            m3 = re.match(r"0*(\d{1,3})", name)
            if m3:
                return (2, 0, int(m3.group(1)), name.casefold())
            return (9, 0, 0, name.casefold())

        for sd in season_dirs:
            if not sd.exists() or not sd.is_dir():
                continue
            show_root = None
            try:
                if str(sd) in show_roots:
                    show_root = sd
                else:
                    parent = sd.parent
                    if str(parent) in show_roots:
                        show_root = parent
            except Exception:
                show_root = None
            if show_root is None:
                show_root = show_dirs[0] if show_dirs else sd
            try:
                files = [p for p in sd.iterdir() if p.is_file() and p.suffix.lower() in self.VIDEO_EXTS]
            except Exception:
                files = []
            files.sort(key=episode_sort_key)
            for ep in files:
                k = str(ep)
                if k in seen:
                    continue
                seen.add(k)
                out.append(EpisodeRef(show_root, ep))

        return out

    def _home_make_show_card(self, parent: QWidget, show_group: ShowGroup, rail_id: str, card_w: int,
                             card_h: int) -> QWidget:
        tmpl = self._show_card_template
        assert tmpl is not None

        base_w = int(tmpl.root_size.width())
        base_h = int(tmpl.root_size.height())
        card_w = int(max(1, card_w))
        card_h = int(max(1, card_h))

        card = tmpl.root_cls(parent)
        card.setObjectName("cardCW1")
        card.setFont(QFont(tmpl.root_font))
        if tmpl.root_stylesheet:
            card.setStyleSheet(tmpl.root_stylesheet)
        card.setFixedSize(card_w, card_h)
        card.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        sx = float(card_w) / float(max(1, base_w))
        sy = float(card_h) / float(max(1, base_h))

        created: Dict[str, QWidget] = {}
        for _name, spec in tmpl.children.items():
            ch = spec.cls(card)
            ch.setObjectName(spec.name)
            g = spec.geom
            ch.setGeometry(
                int(g.x() * sx), int(g.y() * sy),
                max(1, int(g.width() * sx)), max(1, int(g.height() * sy)),
            )
            ch.setFont(QFont(spec.font))
            if spec.stylesheet:
                ch.setStyleSheet(spec.stylesheet)
            if isinstance(ch, QLabel):
                ch.setAlignment(spec.alignment)
                ch.setText(spec.text)
            elif isinstance(ch, (QPushButton, QToolButton)):
                ch.setText(spec.text)
            created[spec.name] = ch

        title = created.get("cardCW1Title")
        if isinstance(title, QLabel):
            title.setText(str(show_group.display_title))

        poster_lbl = created.get("cardCW1Poster")
        apply_poster(poster_lbl, show_group.poster_path, radius=int(self.T.overlays.poster_radius_px), fill_label=False)

        click_btn = created.get("cardCW1Click")
        if not isinstance(click_btn, QPushButton):
            click_btn = QPushButton(card)
            click_btn.setObjectName("cardCW1Click")

        click_btn.setGeometry(0, 0, card_w, card_h)
        click_btn.setFlat(True)
        click_btn.setCursor(Qt.PointingHandCursor)
        click_btn.setStyleSheet("background: transparent; border: none;")
        click_btn.setFocusPolicy(Qt.NoFocus)
        click_btn.setProperty("show_dir", str(show_group.primary_dir))

        dirs_list = []
        for cand_name in ("group_dirs", "dirs", "source_dirs", "all_dirs", "merged_dirs"):
            if hasattr(show_group, cand_name):
                try:
                    dirs_list = list(getattr(show_group, cand_name) or [])
                    break
                except Exception:
                    pass
        if not dirs_list:
            dirs_list = [show_group.primary_dir]

        click_btn.setProperty("show_dirs", json.dumps([str(p) for p in dirs_list]))
        click_btn.setProperty("show_title", str(show_group.display_title))
        click_btn.setProperty("rail_id", str(rail_id))
        click_btn.clicked.connect(self._home_on_show_clicked)

        self._home_dock_overlays_to_fade(created, card, card_w, card_h, kind="show")

        if "cardCW1Poster" in created:
            created["cardCW1Poster"].lower()
        for nm in ["cardBottomFade", "cardCW1Title", "cardMoreBtn"]:
            if nm in created:
                created[nm].raise_()
        click_btn.raise_()

        return card

    def _home_make_episode_card(
            self,
            parent: QWidget,
            show_root_dir: Path,
            episode_path: Path,
            season_poster: Optional[Path],
            show_display_title: str,
            season_num: Optional[int],
            index_1_based: int,
    ) -> QWidget:
        # TEMP SAFE STUB (so the module runs).
        # Paste your real episode-card builder here next.
        w = QFrame(parent)
        w.setFixedSize(260, 145)
        w.setStyleSheet("background: #111; border-radius: 12px;")
        lbl = QLabel(f"EP {index_1_based}", w)
        lbl.setStyleSheet("color: white; background: transparent;")
        lbl.setGeometry(12, 12, 200, 24)

        btn = QPushButton(w)
        btn.setGeometry(0, 0, w.width(), w.height())
        btn.setStyleSheet("background: transparent; border: none;")
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda: self.play_path(str(episode_path)))

        return w

    def _home_on_episode_clicked(self) -> None:
        sender = self.sender()
        if sender is None:
            return
        ep_path_str = sender.property("episode_path")
        if not ep_path_str:
            return
        ep_path = Path(str(ep_path_str))
        dprint("[CLICK] Episode:", ep_path)
        self.play_path(str(ep_path))

    # ============================================================
    # LIBRARY TOOLS + POSTER DIALOG
    # ============================================================

    def _ui_open_poster_art_dialog(self) -> None:
        try:
            shows = self._home_list_shows_merged()
        except Exception:
            shows = []

        items: List[MissingArtItem] = []
        for sg in shows:
            primary = getattr(sg, "primary_dir", None)
            title = getattr(sg, "display_title", None)
            if primary is None:
                continue
            dirs = None
            for cand in ("group_dirs", "dirs", "source_dirs", "all_dirs", "merged_dirs"):
                if hasattr(sg, cand):
                    try:
                        v = getattr(sg, cand)
                        if v:
                            dirs = list(v)
                            break
                    except Exception:
                        dirs = None
            if not dirs:
                dirs = [primary]
            items.append(MissingArtItem(
                display_title=str(title) if title else str(primary.name),
                primary_dir=Path(str(primary)),
                all_dirs=[Path(str(p)) for p in dirs],
            ))

        if not items:
            QMessageBox.information(self.win, "No library items", "No shows were found in your library.")
            return

        try:
            dlg = PosterArtDialog(items, parent=self.win)
            dlg.exec()
        except Exception as e:
            QMessageBox.critical(self.win, "Poster Art Dialog Error", f"{type(e).__name__}: {e}")
            return

        try:
            rename_map = getattr(dlg, "rename_map", None)
        except Exception:
            rename_map = None

        if isinstance(rename_map, dict) and rename_map:
            applied = 0
            for k, new_title in rename_map.items():
                try:
                    p = Path(str(k))
                    t = str(new_title).strip()
                    if not t:
                        continue
                    self._meta_cache.set_show_title(p, t)
                    applied += 1
                except Exception:
                    pass
            if applied:
                dprint(f"[POSTERS] Applied {applied} rename(s) to MetadataCache.")

        self._home_build()

    def _library_ui_add_source(self) -> None:
        start_dir = str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self.win, "Select a TV Library Folder or Show Folder", start_dir)
        if not chosen:
            return

        chosen_path = Path(chosen)
        dprint("[LIBRARY] User selected:", chosen_path)

        if not chosen_path.exists() or not chosen_path.is_dir():
            QMessageBox.warning(self.win, "Invalid Folder", "That folder does not exist.")
            return

        was_added = self._library.add_source(str(chosen_path))
        if not was_added:
            QMessageBox.information(self.win, "Already Added", "That folder is already in your library sources.")
            return

        found = list(self._scanner.iter_show_folders_from_root(chosen_path))
        if not found:
            QMessageBox.information(
                self.win,
                "Source Added (No Shows Found Yet)",
                "I added the folder to your library.\n\n"
                "Right now it doesn't look like it contains show folders or seasons.\n"
                "If you don't see cards, try adding the exact TV Shows folder\n"
                "or a show folder directly.",
            )

        self._home_build()
        QMessageBox.information(self.win, "Library Updated", "Source added. Home rails refreshed.")

    # ============================================================
    # THUMBNAILS
    # ============================================================

    def _thumbs_queue_missing_for_library(self) -> None:
        if not self._thumbs.is_available():
            dprint("[THUMBS][WARN] FFmpeg not found. Episode screenshots disabled.")
            return

        def scan_thread():
            try:
                shows = self._library_gather_all_show_folders()
            except Exception:
                shows = []
            total_eps = 0
            queued = 0
            for show_dir in shows:
                seasons = self._legacy_find_season_dirs(show_dir)
                for _label, season_path in seasons:
                    try:
                        eps = self._legacy_list_episode_files(season_path)
                    except Exception:
                        eps = []
                    for ep in eps:
                        total_eps += 1
                        thumb = self._thumbs.ensure_thumbnail(show_dir, ep)
                        if thumb is None:
                            queued += 1
            dprint(f"[THUMBS] Scan complete. Episodes checked: {total_eps} | Missing queued: {queued}")

        threading.Thread(target=scan_thread, daemon=True).start()

    def _legacy_find_season_dirs(self, show_dir: str) -> list[str]:
        """
        Backward-compatible helper for older scanning code paths.
        Returns a list of season directory paths under a show directory.
        """
        try:
            p = Path(show_dir)
            if not p.exists() or not p.is_dir():
                return []

            # Common season folder patterns:
            # Season 1, Season 01, S01, etc.
            season_dirs: list[Path] = []
            for child in p.iterdir():
                if not child.is_dir():
                    continue
                name = child.name.strip().lower()
                if name.startswith("season "):
                    season_dirs.append(child)
                elif re.match(r"^s\d{1,2}$", name):  # s1, s01, s10...
                    season_dirs.append(child)

            # Sort nicely by extracted number if possible
            def key_fn(x: Path) -> tuple[int, str]:
                m = re.search(r"(\d{1,2})", x.name)
                n = int(m.group(1)) if m else 999
                return (n, x.name.lower())

            season_dirs.sort(key=key_fn)
            return [str(x) for x in season_dirs]
        except Exception:
            return []
    def _thumbs_pump_done_queue(self) -> None:
        try:
            dq = self._thumbs.done_queue()
        except Exception:
            return
        processed_any = False
        any_success = False
        while True:
            try:
                _ep_path, _thumb_path, ok = dq.get_nowait()
            except Exception:
                break
            processed_any = True
            if ok:
                any_success = True
            try:
                dq.task_done()
            except Exception:
                pass

        if not processed_any or not any_success:
            return

        exp = getattr(self, "_inline_expander_widget", None)
        if exp is not None:
            try:
                season_box = exp.findChild(QComboBox, "inlineSeasonBox")
                episodes_content = exp.findChild(QWidget, "inlineEpisodesContent")
                if season_box is not None and episodes_content is not None:
                    idx = season_box.currentIndex()
                    if idx >= 0:
                        data = season_box.itemData(idx)
                        if data:
                            try:
                                season_dirs = [Path(str(x)) for x in json.loads(str(data)) if x]
                            except Exception:
                                season_dirs = []
                            self._home_inline_populate_episodes(exp, season_dirs, episodes_content)
            except Exception:
                pass
()