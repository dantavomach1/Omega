# omega/ui/posters.py
from __future__ import annotations

import hashlib
import queue
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter, QPainterPath, QPixmap, QRegion
from PySide6.QtWidgets import QLabel, QWidget

try:
    from omega.ui.qt_utils import dprint as _dprint
except Exception:  # pragma: no cover - debug logging is optional
    def _dprint(*args, **kwargs):  # type: ignore[no-redef]
        return None


_SOURCE_PIXMAP_CACHE_LIMIT = 96
_DERIVED_PIXMAP_CACHE_LIMIT = 256
_PATH_CACHE_KEY_LIMIT = 512
_PATH_CACHE_KEY_TTL_NS = 1_000_000_000
_SOURCE_PIXMAP_CACHE: "OrderedDict[str, QPixmap]" = OrderedDict()
_DERIVED_PIXMAP_CACHE: "OrderedDict[str, QPixmap]" = OrderedDict()
_PATH_CACHE_KEYS: "OrderedDict[str, tuple[int, str]]" = OrderedDict()
_ARTWORK_VARIANT_CACHE_VERSION = 2
_ARTWORK_VARIANT_CACHE_DIR: Optional[Path] = None
_ARTWORK_PREWARM_QUEUE: "queue.Queue[ArtworkVariantSpec]" = queue.Queue()
_ARTWORK_PREWARM_THREAD: Optional[threading.Thread] = None
_ARTWORK_PREWARM_PENDING: set[str] = set()
_ARTWORK_PREWARM_LOCK = threading.Lock()
_ARTWORK_PREWARM_PAUSED = False
_ARTWORK_PREWARM_STATE = threading.Condition(_ARTWORK_PREWARM_LOCK)


@dataclass(frozen=True)
class ArtworkVariantSpec:
    image_path: Optional[Path]
    width: int
    height: int
    radius: int = 0
    mode: str = "cover"
    cache_namespace: str = ""


def _spec_cache_key(spec: ArtworkVariantSpec) -> str:
    return _variant_cache_key(
        spec.image_path,
        spec.mode,
        spec.width,
        spec.height,
        spec.radius,
        cache_namespace=spec.cache_namespace,
    )


def _cache_get(cache: "OrderedDict[str, QPixmap]", key: str) -> QPixmap:
    pixmap = cache.get(str(key), QPixmap())
    if pixmap.isNull():
        return QPixmap()
    _dprint(f"[ART][CACHE] memory-hit key={str(key)[:96]}")
    cache.move_to_end(str(key))
    return pixmap


def _cache_put(cache: "OrderedDict[str, QPixmap]", key: str, pixmap: QPixmap, limit: int) -> QPixmap:
    if pixmap.isNull():
        return QPixmap()
    cache[str(key)] = pixmap
    cache.move_to_end(str(key))
    _dprint(f"[ART][CACHE] memory-store key={str(key)[:96]}")
    while len(cache) > int(max(1, limit)):
        cache.popitem(last=False)
    return pixmap


def _path_cache_key(image_path: Optional[Path]) -> str:
    if image_path is None:
        return ""
    try:
        path = Path(str(image_path))
    except Exception:
        return ""
    path_str = str(path)
    now_ns = time.monotonic_ns()
    cached = _PATH_CACHE_KEYS.get(path_str)
    if cached is not None:
        expires_ns, cached_key = cached
        if int(expires_ns) > now_ns:
            _PATH_CACHE_KEYS.move_to_end(path_str)
            return str(cached_key)
        _PATH_CACHE_KEYS.pop(path_str, None)
    try:
        stat = path.stat()
        cache_key = f"{path_str}|{int(stat.st_mtime_ns)}|{int(stat.st_size)}"
        _PATH_CACHE_KEYS[path_str] = (int(now_ns + _PATH_CACHE_KEY_TTL_NS), cache_key)
        _PATH_CACHE_KEYS.move_to_end(path_str)
        while len(_PATH_CACHE_KEYS) > int(max(1, _PATH_CACHE_KEY_LIMIT)):
            _PATH_CACHE_KEYS.popitem(last=False)
        return cache_key
    except Exception:
        _PATH_CACHE_KEYS.pop(path_str, None)
        return ""


