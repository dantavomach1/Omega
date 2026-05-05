"""Filename parsing for Omega source discovery.

The parser is deliberately dependency-free. It borrows the same idea used by
projects such as guessit: strip release noise first, then infer media shape from
the remaining title/year/episode tokens.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


VIDEO_EXTENSIONS = {
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".ts",
    ".webm",
    ".wmv",
    ".avi",
}

_NOISE_PATTERNS = (
    r"\b(?:480p|720p|1080p|2160p|4320p|4k|8k)\b",
    r"\b(?:x264|x265|h\.?264|h\.?265|hevc|avc|aac|dts|dts-?hd|ac3|eac3|truehd|atmos)\b",
    r"\b(?:web-?dl|web-?rip|bluray|blu-?ray|brrip|hdrip|dvdrip|hdtv|remux)\b",
    r"\b(?:hdr10?|dv|dolby[ ._-]?vision|sdr|10bit|8bit)\b",
    r"\b(?:proper|repack|extended|unrated|limited|internal|rerip)\b",
)
_BRACKETED = re.compile(r"[\[(][^\])]*(?:720p|1080p|2160p|4k|x264|x265|hevc|web|bluray|hdr|aac|dts)[^\])]*[\])]", re.I)
_YEAR = re.compile(r"(?:^|[\s._(-])((?:19|20)\d{2})(?:$|[\s._)-])")
_SXXEYY = re.compile(r"\b[Ss](\d{1,2})[\s._-]*[Ee](\d{1,3})\b")
_ONE_X_TWO = re.compile(r"\b(\d{1,2})x(\d{1,3})\b", re.I)
_SEASON_EPISODE = re.compile(r"\bseason[\s._-]*(\d{1,2}).{0,20}?episode[\s._-]*(\d{1,3})\b", re.I)
_EPISODE_ONLY = re.compile(r"\b(?:ep(?:isode)?|e)[\s._-]*(\d{1,3})\b", re.I)
_SEASON_DIR = re.compile(r"\bseason[\s._-]*(\d{1,2})\b|\bS(\d{1,2})\b", re.I)


@dataclass(frozen=True)
class MediaParseResult:
    raw_path: str
    media_type: str
    cleaned_title: str
    year: Optional[int] = None
    season: Optional[int] = None
    episode: Optional[int] = None
    episode_title: str = ""
    confidence: float = 0.0
    warnings: List[str] = field(default_factory=list)


def _collapse(text: str) -> str:
    cleaned = re.sub(r"[._]+", " ", str(text or ""))
    cleaned = re.sub(r"\s*-\s*", " - ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" -._")


def clean_media_title(raw: str) -> str:
    text = str(raw or "")
    text = _BRACKETED.sub(" ", text)
    text = re.sub(r"\[[^\]]+\]|\([^\)]*\)$", " ", text)
    text = text.replace("_", " ").replace(".", " ")
    for pattern in _NOISE_PATTERNS:
        text = re.sub(pattern, " ", text, flags=re.I)
    text = re.sub(r"\b(?:rarbg|yts|ettv|eztv|ntb|successfulcrab|ion10)\b", " ", text, flags=re.I)
    text = re.sub(r"-\s*[A-Za-z0-9]{2,18}$", " ", text)
    text = re.sub(r"\s+", " ", text)
    return _collapse(text)


def _find_season_episode(name: str) -> tuple[Optional[int], Optional[int], str]:
    for pattern in (_SXXEYY, _ONE_X_TWO, _SEASON_EPISODE):
        match = pattern.search(name)
        if match:
            return int(match.group(1)), int(match.group(2)), name[: match.start()] + " " + name[match.end() :]
    match = _EPISODE_ONLY.search(name)
    if match:
        return None, int(match.group(1)), name[: match.start()] + " " + name[match.end() :]
    return None, None, name


def _season_from_parents(path: Path) -> Optional[int]:
    for parent in path.parents:
        match = _SEASON_DIR.search(parent.name)
        if match:
            value = match.group(1) or match.group(2)
            try:
                return int(value)
            except Exception:
                return None
    return None


def parse_media_path(path: str | Path) -> MediaParseResult:
    p = Path(path)
    warnings: List[str] = []
    stem = p.stem if p.suffix.lower() in VIDEO_EXTENSIONS else p.name
    season, episode, remainder = _find_season_episode(stem)
    if season is None and episode is not None:
        season = _season_from_parents(p)

    year = None
    year_match = _YEAR.search(stem)
    if year_match:
        try:
            year = int(year_match.group(1))
        except Exception:
            year = None

    title_source = remainder
    if season is not None or episode is not None:
        parent_title = ""
        for parent in p.parents:
            if parent.name and not _SEASON_DIR.search(parent.name):
                parent_title = parent.name
                break
        if parent_title:
            title_source = parent_title

    title = clean_media_title(title_source)
    if year is not None:
        title = clean_media_title(re.sub(rf"\b{year}\b", " ", title))

    episode_title = ""
    if episode is not None:
        parts = re.split(r"\s+-\s+", clean_media_title(remainder), maxsplit=1)
        if len(parts) == 2:
            episode_title = clean_media_title(parts[1])

    media_type = "episode" if episode is not None else "movie"
    confidence = 0.72
    if not title:
        title = clean_media_title(p.parent.name if p.parent.name else stem)
        warnings.append("Title needed parent-folder fallback.")
        confidence = 0.42
    if media_type == "episode" and season is None:
        warnings.append("Episode number found without a season number.")
        confidence = min(confidence, 0.55)
    if year is not None:
        confidence = min(0.94, confidence + 0.08)

    return MediaParseResult(
        raw_path=str(p),
        media_type=media_type,
        cleaned_title=title,
        year=year,
        season=season,
        episode=episode,
        episode_title=episode_title,
        confidence=confidence,
        warnings=warnings,
    )
