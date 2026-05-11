from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Callable, Dict, List, Optional, Sequence

from PySide6.QtCore import QObject, QRunnable, Signal

from omega.app.contracts import ShowGroup
from omega.library.home_catalog import CatalogBuildCancelled, HomeCatalogService
from omega.library.media_discovery import MediaDiscoveryService
from omega.library.metadata_provider_base import DisabledMetadataProvider


@dataclass(frozen=True)
class CatalogRefreshRequest:
    refresh_id: int
    reason: str
    allow_network: bool
    max_network_lookups: int
    cache_dir: Path
    video_exts: Sequence[str]
    image_exts: Sequence[str]
    seed_groups: Sequence[ShowGroup]
    sources: Sequence[Path]
    movies_dir: Path
    loose_episode_roots: Sequence[Path]
    worker_count: int


class CatalogRefreshSignals(QObject):
    finished = Signal(dict)


class CatalogRefreshTask(QRunnable):
    def __init__(self, request: CatalogRefreshRequest, cancel_event: Event) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self.request = request
        self.cancel_event = cancel_event
        self.signals = CatalogRefreshSignals()

    def run(self) -> None:  # pragma: no cover - exercised through controller integration
        t0 = float(time.time())
        payload: Dict[str, object] = {
            "refresh_id": int(self.request.refresh_id),
            "reason": str(self.request.reason),
            "items": [],
            "warnings": [],
            "error": "",
            "elapsed_s": 0.0,
            "cancelled": False,
            "worker_count": int(self.request.worker_count),
        }
        try:
            catalog = HomeCatalogService(
                cache_dir=self.request.cache_dir,
                video_exts=set(self.request.video_exts or ()),
                image_exts=set(self.request.image_exts or ()),
                logger=None,
            )
            result = catalog.build(
                list(self.request.seed_groups or []),
                sources=list(self.request.sources or []),
                movies_dir=self.request.movies_dir,
                loose_episode_roots=list(self.request.loose_episode_roots or []),
                allow_network=bool(self.request.allow_network),
                max_network_lookups=max(0, int(self.request.max_network_lookups)),
                should_cancel=lambda: bool(self.cancel_event.is_set()),
            )
            payload["items"] = list(result.all_items)
            payload["warnings"] = list(result.warnings)
        except CatalogBuildCancelled:
            payload["cancelled"] = True
        except Exception as exc:
            payload["error"] = f"{type(exc).__name__}: {exc}"
        payload["elapsed_s"] = float(time.time()) - t0
        self.signals.finished.emit(payload)


@dataclass(frozen=True)
class SourceDiscoveryRequest:
    discovery_id: int
    reason: str
    source_paths: Sequence[Path]
    limit: int
    known_titles: Sequence[object]
    worker_count: int


class SourceDiscoverySignals(QObject):
    finished = Signal(dict)


class SourceDiscoveryTask(QRunnable):
    def __init__(self, request: SourceDiscoveryRequest) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self.request = request
        self.signals = SourceDiscoverySignals()

    def run(self) -> None:  # pragma: no cover - exercised through controller integration
        t0 = float(time.time())
        payload: Dict[str, object] = {
            "discovery_id": int(self.request.discovery_id),
            "reason": str(self.request.reason),
            "candidates": [],
            "error": "",
            "elapsed_s": 0.0,
            "worker_count": int(self.request.worker_count),
        }
        try:
            service = MediaDiscoveryService(DisabledMetadataProvider())
            candidates = service.discover(
                list(self.request.source_paths or []),
                limit=max(1, int(self.request.limit)),
                known_titles=list(self.request.known_titles or []),
            )
            payload["candidates"] = list(candidates)
        except Exception as exc:
            payload["error"] = f"{type(exc).__name__}: {exc}"
        payload["elapsed_s"] = float(time.time()) - t0
        self.signals.finished.emit(payload)