def configure_artwork_variant_cache(cache_dir: Optional[Path]) -> None:
    global _ARTWORK_VARIANT_CACHE_DIR
    if cache_dir is None:
        _ARTWORK_VARIANT_CACHE_DIR = None
        return
    try:
        root = Path(str(cache_dir)) / "artwork_variants"
        root.mkdir(parents=True, exist_ok=True)
    except Exception:
        _ARTWORK_VARIANT_CACHE_DIR = None
        return
    _ARTWORK_VARIANT_CACHE_DIR = root


def _variant_cache_key(
    image_path: Optional[Path],
    mode: str,
    w: int,
    h: int,
    radius: int,
    *,
    cache_namespace: str = "",
) -> str:
    path_key = _path_cache_key(image_path)
    if not path_key:
        return ""
    target_w = max(1, int(w))
    target_h = max(1, int(h))
    target_radius = max(0, int(radius))
    mode_key = "rounded" if str(mode or "").strip().casefold() == "rounded" else "cover"
    namespace_key = str(cache_namespace or "").strip()
    return (
        f"variant:v{int(_ARTWORK_VARIANT_CACHE_VERSION)}|{namespace_key}|{mode_key}|"
        f"{path_key}|{target_w}x{target_h}|r{target_radius}"
    )


def _variant_disk_path(cache_key: str) -> Optional[Path]:
    if not cache_key or _ARTWORK_VARIANT_CACHE_DIR is None:
        return None
    digest = hashlib.sha1(cache_key.encode("utf-8", errors="ignore")).hexdigest()
    return _ARTWORK_VARIANT_CACHE_DIR / f"{digest}.png"


def _load_variant_pixmap(cache_key: str) -> QPixmap:
    disk_path = _variant_disk_path(cache_key)
    if disk_path is None or not disk_path.exists():
        _dprint(f"[ART][CACHE] disk-miss key={str(cache_key)[:96]}")
        return QPixmap()
    pixmap = QPixmap(str(disk_path))
    if pixmap.isNull():
        try:
            disk_path.unlink()
        except Exception:
            pass
        _dprint(f"[ART][CACHE] disk-corrupt key={str(cache_key)[:96]}")
        return QPixmap()
    _dprint(f"[ART][CACHE] disk-hit key={str(cache_key)[:96]}")
    return pixmap


