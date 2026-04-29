# omega/media_scan.py

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".mov", ".m4v", ".webm"}
IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".jfif", ".tbn"}


@dataclass
class MediaItem:
    title: str
    path: Path


def is_video_file(p: Path) -> bool:
    try:
        return p.is_file() and p.suffix.lower() in VIDEO_EXTS
    except Exception:
        return False


def _has_any_video(folder: Path, max_depth: int = 3) -> bool:
    """
    True if folder contains any video file within max_depth.
    max_depth=0 means only direct files.
    """
    try:
        base = len(folder.parts)
        for p in folder.rglob("*"):
            if not p.is_file():
                continue
            depth = len(p.parts) - base
            if depth > max_depth:
                continue
            if p.suffix.lower() in VIDEO_EXTS:
                return True
        return False
    except Exception:
        return False


def find_poster_in_folder(folder: Path) -> Optional[Path]:
    """
    Find a representative image for a show folder.
    Priority:
      1) common exact names
      2) common keywords in filename
      3) any image in folder
      4) one-level artwork subfolders
    """
    if not folder or not folder.exists() or not folder.is_dir():
        return None

    preferred = [
        "poster.jpg", "poster.jpeg", "poster.png", "poster.webp", "poster.tbn",
        "folder.jpg", "folder.png", "folder.tbn",
        "cover.jpg", "cover.png", "cover.webp", "cover.tbn",
        "fanart.jpg", "fanart.png", "fanart.webp",
        "backdrop.jpg", "backdrop.png", "background.jpg", "background.png",
        "thumb.jpg", "thumb.png", "thumbnail.jpg", "thumbnail.png",
    ]
    for name in preferred:
        p = folder / name
        if p.exists() and p.is_file():
            return p

    keywords = ("poster", "folder", "cover", "fanart", "backdrop", "background", "thumb", "banner", "keyart")

    def score(p: Path) -> int:
        n = p.name.lower()
        s = 0
        if any(k in n for k in keywords):
            s += 50
        if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
            s += 10
        if p.suffix.lower() == ".tbn":
            s += 5
        return s

    # root images
    imgs = []
    try:
        for p in folder.iterdir():
            if p.is_file() and p.suffix.lower() in IMG_EXTS:
                imgs.append(p)
    except Exception:
        imgs = []

    if imgs:
        imgs.sort(key=score, reverse=True)
        return imgs[0]

    # common art subfolders one level
    art_dirs = {"art", "artwork", "images", "posters", "poster", "thumbs", "fanart", "backgrounds"}
    try:
        for d in folder.iterdir():
            if d.is_dir() and d.name.lower() in art_dirs:
                imgs2 = [p for p in d.iterdir() if p.is_file() and p.suffix.lower() in IMG_EXTS]
                if imgs2:
                    imgs2.sort(key=score, reverse=True)
                    return imgs2[0]
    except Exception:
        pass

    return None


def scan_media_folders(folders: list[Path]) -> list[MediaItem]:
    items: list[MediaItem] = []
    seen = set()

    for folder in folders:
        if not folder.exists():
            continue
        try:
            for p in sorted(folder.rglob("*")):
                if is_video_file(p):
                    k = str(p).lower()
                    if k in seen:
                        continue
                    seen.add(k)
                    items.append(MediaItem(title=p.stem, path=p))
        except Exception:
            continue

    return items


def _child_show_candidates(root: Path, limit: int = 160) -> list[Path]:
    """
    Return child directories that look like show folders:
    immediate child dirs that contain at least one video within depth 3.
    """
    out: list[Path] = []
    try:
        kids = [p for p in root.iterdir() if p.is_dir()]
        kids.sort(key=lambda x: x.name.lower())
        for d in kids:
            if _has_any_video(d, max_depth=3):
                out.append(d)
                if len(out) >= limit:
                    break
    except Exception:
        pass
    return out


def scan_shows_from_sources(sources: list[Path], limit: int = 160) -> list[dict]:
    """
    Smart show scan:
      - If source itself looks like a show folder (has videos under it),
        treat it as ONE show.
      - Else treat it as a library root and take child show folders.
    Returns list of dicts: {"title","folder","poster","subtitle"}.
    """
    shows: list[dict] = []
    seen_folders = set()

    for src in sources:
        try:
            src = Path(src)
        except Exception:
            continue
        if not src.exists() or not src.is_dir():
            continue

        # Decide: show folder vs library root
        # If src contains videos, it can still be a library root,
        # but most TV libraries have videos inside show dirs, not in root.
        # So: if it has many child show candidates -> treat as library root.
        child_candidates = _child_show_candidates(src, limit=limit)
        if child_candidates:
            # Library root
            for show_dir in child_candidates:
                key = str(show_dir.resolve()).lower()
                if key in seen_folders:
                    continue
                seen_folders.add(key)

                poster = find_poster_in_folder(show_dir)
                shows.append({
                    "title": show_dir.name,
                    "folder": str(show_dir),
                    "poster": str(poster) if poster else None,
                    "subtitle": "",
                })
                if len(shows) >= limit:
                    return shows
            continue

        # No child show candidates -> treat src as a show folder if it has videos
        if _has_any_video(src, max_depth=6):
            key = str(src.resolve()).lower()
            if key in seen_folders:
                continue
            seen_folders.add(key)

            poster = find_poster_in_folder(src)
            shows.append({
                "title": src.name,
                "folder": str(src),
                "poster": str(poster) if poster else None,
                "subtitle": "",
            })
            if len(shows) >= limit:
                return shows

    return shows
