from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .repository import LibraryBatchSummary, LibraryHealthReport, LibraryRepository


# ============================================================
# Data types
# ============================================================

@dataclass
class LibrarySource:
    """
    Represents a single library root folder.
    Controller expects objects with:
      - .path (Path)
      - .enabled (bool)
    """
    path: Path
    enabled: bool = True
    added_at: int = 0
    label: str = ""
    status: str = "available"
    error: str = ""
    source_id: str = ""


@dataclass
class LibraryPaths:
    """
    Centralized paths used by the library system.

    We compute project_root by walking up from:
        .../media-tv-brain/omega/library/manager.py
    So:
        manager.py -> library -> omega -> project_root
    """
    project_root: Path
    media_dir: Path
    shows_dir: Path
    movies_dir: Path
    config_dir: Path
    sources_json: Path
    library_json: Path

    @staticmethod
    def from_here() -> "LibraryPaths":
        project_root = Path(__file__).resolve().parents[2]
        media_dir = project_root / "Media"
        return LibraryPaths(
            project_root=project_root,
            media_dir=media_dir,
            shows_dir=media_dir / "Shows",
            movies_dir=media_dir / "Movies",
            config_dir=project_root / "config",
            sources_json=(project_root / "config" / "sources.json"),
            library_json=(media_dir / "library.json"),
        )


# ============================================================
# Library Manager
# ============================================================