def _center_crop_image(src: QImage, w: int, h: int) -> QImage:
    if src.isNull() or w <= 0 or h <= 0:
        return QImage()

    scaled = src.scaled(int(w), int(h), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    if scaled.isNull():
        return QImage()

    x = max(0, (scaled.width() - int(w)) // 2)
    y = max(0, (scaled.height() - int(h)) // 2)
    return scaled.copy(int(x), int(y), int(w), int(h))


def _rounded_image(src: QImage, w: int, h: int, radius: int) -> QImage:
    if src.isNull() or w <= 0 or h <= 0:
        return QImage()
    out = QImage(int(w), int(h), QImage.Format_ARGB32_Premultiplied)
    out.fill(Qt.transparent)

    painter = QPainter(out)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    path = QPainterPath()
    path.addRoundedRect(0.0, 0.0, float(w), float(h), float(max(0, radius)), float(max(0, radius)))
    painter.setClipPath(path)
    painter.drawImage(0, 0, src)
    painter.end()
    return out


def _build_variant_image(
    image_path: Optional[Path],
    mode: str,
    w: int,
    h: int,
    radius: int,
    *,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> QImage:
    if cancel_check is not None and cancel_check():
        return QImage()
    try:
        src_path = Path(str(image_path)) if image_path is not None else None
    except Exception:
        src_path = None
    if src_path is None:
        return QImage()

    src = QImage(str(src_path))
    if src.isNull():
        return QImage()
    if cancel_check is not None and cancel_check():
        return QImage()

    cropped = _center_crop_image(src, w, h)
    if cropped.isNull():
        return QImage()
    if cancel_check is not None and cancel_check():
        return QImage()
    if str(mode or "").strip().casefold() == "rounded":
        return _rounded_image(cropped, w, h, radius)
    return cropped


def _ensure_variant_file(
    cache_key: str,
    image_path: Optional[Path],
    mode: str,
    w: int,
    h: int,
    radius: int,
    *,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> Optional[Path]:
    disk_path = _variant_disk_path(cache_key)
    if disk_path is None:
        return None
    if disk_path.exists():
        return disk_path
    if cancel_check is not None and cancel_check():
        return None

    variant = _build_variant_image(
        image_path,
        mode,
        w,
        h,
        radius,
        cancel_check=cancel_check,
    )
    if variant.isNull():
        return None
    if cancel_check is not None and cancel_check():
        return None

    try:
        disk_path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        return None
    if cancel_check is not None and cancel_check():
        return None

    tmp_path = disk_path.with_name(f"{disk_path.stem}.{threading.get_ident()}.tmp.png")
    try:
        if cancel_check is not None and cancel_check():
            return None
        if not variant.save(str(tmp_path), "PNG"):
            return None
        if cancel_check is not None and cancel_check():
            return None
        try:
            tmp_path.replace(disk_path)
        except Exception:
            if not disk_path.exists():
                return None
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass
    return disk_path if disk_path.exists() else None


def _pixmap_from_variant(
    image_path: Optional[Path],
    mode: str,
    w: int,
    h: int,
    radius: int,
    *,
    cache_namespace: str = "",
) -> QPixmap:
    cache_key = _variant_cache_key(image_path, mode, w, h, radius, cache_namespace=cache_namespace)
    if not cache_key:
        return QPixmap()

    cached = _cache_get(_DERIVED_PIXMAP_CACHE, cache_key)
    if not cached.isNull():
        return cached

    pixmap = _load_variant_pixmap(cache_key)
    if pixmap.isNull():
        disk_path = _ensure_variant_file(cache_key, image_path, mode, w, h, radius)
        if disk_path is not None:
            pixmap = QPixmap(str(disk_path))

    if pixmap.isNull():
        variant = _build_variant_image(image_path, mode, w, h, radius)
        if variant.isNull():
            return QPixmap()
        pixmap = QPixmap.fromImage(variant)
    if pixmap.isNull():
        return QPixmap()
    return _cache_put(_DERIVED_PIXMAP_CACHE, cache_key, pixmap, _DERIVED_PIXMAP_CACHE_LIMIT)


def _normalize_variant_spec(spec: ArtworkVariantSpec) -> Optional[ArtworkVariantSpec]:
    try:
        target_w = max(1, int(spec.width))
        target_h = max(1, int(spec.height))
        target_radius = max(0, int(spec.radius))
    except Exception:
        return None
    mode = "rounded" if str(spec.mode or "").strip().casefold() == "rounded" else "cover"
    try:
        image_path = Path(str(spec.image_path)) if spec.image_path is not None else None
    except Exception:
        image_path = None
    if image_path is None or not _path_cache_key(image_path):
        return None
    return ArtworkVariantSpec(
        image_path=image_path,
        width=target_w,
        height=target_h,
        radius=target_radius,
        mode=mode,
        cache_namespace=str(getattr(spec, "cache_namespace", "") or ""),
    )


def _artwork_prewarm_is_paused() -> bool:
    with _ARTWORK_PREWARM_LOCK:
        return bool(_ARTWORK_PREWARM_PAUSED)


def _ensure_prewarm_thread() -> None:
    global _ARTWORK_PREWARM_THREAD
    with _ARTWORK_PREWARM_LOCK:
        if _ARTWORK_PREWARM_THREAD is not None and _ARTWORK_PREWARM_THREAD.is_alive():
            return
        _ARTWORK_PREWARM_THREAD = threading.Thread(
            target=_artwork_prewarm_worker,
            name="omega-artwork-prewarm",
            daemon=True,
        )
        _ARTWORK_PREWARM_THREAD.start()


def _artwork_prewarm_worker() -> None:
    while True:
        spec = _ARTWORK_PREWARM_QUEUE.get()
        cache_key = _spec_cache_key(spec)
        try:
            if cache_key and not _artwork_prewarm_is_paused():
                _ensure_variant_file(
                    cache_key,
                    spec.image_path,
                    spec.mode,
                    spec.width,
                    spec.height,
                    spec.radius,
                    cancel_check=_artwork_prewarm_is_paused,
                )
        finally:
            with _ARTWORK_PREWARM_LOCK:
                _ARTWORK_PREWARM_PENDING.discard(cache_key)
            _ARTWORK_PREWARM_QUEUE.task_done()


def clear_pending_artwork_prewarm() -> int:
    cleared = 0
    while True:
        try:
            spec = _ARTWORK_PREWARM_QUEUE.get_nowait()
        except queue.Empty:
            break
        cache_key = _spec_cache_key(spec)
        with _ARTWORK_PREWARM_LOCK:
            _ARTWORK_PREWARM_PENDING.discard(cache_key)
        _ARTWORK_PREWARM_QUEUE.task_done()
        cleared += 1
    return cleared


def set_artwork_prewarm_paused(paused: bool, *, drop_pending: bool = False) -> None:
    global _ARTWORK_PREWARM_PAUSED
    paused = bool(paused)
    if drop_pending:
        clear_pending_artwork_prewarm()
    with _ARTWORK_PREWARM_STATE:
        _ARTWORK_PREWARM_PAUSED = paused
        if not _ARTWORK_PREWARM_PAUSED:
            _ARTWORK_PREWARM_STATE.notify_all()
    if paused:
        clear_pending_artwork_prewarm()


def prewarm_artwork_variants(specs: Iterable[ArtworkVariantSpec]) -> None:
    if _ARTWORK_VARIANT_CACHE_DIR is None:
        return
    queued_any = False
    for raw_spec in specs:
        spec = _normalize_variant_spec(raw_spec)
        if spec is None:
            continue
        cache_key = _spec_cache_key(spec)
        disk_path = _variant_disk_path(cache_key)
        if not cache_key or disk_path is None:
            continue
        if disk_path.exists():
            continue
        with _ARTWORK_PREWARM_LOCK:
            if _ARTWORK_PREWARM_PAUSED:
                continue
            if cache_key in _ARTWORK_PREWARM_PENDING:
                continue
            _ARTWORK_PREWARM_PENDING.add(cache_key)
        _ARTWORK_PREWARM_QUEUE.put(spec)
        queued_any = True
    if queued_any:
        _ensure_prewarm_thread()


def load_pixmap_cached(image_path: Optional[Path]) -> QPixmap:
    key = _path_cache_key(image_path)
    if not key:
        return QPixmap()

    cached = _cache_get(_SOURCE_PIXMAP_CACHE, key)
    if not cached.isNull():
        return cached

    try:
        pixmap = QPixmap(str(Path(str(image_path))))
    except Exception:
        pixmap = QPixmap()
    if pixmap.isNull():
        return QPixmap()
    return _cache_put(_SOURCE_PIXMAP_CACHE, key, pixmap, _SOURCE_PIXMAP_CACHE_LIMIT)


def center_crop_pixmap(src: QPixmap, w: int, h: int) -> QPixmap:
    """
    True center-crop:
      - scale to cover
      - crop center to exact (w,h)
    """
    if src.isNull() or w <= 0 or h <= 0:
        return QPixmap()

    scaled = src.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    if scaled.isNull():
        return QPixmap()

    x = max(0, (scaled.width() - w) // 2)
    y = max(0, (scaled.height() - h) // 2)
    return scaled.copy(x, y, w, h)


def rounded_pixmap(src: QPixmap, w: int, h: int, radius: int) -> QPixmap:
    out = QPixmap(w, h)
    out.fill(Qt.transparent)

    painter = QPainter(out)
    painter.setRenderHint(QPainter.Antialiasing, True)

    path = QPainterPath()
    path.addRoundedRect(0, 0, w, h, radius, radius)
    painter.setClipPath(path)

    painter.drawPixmap(0, 0, src)
    painter.end()
    return out


def apply_rounded_mask(widget: Optional[QWidget], radius: int) -> None:
    if widget is None:
        return
    try:
        w = max(1, int(widget.width()))
        h = max(1, int(widget.height()))
        r = max(0, int(radius))
    except Exception:
        return
    if r <= 0:
        try:
            widget.clearMask()
            widget.setProperty("_omega_mask_sig", "")
        except Exception:
            pass
        return

    sig = f"{w}x{h}:r{r}"
    try:
        if str(widget.property("_omega_mask_sig") or "") == sig:
            return
    except Exception:
        pass

    path = QPainterPath()
    path.addRoundedRect(0.0, 0.0, float(w), float(h), float(r), float(r))
    try:
        widget.setMask(QRegion(path.toFillPolygon().toPolygon()))
        widget.setProperty("_omega_mask_sig", sig)
    except Exception:
        pass


def cover_pixmap_cached(image_path: Optional[Path], w: int, h: int, *, cache_namespace: str = "") -> QPixmap:
    target_w = max(1, int(w))
    target_h = max(1, int(h))
    return _pixmap_from_variant(image_path, "cover", target_w, target_h, 0, cache_namespace=cache_namespace)


def rounded_cover_pixmap_cached(
    image_path: Optional[Path],
    w: int,
    h: int,
    radius: int,
    *,
    cache_namespace: str = "",
) -> QPixmap:
    target_w = max(1, int(w))
    target_h = max(1, int(h))
    target_radius = max(0, int(radius))
    return _pixmap_from_variant(
        image_path,
        "rounded",
        target_w,
        target_h,
        target_radius,
        cache_namespace=cache_namespace,
    )


def apply_poster(
    poster_widget: Optional[QWidget],
    poster_path: Optional[Path],
    radius: int = 18,
    fill_label: bool = False,
    *,
    cache_namespace: str = "",
) -> None:
    """
    Apply a poster image to a QLabel using true center-crop + rounded corners.

    fill_label=True:
      - force label to fill its parent
      - useful for donor templates where the label is smaller than the card
    """
    if poster_widget is None:
        return
    if poster_path is None or not poster_path.exists():
        return
    if not isinstance(poster_widget, QLabel):
        return

    label: QLabel = poster_widget

    if fill_label:
        try:
            parent = label.parentWidget()
            if parent is not None:
                label.setGeometry(0, 0, int(parent.width()), int(parent.height()))
        except Exception:
            pass

    try:
        label.setScaledContents(False)
        label.setAttribute(Qt.WA_TranslucentBackground, True)
        label.setStyleSheet(f"background: transparent; border-radius: {int(max(0, radius))}px;")
    except Exception:
        pass

    target_w = max(1, int(label.width()))
    target_h = max(1, int(label.height()))
    if target_w <= 1 or target_h <= 1:
        return

    rounded = rounded_cover_pixmap_cached(
        poster_path,
        target_w,
        target_h,
        radius=radius,
        cache_namespace=cache_namespace,
    )
    if rounded.isNull():
        return

    try:
        current = label.pixmap()
        current_key = int(current.cacheKey()) if current is not None and not current.isNull() else 0
        next_key = int(rounded.cacheKey())
        if current_key != next_key:
            label.setPixmap(rounded)
        label.update()
    except Exception:
        pass
