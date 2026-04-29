from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


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

        # In-memory library data
        self._data: Dict[str, Any] = {}

        # Ensure directories exist (first run safety)
        self.paths.media_dir.mkdir(parents=True, exist_ok=True)
        self.paths.shows_dir.mkdir(parents=True, exist_ok=True)
        self.paths.movies_dir.mkdir(parents=True, exist_ok=True)
        self.paths.config_dir.mkdir(parents=True, exist_ok=True)

        # Load/create library.json
        self.load_or_init()

    # -------------------------
    # Load / Save
    # -------------------------

    def load_or_init(self) -> Dict[str, Any]:
        """
        Load Media/library.json if present; otherwise initialize defaults.
        Always guarantees required keys exist.
        """
        if self.paths.library_json.exists():
            try:
                self._data = json.loads(self.paths.library_json.read_text(encoding="utf-8"))
            except Exception:
                # Corrupt JSON shouldn't brick the app.
                self._data = self._empty_library()
        else:
            self._data = self._empty_library()

        self._data.setdefault("version", 1)
        self._data.setdefault("sources", [])
        self._data.setdefault("shows", [])
        self._data.setdefault("movies", [])
        self._data.setdefault("updated_at", None)

        return self._data

    def save(self) -> None:
        """Persist in-memory library to Media/library.json."""
        self.paths.library_json.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # -------------------------
    # Sources API (what controller.py expects)
    # -------------------------

    def list_sources(self, enabled_only: bool = True) -> List[LibrarySource]:
        """
        Return sources as LibrarySource objects (with .path and .enabled).
        """
        raw = self._data.get("sources", [])
        sources: List[LibrarySource] = []

        # Support both formats:
        # 1) ["C:\\path1", "D:\\path2"]
        # 2) [{"path":"C:\\path1","enabled":true}, ...]
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, str):
                    p = Path(item)
                    sources.append(LibrarySource(path=p, enabled=True))
                elif isinstance(item, dict):
                    p = Path(item.get("path", "")).expanduser()
                    enabled = bool(item.get("enabled", True))
                    if str(p).strip():
                        sources.append(LibrarySource(path=p, enabled=enabled))

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
            payload.append({"path": str(Path(s.path).expanduser()), "enabled": bool(s.enabled)})

        self._data["sources"] = payload
        self.save()

        # Also mirror to config/sources.json for convenience/legacy tools
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
        current = self.list_sources(enabled_only=False)
        seen_keys = {self._source_key(src.path) for src in current}
        added: List[Path] = []
        duplicates: List[Path] = []
        invalid: List[str] = []

        for raw_path in paths or []:
            normalized = self._normalize_source_path(raw_path)
            if normalized is None:
                invalid.append(str(raw_path or ""))
                continue

            key = self._source_key(normalized)
            if key in seen_keys:
                duplicates.append(normalized)
                continue

            seen_keys.add(key)
            current.append(LibrarySource(path=normalized, enabled=bool(enabled)))
            added.append(normalized)

        if added:
            self.set_sources(current)

        return added, duplicates, invalid

    def set_source_enabled(self, path: object, enabled: bool) -> bool:
        """
        Enable or disable an existing source.

        Returns True when a stored source changed state.
        """
        wanted = self._source_key_from_unknown(path)
        if not wanted:
            return False

        current = self.list_sources(enabled_only=False)
        changed = False
        for src in current:
            if self._source_key(src.path) != wanted:
                continue
            desired = bool(enabled)
            if bool(src.enabled) != desired:
                src.enabled = desired
                changed = True

        if changed:
            self.set_sources(current)
        return changed

    def remove_source(self, path: object) -> bool:
        """
        Remove an existing source.

        Returns True when a stored source was removed.
        """
        wanted = self._source_key_from_unknown(path)
        if not wanted:
            return False

        current = self.list_sources(enabled_only=False)
        kept = [src for src in current if self._source_key(src.path) != wanted]
        if len(kept) == len(current):
            return False

        self.set_sources(kept)
        return True

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

        """
        Best-practice behavior:
        If there are NO sources at all, automatically add the local Media folder
        (and/or Shows folder) so Home isn't blank on fresh installs.

        Returns True if it added something.
        """
        current = self.list_sources(enabled_only=False)
        if current:
            return False

        # Default: use Media/Shows as a "source root" (matches your app structure)
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
            "version": 1,
            "sources": [],
            "shows": [],
            "movies": [],
            "updated_at": None,
        }
