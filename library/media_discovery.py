"""Source-folder discovery and candidate grouping for Omega."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional

from .media_parser import VIDEO_EXTENSIONS, parse_media_path
from .metadata_provider_base import DisabledMetadataProvider, MetadataProvider, MetadataSearchResult, rank_metadata_results


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
    year: Optional[int] = None
    paths: List[str] = field(default_factory=list)
    episodes: List[DiscoveredEpisode] = field(default_factory=list)
    confidence: float = 0.0
    warnings: List[str] = field(default_factory=list)
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

    def discover(self, source_paths: Iterable[str | Path], *, limit: int = 400) -> List[DiscoveredMediaCandidate]:
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

        candidates = list(grouped.values())
        for candidate in candidates:
            candidate.episodes.sort(key=lambda ep: (ep.season or 999, ep.episode or 999, ep.path))
            self._attach_best_metadata(candidate)
            candidate.needs_review = candidate.confidence < 0.68 or bool(candidate.warnings)
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
            return
        if not ranked:
            return
        best = ranked[0]
        candidate.metadata_match = best
        candidate.confidence = max(candidate.confidence, best.confidence)
        candidate.selected_poster = best.poster_path
        if best.confidence < 0.72:
            candidate.warnings.append("Metadata match needs review.")

    @staticmethod
    def _candidate_id(media_type: str, title: str, year: Optional[int]) -> str:
        raw = f"{media_type}:{title.casefold()}:{year or ''}".encode("utf-8", errors="ignore")
        return hashlib.sha1(raw).hexdigest()[:16]
