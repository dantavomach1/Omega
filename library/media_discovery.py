"""Source-folder discovery and candidate grouping for Omega."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from .media_parser import VIDEO_EXTENSIONS, parse_media_path
from .metadata_provider_base import DisabledMetadataProvider, MetadataProvider, MetadataSearchResult, rank_metadata_results
from omega.app.text_naming import NameCleaner


@dataclass(frozen=True)
class DiscoveredEpisode:
    path: str
    season: Optional[int]
    episode: Optional[int]
    title: str = ""


@dataclass
class DiscoveredMediaCandidate:
    candidate_id: str
    media_type: str
    title: str
    source_path: str = ""
    year: Optional[int] = None
    paths: List[str] = field(default_factory=list)
    episodes: List[DiscoveredEpisode] = field(default_factory=list)
    confidence: float = 0.0
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    existing_title_match: str = ""
    existing_title_id: str = ""
    status: str = "discovering"
    metadata_match: Optional[MetadataSearchResult] = None
    selected_poster: str = ""
    needs_review: bool = False

    @property
    def file_count(self) -> int:
        return len(self.paths)

    @property
    def episode_count(self) -> int:
        return len(self.episodes)


class MediaDiscoveryService:
    def __init__(self, metadata_provider: Optional[MetadataProvider] = None) -> None:
        self.metadata_provider = metadata_provider or DisabledMetadataProvider()

    def discover(
        self,
        source_paths: Iterable[str | Path],
        *,
        limit: int = 400,
        known_titles: Optional[Sequence[object]] = None,
    ) -> List[DiscoveredMediaCandidate]:
        known_index = self._known_title_index(known_titles or [])
        parses = []
        for source in source_paths:
            root = Path(source)
            if not root.exists():
                continue
            files = [root] if root.is_file() else root.rglob("*")
            for path in files:
                try:
                    if len(parses) >= int(limit):
                        break
                    if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS:
                        parses.append(parse_media_path(path))
                except Exception:
                    continue

        grouped: dict[tuple[str, str, Optional[int]], DiscoveredMediaCandidate] = {}
        for parsed in parses:
            group_type = "show" if parsed.media_type == "episode" else "movie"
            key = (group_type, parsed.cleaned_title.casefold(), parsed.year)
            if key not in grouped:
                grouped[key] = DiscoveredMediaCandidate(
                    candidate_id=self._candidate_id(group_type, parsed.cleaned_title, parsed.year),
                    media_type=group_type,
                    title=parsed.cleaned_title,
                    source_path=str(Path(parsed.raw_path).parent),
                    year=parsed.year,
                )
            candidate = grouped[key]
            candidate.paths.append(parsed.raw_path)
            candidate.confidence = max(candidate.confidence, parsed.confidence)
            candidate.warnings.extend(w for w in parsed.warnings if w not in candidate.warnings)
            if parsed.media_type == "episode":
                candidate.episodes.append(
                    DiscoveredEpisode(
                        path=parsed.raw_path,
                        season=parsed.season,
                        episode=parsed.episode,
                        title=parsed.episode_title,
                    )
                )
            match = known_index.get(self._match_key(candidate.media_type, candidate.title, candidate.year))
            if match is not None:
                candidate.existing_title_match = match.get("display_title", "")
                candidate.existing_title_id = match.get("title_id", "")

        candidates = list(grouped.values())
        for candidate in candidates:
            candidate.episodes.sort(key=lambda ep: (ep.season or 999, ep.episode or 999, ep.path))
            self._attach_best_metadata(candidate)
            candidate.needs_review = candidate.confidence < 0.68 or bool(candidate.warnings) or bool(candidate.errors)
            if candidate.existing_title_id:
                candidate.status = "partial"
            elif candidate.needs_review:
                candidate.status = "metadata_pending" if candidate.metadata_match is None else "art_pending"
            else:
                candidate.status = "ready"
        return sorted(candidates, key=lambda item: (item.needs_review, item.media_type, item.title.casefold()))

    def _attach_best_metadata(self, candidate: DiscoveredMediaCandidate) -> None:
        provider = self.metadata_provider
        try:
            if not provider.is_available():
                return
            if candidate.media_type == "show":
                results = provider.search_show(candidate.title, candidate.year)
            else:
                results = provider.search_movie(candidate.title, candidate.year)
            ranked = rank_metadata_results(candidate.title, candidate.media_type, candidate.year, list(results or []))
        except Exception:
            candidate.errors.append("Metadata lookup failed.")
            return
        if not ranked:
            return
        best = ranked[0]
        candidate.metadata_match = best
        candidate.confidence = max(candidate.confidence, best.confidence)
        candidate.selected_poster = best.poster_path
        if best.confidence < 0.72:
            candidate.warnings.append("Metadata match needs review.")

    def _known_title_index(self, known_titles: Sequence[object]) -> dict[str, dict[str, str]]:
        out: dict[str, dict[str, str]] = {}
        for raw in known_titles or []:
            title = ""
            media_type = "movie"
            year = None
            title_id = ""
            if isinstance(raw, dict):
                title = str(raw.get("display_title") or raw.get("title") or "").strip()
                media_type = str(raw.get("media_type") or "movie").strip().casefold()
                year = raw.get("year")
                title_id = str(raw.get("title_id") or "").strip()
            else:
                title = str(getattr(raw, "display_title", "") or getattr(raw, "title", "") or "").strip()
                media_type = str(getattr(raw, "media_type", "movie") or "movie").strip().casefold()
                year = getattr(raw, "year", None)
                title_id = str(getattr(raw, "title_id", "") or "").strip()

            if media_type not in {"movie", "show", "tv"}:
                media_type = "movie"
            if media_type == "tv":
                media_type = "show"
            try:
                year = int(year) if year is not None and str(year).strip() else None
            except Exception:
                year = None

            key = self._match_key(media_type, title, year)
            if not key:
                continue
            out[key] = {
                "display_title": title,
                "title_id": title_id,
            }
        return out

    def _match_key(self, media_type: str, title: str, year: Optional[int]) -> str:
        cleaned = NameCleaner.clean(str(title or "")) or str(title or "")
        cleaned = " ".join(part for part in cleaned.replace("_", " ").replace(".", " ").replace("-", " ").split() if part)
        if not cleaned:
            return ""
        norm_type = str(media_type or "").strip().casefold()
        if norm_type == "tv":
            norm_type = "show"
        return f"{norm_type}|{cleaned.casefold()}|{year or ''}"

    @staticmethod
    def _candidate_id(media_type: str, title: str, year: Optional[int]) -> str:
        raw = f"{media_type}:{title.casefold()}:{year or ''}".encode("utf-8", errors="ignore")
        return hashlib.sha1(raw).hexdigest()[:16]
