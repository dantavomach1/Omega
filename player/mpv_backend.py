# omega/player/mpv_backend.py
from __future__ import annotations

import threading
import sys
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

# ------------------------------------------------------------
# MPV import (python-mpv)
# ------------------------------------------------------------
try:
    import mpv  # pip install python-mpv
except Exception as e:
    mpv = None
    _MPV_IMPORT_ERROR = e
else:
    _MPV_IMPORT_ERROR = None


class MPVBackend:
    """
    Thin wrapper around python-mpv.

    Rule:
    - The rest of the app does NOT call mpv directly.
    - The rest of the app calls THIS wrapper only.
    """

    # Keep observers limited to state transitions the controller actually handles.
    DEFAULT_OBSERVED_PROPERTIES: Tuple[str, ...] = (
        "duration",
        "pause",
        "playlist-pos",
        "path",
        "chapter-list",
        "sid",
        "aid",
        "sub-visibility",
    )

    def __init__(self):
        if mpv is None:
            raise RuntimeError(
                "python-mpv failed to import.\n\n"
                "Install:\n  pip install python-mpv\n\n"
                f"Import error:\n  {_MPV_IMPORT_ERROR}"
            )

        base_config = dict(
            log_handler=None,
            loglevel="warn",
            input_default_bindings=False,
            input_vo_keyboard=False,
            osc=False,
            profile="fast",
            hwdec="auto-safe",
            hwdec_codecs="all",
            ao="wasapi",
            vo="gpu",
            video_sync="audio",
            interpolation=False,
            deband=False,
            scale="bilinear",
            cscale="bilinear",
            dscale="bilinear",
            temporal_dither=False,
            vd_lavc_threads=1,
            framedrop="vo",
            sub_auto="all",
            sid="auto",
            sub_visibility=True,
        )
        preferred_configs = [dict(base_config)]
        if sys.platform.startswith("win"):
            # Prefer native D3D11 GPU paths on Windows and try to remove the
            # extra decoder-surface copy when the runtime supports it.
            preferred_configs = [
                dict(
                    base_config,
                    vo="gpu-next",
                    hwdec="d3d11va,auto-safe",
                    gpu_context="d3d11",
                    gpu_api="d3d11",
                    d3d11va_zero_copy=True,
                    vd_lavc_film_grain="gpu",
                ),
                dict(
                    base_config,
                    hwdec="d3d11va,auto-safe",
                    gpu_context="d3d11",
                    gpu_api="d3d11",
                    d3d11va_zero_copy=True,
                ),
                dict(base_config),
            ]

        self.player = None
        for config in preferred_configs:
            try:
                self.player = mpv.MPV(**config)
                break
            except Exception:
                self.player = None
        if self.player is None:
            self.player = mpv.MPV(**base_config)
        self._observer_lock = threading.Lock()
        self._observer_registry: Dict[Tuple[str, int], Callable[..., None]] = {}

    def set_wid(self, wid: int) -> None:
        self.player.wid = int(wid)

    def load(self, path: str) -> None:
        self.player.command("loadfile", path, "replace")

    def load_playlist(self, paths: List[str], *, play_immediately: bool = True) -> None:
        """Replace the current playlist with the provided paths."""
        items = [str(p) for p in (paths or []) if str(p).strip()]
        if not items:
            return

        first, rest = items[0], items[1:]
        self.player.command("loadfile", first, "replace")
        for path in rest:
            self.player.command("loadfile", path, "append")

        if play_immediately:
            self.player.pause = False

    def playlist_next(self) -> None:
        self.player.command("playlist-next", "force")

    def playlist_prev(self) -> None:
        self.player.command("playlist-prev", "force")

    def playlist_play_index(self, index: int) -> None:
        try:
            self.player.command("playlist-play-index", int(index))
            return
        except Exception:
            pass
        self._set_property("playlist-pos", int(index))

    def playlist_move(self, from_index: int, to_index: int) -> None:
        self.player.command("playlist-move", int(from_index), int(to_index))

    def playlist_remove(self, index: int) -> None:
        self.player.command("playlist-remove", int(index))

    def playlist_append(self, path: str) -> None:
        self.player.command("loadfile", str(path), "append")

    def play(self) -> None:
        self.player.pause = False

    def pause(self) -> None:
        self.player.pause = True

    def toggle_pause(self) -> None:
        self.player.pause = not bool(self.player.pause)

    def stop(self) -> None:
        self.player.command("stop")

    def is_paused(self) -> bool:
        return bool(self.player.pause)

    def get_time_raw(self):
        # mpv wrapper returns seconds (float) typically, but we keep it raw.
        return self.player.time_pos

    def get_duration_raw(self):
        return self.player.duration

    def get_current_path(self) -> str:
        try:
            path = self.player.path
        except Exception:
            return ""
        return "" if path is None else str(path)

    def get_playlist_pos(self):
        try:
            pos = self.player.playlist_pos
        except Exception:
            return None
        try:
            return int(pos)
        except Exception:
            return None

    def get_chapters(self) -> List[Dict[str, object]]:
        try:
            raw = self.player.chapter_list
        except Exception:
            return []
        out: List[Dict[str, object]] = []
        try:
            items = list(raw or [])
        except Exception:
            items = []
        for item in items:
            try:
                if isinstance(item, dict):
                    chapter = dict(item)
                else:
                    chapter = dict(item)
            except Exception:
                chapter = {}
            title = ""
            for key in ("title", "name", "label"):
                if key in chapter and chapter.get(key) is not None:
                    title = str(chapter.get(key) or "")
                    break
            start_ms = 0
            for key in ("time_ms", "start_ms"):
                if key in chapter and chapter.get(key) is not None:
                    try:
                        start_ms = int(round(float(chapter.get(key) or 0.0)))
                        break
                    except Exception:
                        pass
            if start_ms <= 0:
                for key in ("time", "start"):
                    if key in chapter and chapter.get(key) is not None:
                        try:
                            start_ms = int(round(float(chapter.get(key) or 0.0) * 1000.0))
                            break
                        except Exception:
                            pass
            out.append({
                "title": title,
                "start_ms": int(max(0, start_ms)),
            })
        out.sort(key=lambda item: int(item.get("start_ms", 0) or 0))
        return out

    def seek_seconds(self, target_sec: float) -> None:
        target = max(0.0, float(target_sec))
        try:
            self.player.command("seek", target, "absolute", "exact")
            return
        except Exception:
            pass
        self.player.time_pos = target

    def set_volume(self, v: int) -> None:
        self.player.volume = int(max(0, min(100, v)))

    def get_volume(self) -> int:
        try:
            return int(self.player.volume)
        except Exception:
            return 80

    def toggle_mute(self) -> bool:
        try:
            self.player.mute = not bool(self.player.mute)
            return bool(self.player.mute)
        except Exception:
            return False

    def _property_attr_name(self, name: str) -> str:
        return str(name or "").strip().replace("-", "_")

    def _format_property_value(self, value: Any) -> Any:
        if isinstance(value, bool):
            return "yes" if value else "no"
        return value

    def _set_property(self, name: str, value: Any) -> None:
        attr_name = self._property_attr_name(name)
        try:
            setattr(self.player, attr_name, value)
            return
        except Exception:
            pass
        try:
            self.player.command("set", str(name or "").replace("_", "-"), self._format_property_value(value))
        except Exception:
            pass

    def _get_property(self, name: str, default: Any = None) -> Any:
        attr_name = self._property_attr_name(name)
        try:
            return getattr(self.player, attr_name)
        except Exception:
            return default

    def get_property(self, name: str, default: Any = None) -> Any:
        return self._get_property(name, default)

    def get_hwdec_current(self) -> str:
        try:
            value = self._get_property("hwdec-current", "")
        except Exception:
            value = ""
        return str(value or "").strip()

    def is_hardware_decoding_active(self) -> bool:
        value = self.get_hwdec_current().casefold()
        return value not in {"", "no", "auto", "none", "unknown"}

    def _normalized_property_name(self, name: str) -> str:
        return str(name or "").strip().replace("_", "-")

    def observe_property(self, name: str, callback: Callable[..., None]) -> bool:
        """
        Register a lightweight mpv property observer.

        The wrapper keeps the API surface small but lets the controller switch
        from polling to event-driven updates when it is ready.
        """
        prop = self._normalized_property_name(name)
        if not prop or callback is None:
            return False

        observer = getattr(self.player, "observe_property", None)
        if not callable(observer):
            return False

        key = (prop, id(callback))
        with self._observer_lock:
            if key in self._observer_registry:
                return True
            try:
                observer(prop, callback)
            except TypeError:
                try:
                    observer(callback, prop)
                except TypeError:
                    try:
                        observer(name=prop, callback=callback)
                    except Exception:
                        return False
            except Exception:
                return False
            self._observer_registry[key] = callback
            return True

    def unobserve_property(self, name: str, callback: Optional[Callable[..., None]] = None) -> bool:
        prop = self._normalized_property_name(name)
        if not prop:
            return False

        unobserver = getattr(self.player, "unobserve_property", None)
        if not callable(unobserver):
            return False

        with self._observer_lock:
            if callback is None:
                keys = [key for key in self._observer_registry if key[0] == prop]
            else:
                keys = [(prop, id(callback))]

            removed = False
            for key in keys:
                cb = self._observer_registry.get(key)
                if cb is None:
                    continue
                try:
                    unobserver(prop, cb)
                except TypeError:
                    try:
                        unobserver(cb, prop)
                    except TypeError:
                        try:
                            unobserver(name=prop, callback=cb)
                        except Exception:
                            continue
                except Exception:
                    continue
                self._observer_registry.pop(key, None)
                removed = True
            return removed

    def observe_playback_state(self, callback: Callable[..., None], properties: Optional[Iterable[str]] = None) -> List[str]:
        observed: List[str] = []
        for prop in tuple(properties or self.DEFAULT_OBSERVED_PROPERTIES):
            if self.observe_property(prop, callback):
                observed.append(self._normalized_property_name(prop))
        return observed

    def unobserve_playback_state(self, callback: Optional[Callable[..., None]] = None, properties: Optional[Iterable[str]] = None) -> int:
        removed = 0
        for prop in tuple(properties or self.DEFAULT_OBSERVED_PROPERTIES):
            if self.unobserve_property(prop, callback):
                removed += 1
        return removed

    def get_track_list(self) -> List[Dict[str, object]]:
        try:
            raw_tracks = list(self.player.track_list or [])
        except Exception:
            raw_tracks = []

        out: List[Dict[str, object]] = []
        for item in raw_tracks:
            try:
                track = dict(item) if isinstance(item, dict) else dict(item)
            except Exception:
                track = {}
            normalized: Dict[str, object] = {}
            for key, value in track.items():
                normalized[str(key).replace("-", "_")] = value
            out.append(normalized)
        return out

    def get_subtitle_tracks(self) -> List[Dict[str, object]]:
        out: List[Dict[str, object]] = []
        for track in self.get_track_list():
            if str(track.get("type") or "").strip().casefold() == "sub":
                out.append(track)
        return out

    def get_audio_tracks(self) -> List[Dict[str, object]]:
        out: List[Dict[str, object]] = []
        for track in self.get_track_list():
            if str(track.get("type") or "").strip().casefold() == "audio":
                out.append(track)
        return out

    def get_current_subtitle_id(self) -> Optional[object]:
        sid = self._get_property("sid", None)
        if sid in (None, "", "no"):
            return None
        try:
            return int(sid)
        except Exception:
            return sid

    def get_subtitle_visible(self) -> bool:
        try:
            return bool(self._get_property("sub_visibility", True))
        except Exception:
            return True

    def get_current_audio_id(self) -> Optional[object]:
        aid = self._get_property("aid", None)
        if aid in (None, "", "no"):
            return None
        try:
            return int(aid)
        except Exception:
            return aid

    def set_subtitle_visible(self, visible: bool) -> None:
        self._set_property("sub_visibility", bool(visible))

    def set_subtitle_track(self, track_id: Optional[object], *, visible: Optional[bool] = True) -> None:
        if track_id in (None, "", "off", "no", 0):
            self._set_property("sub_visibility", False if visible is None else bool(visible))
            self._set_property("sid", "no")
            return

        if str(track_id).strip().casefold() == "auto":
            self._set_property("sid", "auto")
        else:
            try:
                self._set_property("sid", int(track_id))
            except Exception:
                self._set_property("sid", str(track_id))

        if visible is not None:
            self._set_property("sub_visibility", bool(visible))

    def set_audio_track(self, track_id: Optional[object]) -> None:
        if track_id in (None, "", "off", "no", 0):
            self._set_property("aid", "no")
            return

        if str(track_id).strip().casefold() == "auto":
            self._set_property("aid", "auto")
            return

        try:
            self._set_property("aid", int(track_id))
        except Exception:
            self._set_property("aid", str(track_id))

    def apply_subtitle_settings(self, settings: Dict[str, object]) -> None:
        for key, value in dict(settings or {}).items():
            if value is None:
                continue
            self._set_property(str(key), value)


