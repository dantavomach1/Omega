from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional, Set


@dataclass(frozen=True)
class DiscoveredShow:
    """
    A discovered show folder.

    We keep this small and boring on purpose:
    - No Qt imports
    - No player imports
    - No UI knowledge
    """
    path: Path


class LibraryScanner:
    """
    Responsible for discovering show folders from a set of library sources.

    Controller needs two capabilities:
    1) iter_show_folders_from_root(root) -> yields show folders found under that root
    2) gather_all_show_folders(default_shows_dir, sources) -> returns merged, de-duped list

    Design rule:
    - The scanner *never* assumes UI layout or user preferences.
    - It tries to be conservative (avoid false positives).
    """

    def __init__(self, video_exts: Optional[Set[str]] = None) -> None:
        # Example: {".mkv", ".mp4", ...}
        self.video_exts: Set[str] = set(x.lower() for x in (video_exts or set()))

    # ============================================================
    # Public API (used by controller.py)
    # ============================================================

    def gather_all_show_folders(self, default_shows_dir: Path, sources: List[Path]) -> List[Path]:
        """
        Merge shows discovered from:
        - the app's default Media/Shows folder
        - any user-added sources

        Returns a stable, de-duped list of show folder Paths.
        """
        candidates: List[Path] = []

        # 1) Always include Media/Shows (your original behavior)
        if default_shows_dir and default_shows_dir.exists() and default_shows_dir.is_dir():
            candidates.extend(list(self.iter_show_folders_from_root(default_shows_dir)))

        # 2) Include user sources (can be a "TV Shows" folder OR a show folder)
        for src in sources or []:
            if not src:
                continue
            p = Path(src)
            if not p.exists() or not p.is_dir():
                continue
            candidates.extend(list(self.iter_show_folders_from_root(p)))

        # 3) De-dupe with canonical absolute path (Windows-safe)
        seen: Set[str] = set()
        out: List[Path] = []
        for p in candidates:
            try:
                key = str(p.resolve()).casefold()
            except Exception:
                key = str(p.absolute()).casefold()

            if key in seen:
                continue
            seen.add(key)
            out.append(p)

        return out

    def iter_show_folders_from_root(self, root: Path) -> Iterator[Path]:
        """
        Given a root folder, yield show folders.

        We support common structures:
        A) Root is a "TV Shows" style folder:
           root/
             Show A/
               Season 1/
               Season 2/
             Show B/
               Season 1/
        B) Root is directly a show folder:
           root/
             Season 1/
             Season 2/
        C) Flat episode-only folders are handled later by the catalog as
           explicit loose-episode bundles.

        Conservative rule:
        - A folder is considered a "show folder" if it contains at least one season folder,
          while direct loose files are grouped by episode filename at catalog time.
        """
        root = Path(root)

        # If root itself looks like a show folder, yield it and stop
        if self._is_show_folder(root):
            yield root
            return

        # Otherwise, treat root as a container and scan one level down
        try:
            children = [p for p in root.iterdir() if p.is_dir()]
        except Exception:
            children = []

        # Try each child as a potential show folder
        for child in children:
            if self._is_show_folder(child):
                yield child
                continue

            # If it's not a show folder, it might be another container (e.g., "TV Shows/Anime/")
            # We scan one more level down, but keep it shallow to avoid huge slow scans.
            try:
                grandkids = [p for p in child.iterdir() if p.is_dir()]
            except Exception:
                grandkids = []

            for g in grandkids:
                if self._is_show_folder(g):
                    yield g

    # ============================================================
    # Internal helpers
    # ============================================================

    def _is_show_folder(self, p: Path) -> bool:
        """
        Decide if folder p is a show folder.

        Heuristic:
        1) Has at least one season-like subfolder
        """
        if not p.exists() or not p.is_dir():
            return False

        # 1) season-like subfolders
        if self._has_season_subfolder(p):
            return True

        return False

    def _has_season_subfolder(self, show_dir: Path) -> bool:
        """
        Look for common season folder patterns.
        """
        try:
            for sub in show_dir.iterdir():
                if not sub.is_dir():
                    continue
                name = sub.name.strip().casefold()

                # Season 1, Season_01, Season-2, etc.
                if name.startswith("season"):
                    return True

                # S01, s1, s02, etc.
                if len(name) in (2, 3) and name.startswith("s") and name[1:].isdigit():
                    return True

                # "Season 01 Extras" etc: startswith covers it, but keep tolerant
                if "season" in name and any(ch.isdigit() for ch in name):
                    return True
        except Exception:
            return False

        return False
