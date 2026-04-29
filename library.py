# =========================
# omega/library.py
# Library Manager + Scanner (Option B: library.json)
# =========================

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set


# ============================================================
# Data model
# ============================================================

@dataclass
class LibrarySource:
    """
    One source entry in Media/library.json.

    path:     Folder that contains shows (or contains Media/ or Shows/ etc.)
    enabled:  If false, we keep it but ignore it during scanning
    added_at: Unix timestamp when it was added
    label:    Optional friendly name (not required)
    """
    path: str
    enabled: bool = True
    added_at: int = 0
    label: str = ""

    def norm_path(self) -> str:
        """
        Normalize for comparisons:
        - expand user (~)
        - resolve if possible
        - casefold for Windows
        """
        try:
            p = Path(self.path).expanduser()
            try:
                p = p.resolve()
            except Exception:
                # If drive is disconnected, resolve() can fail.
                # absolute() still gives a stable string.
                p = p.absolute()
            return str(p).casefold()
        except Exception:
            return str(self.path).casefold()


# ============================================================
# Library Manager: reads/writes Media/library.json
# ============================================================

class LibraryManager:
    """
    Manages a JSON file:
      Media/library.json

    Format:
    {
      "version": 1,
      "sources": [
        {"path": "G:/TV Shows", "enabled": true, "added_at": 1700000000, "label": ""}
      ]
    }
    """

    def __init__(self, library_json_path: Path):
        self.library_json_path = Path(library_json_path)
        self._data: Dict[str, Any] = {"version": 1, "sources": []}

        # Load immediately so scanning works right away.
        self.load()

    def load(self) -> None:
        """Load library.json if it exists. If not, use defaults."""
        p = self.library_json_path
        if not p.exists():
            self._data = {"version": 1, "sources": []}
            return

        try:
            raw = p.read_text(encoding="utf-8", errors="ignore")
            obj = json.loads(raw) if raw.strip() else {}
            if not isinstance(obj, dict):
                raise ValueError("library.json root must be an object/dict")

            version = int(obj.get("version", 1))
            sources_obj = obj.get("sources", [])
            if not isinstance(sources_obj, list):
                sources_obj = []

            cleaned: List[Dict[str, Any]] = []
            for s in sources_obj:
                if not isinstance(s, dict):
                    continue
                path = str(s.get("path", "")).strip()
                if not path:
                    continue
                cleaned.append(
                    {
                        "path": path,
                        "enabled": bool(s.get("enabled", True)),
                        "added_at": int(s.get("added_at", 0) or 0),
                        "label": str(s.get("label", "") or ""),
                    }
                )

            self._data = {"version": version, "sources": cleaned}

        except Exception:
            # If JSON is corrupt, do NOT crash. Fall back safely.
            self._data = {"version": 1, "sources": []}

    def save(self) -> None:
        """
        Atomic-ish save:
        - write tmp
        - replace original
        prevents partial/corrupt writes on crash
        """
        p = self.library_json_path
        p.parent.mkdir(parents=True, exist_ok=True)

        tmp = p.with_suffix(".json.tmp")
        payload = json.dumps(self._data, indent=2, ensure_ascii=False)

        tmp.write_text(payload, encoding="utf-8")
        os.replace(str(tmp), str(p))

    # ----------------------------
    # Source helpers
    # ----------------------------

    def list_sources(self, enabled_only: bool = True) -> List[LibrarySource]:
        """Return sources as dataclasses (easy to use in controller)."""
        out: List[LibrarySource] = []
        for s in self._data.get("sources", []):
            try:
                src = LibrarySource(
                    path=str(s.get("path", "")),
                    enabled=bool(s.get("enabled", True)),
                    added_at=int(s.get("added_at", 0) or 0),
                    label=str(s.get("label", "") or ""),
                )
                if enabled_only and not src.enabled:
                    continue
                out.append(src)
            except Exception:
                continue
        return out

    def has_source(self, path: str) -> bool:
        """True if path already exists (normalized compare)."""
        needle = LibrarySource(path=str(path)).norm_path()
        for src in self.list_sources(enabled_only=False):
            if src.norm_path() == needle:
                return True
        return False

    def add_source(self, path: str, label: str = "") -> bool:
        """
        Add a new path if it isn't already in the file.
        Returns True if added, False if it already existed.
        """
        path = str(path).strip()
        if not path:
            return False

        if self.has_source(path):
            return False

        entry = {
            "path": path,
            "enabled": True,
            "added_at": int(time.time()),
            "label": str(label or ""),
        }
        self._data.setdefault("sources", []).append(entry)
        self.save()
        return True

    def set_enabled(self, path: str, enabled: bool) -> None:
        """Enable/disable an existing source."""
        needle = LibrarySource(path=str(path)).norm_path()
        for s in self._data.get("sources", []):
            try:
                sp = str(s.get("path", ""))
                if LibrarySource(path=sp).norm_path() == needle:
                    s["enabled"] = bool(enabled)
            except Exception:
                continue
        self.save()

    def remove_source(self, path: str) -> bool:
        """Remove a source completely. Returns True if removed."""
        needle = LibrarySource(path=str(path)).norm_path()
        before = len(self._data.get("sources", []))

        kept: List[Dict[str, Any]] = []
        for s in self._data.get("sources", []):
            try:
                sp = str(s.get("path", ""))
                if LibrarySource(path=sp).norm_path() == needle:
                    continue
                kept.append(s)
            except Exception:
                kept.append(s)

        self._data["sources"] = kept
        after = len(kept)

        if after != before:
            self.save()
            return True
        return False


