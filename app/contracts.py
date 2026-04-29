# omega/app/contracts.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, List, Tuple, Any


# ============================================================
# App-wide “contract” types
# These types create clean boundaries between modules.
# ============================================================

@dataclass(frozen=True)
class ShowGroup:
    """
    One logical media card.

    A card can represent multiple physical folders (merged sources).
    Example:
      - D:/TV/ShowName
      - G:/Backup/ShowName

    Additional optional fields support richer Home rails and metadata-driven UX.
    """
    display_title: str
    primary_dir: Path
    poster_path: Optional[Path]
    group_mtime: float
    all_dirs: List[Path]

    media_type: str = "tv"  # "tv" or "movie"
    play_path: Optional[Path] = None
    content_key: str = ""

    year: Optional[int] = None
    genres: Tuple[str, ...] = ()
    overview: str = ""
    rating: Optional[float] = None

    tmdb_id: Optional[int] = None
    tmdb_media_type: str = ""
    backdrop_path: Optional[Path] = None
    classification_reason: str = ""
    episode_paths: Tuple[Path, ...] = ()

@dataclass(frozen=True)
class EpisodeRef:
    """
    One playable episode entry, paired with the show root it belongs to.
    We keep show_root_dir because thumbnail caching needs it.
    """
    show_root_dir: Path
    episode_path: Path


def safe_path(p: Any) -> Path:
    """
    Convert "whatever" into a Path safely.
    """
    try:
        return Path(str(p))
    except Exception:
        return Path()

