"""Metadata provider interfaces for source discovery and editing."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import List, Optional, Protocol


@dataclass(frozen=True)
class MetadataSearchResult:
    provider: str
    provider_id: str
    title: str
    media_type: str
    year: Optional[int] = None
    overview: str = ""
    poster_path: str = ""
    confidence: float = 0.0


class MetadataProvider(Protocol):
    def is_available(self) -> bool:
        ...

    def search_show(self, title: str, year: Optional[int] = None) -> List[MetadataSearchResult]:
        ...

    def search_movie(self, title: str, year: Optional[int] = None) -> List[MetadataSearchResult]:
        ...

    def get_images(self, provider_id: str) -> List[str]:
        ...


class DisabledMetadataProvider:
    """Safe fallback when no online provider/API key is configured."""

    name = "disabled"

    def is_available(self) -> bool:
        return False

    def search_show(self, title: str, year: Optional[int] = None) -> List[MetadataSearchResult]:
        return []

    def search_movie(self, title: str, year: Optional[int] = None) -> List[MetadataSearchResult]:
        return []

    def get_images(self, provider_id: str) -> List[str]:
        return []


def rank_metadata_results(
    query_title: str,
    media_type: str,
    year: Optional[int],
    results: List[MetadataSearchResult],
) -> List[MetadataSearchResult]:
    ranked: List[MetadataSearchResult] = []
    query_norm = str(query_title or "").strip().casefold()
    for result in results:
        title_norm = str(result.title or "").strip().casefold()
        score = SequenceMatcher(None, query_norm, title_norm).ratio() if query_norm and title_norm else 0.0
        if result.media_type and str(result.media_type).casefold() == str(media_type).casefold():
            score += 0.06
        if year is not None and result.year is not None:
            score += 0.12 if int(year) == int(result.year) else -0.04
        ranked.append(
            MetadataSearchResult(
                provider=result.provider,
                provider_id=result.provider_id,
                title=result.title,
                media_type=result.media_type,
                year=result.year,
                overview=result.overview,
                poster_path=result.poster_path,
                confidence=max(0.0, min(1.0, score)),
            )
        )
    return sorted(ranked, key=lambda item: item.confidence, reverse=True)