# ============================================================
# Scanner: turns sources into actual show folders
# ============================================================

class LibraryScanner:
    """
    Takes library sources and converts them into "show folders".

    Your controller already expects show folders to be:
      <Show Name>/
        Season 1/
        poster.jpg
        etc.
    """

    def __init__(self, video_exts: Set[str]):
        self.video_exts = {e.lower() for e in set(video_exts)}

    # ----------------------------
    # Folder type heuristics
    # ----------------------------

    def looks_like_media_root(self, p: Path) -> bool:
        """Media root typically contains Shows/ or Movies/."""
        if not p.exists() or not p.is_dir():
            return False
        return (p / "Shows").exists() or (p / "Movies").exists()

    def looks_like_shows_container(self, p: Path) -> bool:
        """
        A "container" where each child folder is a show.
        Examples:
          - Media/Shows
          - G:/TV Shows
        """
        if not p.exists() or not p.is_dir():
            return False

        if p.name.casefold() == "shows":
            return True

        try:
            dirs = [x for x in p.iterdir() if x.is_dir() and not x.name.startswith(".")]
            return len(dirs) >= 1
        except Exception:
            return False

    def looks_like_show_folder(self, p: Path) -> bool:
        """
        A "show folder" typically contains Season folders,
        OR contains video files somewhere inside.
        """
        if not p.exists() or not p.is_dir():
            return False

        # Season folder clues
        try:
            for ch in p.iterdir():
                if not ch.is_dir():
                    continue
                nm = ch.name.casefold()
                if "season" in nm:
                    return True
                if re.fullmatch(r"s\d{1,2}", nm):
                    return True
        except Exception:
            pass

        # Any video file anywhere inside
        try:
            for vid in p.rglob("*"):
                if vid.is_file() and vid.suffix.lower() in self.video_exts:
                    return True
        except Exception:
            pass

        return False

    # ----------------------------
    # Convert a selected root into show folders
    # ----------------------------

    def iter_show_folders_from_root(self, root: Path) -> Iterable[Path]:
        """
        Convert any user-picked path into real show folders.

        We never treat container folders like "Shows" themselves as shows.
        We always yield the children show folders.
        """
        root = root.expanduser()
        if not root.exists():
            return

        # A) Root is a Media folder that contains Shows/
        if self.looks_like_media_root(root):
            shows = root / "Shows"
            if shows.exists() and shows.is_dir():
                for p in sorted(shows.iterdir()):
                    if p.is_dir() and not p.name.startswith("."):
                        yield p
            return

        # B) Root is Media/Shows (container)
        if root.name.casefold() == "shows":
            for p in sorted(root.iterdir()):
                if p.is_dir() and not p.name.startswith("."):
                    yield p
            return

        # C) Root is directly a show folder
        if self.looks_like_show_folder(root):
            yield root
            return

        # D) Root is a container where each child is a show folder
        if self.looks_like_shows_container(root):
            for p in sorted(root.iterdir()):
                if p.is_dir() and not p.name.startswith(".") and self.looks_like_show_folder(p):
                    yield p
            return

    def gather_all_show_folders(self, canonical_shows_dir: Path, sources: List[str]) -> List[Path]:
        """
        Combine:
          - Media/Shows/<Show Name> (canonical)
          - every enabled source from library.json
        De-dupe by best-effort resolved path.
        """
        show_dirs: List[Path] = []

        # 1) Canonical
        if canonical_shows_dir.exists() and canonical_shows_dir.is_dir():
            for p in sorted(canonical_shows_dir.iterdir()):
                if p.is_dir() and not p.name.startswith("."):
                    show_dirs.append(p)

        # 2) External sources
        for s in sources:
            try:
                src = Path(str(s))
            except Exception:
                continue
            for sd in self.iter_show_folders_from_root(src):
                show_dirs.append(sd)

        # De-duplicate
        seen = set()
        unique: List[Path] = []
        for p in show_dirs:
            try:
                key = str(p.resolve()).casefold()
            except Exception:
                key = str(p.absolute()).casefold()
            if key in seen:
                continue
            seen.add(key)
            unique.append(p)

        return unique


# ============================================================
# Optional one-time migration from old sources.txt to library.json
# ============================================================

def migrate_sources_txt_to_library_json(sources_txt: Path, library_json: Path) -> Optional[str]:
    """
    If you previously used Media/sources.txt, copy those paths into Media/library.json.

    Safe behavior:
      - does NOT delete sources.txt
      - just imports it
    """
    sources_txt = Path(sources_txt)
    if not sources_txt.exists():
        return None

    try:
        lines = sources_txt.read_text(encoding="utf-8", errors="ignore").splitlines()
        paths: List[str] = []
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            paths.append(line)

        if not paths:
            return None

        mgr = LibraryManager(Path(library_json))
        added = 0
        for p in paths:
            if mgr.add_source(p):
                added += 1

        return f"Migrated {added} path(s) from sources.txt into library.json."
    except Exception as e:
        return f"Migration failed: {type(e).__name__}: {e}"