class LibraryManager:
    """
    Loads/saves Media/library.json and provides a stable API.

    IMPORTANT:
    - This class returns sources as LibrarySource objects for controller compatibility.
    - It also supports older formats in library.json:
        sources: ["C:\\path", ...]
      and newer format:
        sources: [{"path":"C:\\path","enabled":true}, ...]
    """

    def __init__(self, paths: Optional[LibraryPaths] = None) -> None:
        self.paths = paths or LibraryPaths.from_here()
        self.repository = LibraryRepository(
            self.paths.library_json,
            backup_dir=self.paths.media_dir / ".omega_cache" / "library_backups",
        )

        # In-memory library data
        self._data: Dict[str, Any] = self.repository.data

        # Ensure directories exist (first run safety)
        self.paths.media_dir.mkdir(parents=True, exist_ok=True)
        self.paths.shows_dir.mkdir(parents=True, exist_ok=True)
        self.paths.movies_dir.mkdir(parents=True, exist_ok=True)
        self.paths.config_dir.mkdir(parents=True, exist_ok=True)

        # Load/create library.json through the durable repository layer.
        self.load_or_init()

    @property
    def data(self) -> Dict[str, Any]:
        return self._data

    # -------------------------
    # Load / Save
    # -------------------------

    def load_or_init(self) -> Dict[str, Any]:
        """
        Load Media/library.json if present; otherwise initialize defaults.
        Always guarantees required keys exist.
        """
        self._data = self.repository.load()
        return self._data

    def save(self) -> None:
        """Persist in-memory library to Media/library.json."""
        self.repository.save()
        self._data = self.repository.data

    # -------------------------
    # Sources API (what controller.py expects)
    # -------------------------

    def list_sources(self, enabled_only: bool = True) -> List[LibrarySource]:
        """
        Return sources as LibrarySource objects (with .path and .enabled).
        """
        sources: List[LibrarySource] = []
        for item in self.source_records():
            path = str(item.get("path", "") or "").strip()
            if not path:
                continue
            enabled = bool(item.get("enabled", True))
            sources.append(
                LibrarySource(
                    path=Path(path),
                    enabled=enabled,
                    added_at=int(item.get("added_at", 0) or 0),
                    label=str(item.get("label", "") or ""),
                    status=str(item.get("status", "available") or "available"),
                    error=str(item.get("error", "") or ""),
                    source_id=str(item.get("source_id", "") or ""),
                )
            )

        if enabled_only:
            sources = [s for s in sources if s.enabled]

        return sources

    def get_sources(self, enabled_only: bool = True) -> List[LibrarySource]:
        """
        Backwards-compatible alias (some code may call get_sources()).
        """
        return self.list_sources(enabled_only=enabled_only)

    def set_sources(self, sources: List[LibrarySource]) -> None:
        """
        Store sources in the newer structured format:
          [{"path":"...","enabled":true}, ...]
        """
        payload: List[Dict[str, Any]] = []
        for s in sources:
            path = str(Path(s.path).expanduser())
            payload.append(
                {
                    "path": path,
                    "enabled": bool(s.enabled),
                    "added_at": int(getattr(s, "added_at", 0) or 0),
                    "label": str(getattr(s, "label", "") or ""),
                    "status": str(getattr(s, "status", "available") or "available"),
                    "error": str(getattr(s, "error", "") or ""),
                    "source_id": str(getattr(s, "source_id", "") or ""),
                }
            )

        self.repository.set_source_records(payload)
        self._data = self.repository.data
        self._write_sources_json([d["path"] for d in payload])

    def add_source(self, path: str, enabled: bool = True) -> bool:
        """
        Add a new library source path.

        Returns:
            True  -> added
            False -> already exists or invalid
        """
        added, _duplicates, _invalid = self.add_sources([path], enabled=enabled)
        return bool(added)

    def add_sources(
        self,
        paths: Sequence[str],
        enabled: bool = True,
    ) -> Tuple[List[Path], List[Path], List[str]]:
        """
        Add multiple library source paths in one pass.

        Returns:
            added       -> normalized directories that were newly stored
            duplicates  -> normalized directories already present or repeated in input
            invalid     -> raw path strings that could not be used
        """
        payload = [{"path": str(p or ""), "enabled": bool(enabled)} for p in paths or []]
        added, duplicates, invalid = self.repository.upsert_source_records(payload, enabled=enabled)
        self._data = self.repository.data
        if added:
            self._write_sources_json([str(src.path) for src in self.list_sources(enabled_only=False)])
        return added, duplicates, invalid

    def set_source_enabled(self, path: object, enabled: bool) -> bool:
        """
        Enable or disable an existing source.

        Returns True when a stored source changed state.
        """
        wanted = self._source_key_from_unknown(path)
        if not wanted:
            return False

        records = self.source_records()
        changed = False
        for src in records:
            if self._source_key_from_unknown(src.get("path", "")) != wanted:
                continue
            desired = bool(enabled)
            if bool(src.get("enabled", True)) != desired:
                src["enabled"] = desired
                changed = True
        if changed:
            self.repository.set_source_records(records)
            self._data = self.repository.data
            self._write_sources_json([str(src.get("path", "")) for src in records if str(src.get("path", "")).strip()])
        return changed

    def remove_source(self, path: object) -> bool:
        """
        Remove an existing source.

        Returns True when a stored source was removed.
        """
        wanted = self._source_key_from_unknown(path)
        if not wanted:
            return False

        current = self.source_records()
        kept = [src for src in current if self._source_key_from_unknown(src.get("path", "")) != wanted]
        if len(kept) == len(current):
            return False

        self.repository.set_source_records(kept)
        self._data = self.repository.data
        self._write_sources_json([str(src.get("path", "")) for src in kept if str(src.get("path", "")).strip()])
        return True

    def source_records(self) -> List[Dict[str, Any]]:
        return self.repository.source_records()

    def load_title_groups(self) -> List[Any]:
        return self.repository.load_title_groups()

    def load_title_records(self) -> List[Dict[str, Any]]:
        return self.repository.load_title_records()

    def commit_title_groups(
        self,
        items: Sequence[Any],
        *,
        source_label: str,
        batch_id: str,
        worker_count: int,
    ) -> LibraryBatchSummary:
        summary = self.repository.commit_title_groups(
            items,
            source_label=source_label,
            batch_id=batch_id,
            worker_count=worker_count,
        )
        self._data = self.repository.data
        return summary

    def latest_errors(self) -> List[str]:
        return self.repository.latest_errors()

    def record_ingestion_start(
        self,
        *,
        batch_id: str,
        source_label: str,
        worker_count: int,
        candidate_count: int = 0,
    ) -> None:
        self.repository.record_ingestion_start(
            batch_id=batch_id,
            source_label=source_label,
            worker_count=worker_count,
            candidate_count=candidate_count,
        )
        self._data = self.repository.data

    def record_ingestion_finish(
        self,
        *,
        batch_id: str,
        summary: Optional[LibraryBatchSummary] = None,
        error: str = "",
    ) -> None:
        self.repository.record_ingestion_finish(batch_id=batch_id, summary=summary, error=error)
        self._data = self.repository.data

    def health_check(self) -> LibraryHealthReport:
        return self.repository.health_check()

    def repair_index(self) -> Tuple[LibraryHealthReport, bool]:
        report, changed = self.repository.repair_index()
        self._data = self.repository.data
        return report, changed

    def ensure_default_source(self) -> bool:
        """
        If there are NO sources at all, automatically add the local Media/Shows folder.
        Returns True if it added something.
        """
        current = self.list_sources(enabled_only=False)
        if current:
            return False

        default_source = LibrarySource(path=self.paths.shows_dir, enabled=True)
        self.set_sources([default_source])
        return True

    # -------------------------
    # Optional helpers for config/sources.json
    # -------------------------

    def _write_sources_json(self, sources: List[str]) -> None:
        """
        Write config/sources.json in a stable legacy format:
          { "sources": ["C:/path1", "D:/path2"] }
        """
        payload = {"sources": sources}
        try:
            self.paths.sources_json.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            # Not fatal if config can't be written
            pass

    def _normalize_source_path(self, path: str) -> Optional[Path]:
        raw = str(path or "").strip()
        if not raw:
            return None
        try:
            normalized = Path(raw).expanduser()
        except Exception:
            return None
        try:
            normalized = normalized.resolve()
        except Exception:
            pass
        if not normalized.exists() or not normalized.is_dir():
            return None
        return normalized

    def _source_key(self, path: Path) -> str:
        return str(Path(path).expanduser()).rstrip("\\/").casefold()

    def _source_key_from_unknown(self, path: object) -> str:
        raw = str(path or "").strip()
        if not raw:
            return ""
        try:
            normalized = Path(raw).expanduser()
        except Exception:
            return ""
        try:
            normalized = normalized.resolve()
        except Exception:
            pass
        return self._source_key(normalized)

    # -------------------------
    # Defaults
    # -------------------------

    def _empty_library(self) -> Dict[str, Any]:
        return {
            "version": 2,
            "sources": [],
            "titles": [],
            "shows": [],
            "movies": [],
            "updated_at": None,
            "last_scan_at": 0,
            "last_successful_commit_at": 0,
            "last_repair_at": 0,
            "latest_errors": [],
            "quarantined": [],
            "ingestion": {
                "active": False,
                "status": "idle",
                "batch_id": "",
                "reason": "",
                "source_label": "",
                "candidate_count": 0,
                "imported_count": 0,
                "updated_count": 0,
                "skipped_duplicate_count": 0,
                "failed_count": 0,
                "worker_count": 0,
                "started_at": 0,
                "finished_at": 0,
                "elapsed_s": 0.0,
                "error": "",
            },
        }
