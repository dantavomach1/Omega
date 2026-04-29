# omega/library/tmdb_client.py
from __future__ import annotations

import os
import json
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from urllib.request import Request, urlopen
from urllib.parse import quote_plus


@dataclass
class TMDBHit:
    """
    A single search hit from TMDB.
    We keep both:
      - poster_path (vertical)
      - backdrop_path (horizontal/wide)
    """
    id: int
    media_type: str           # "tv" or "movie"
    title: str
    year: str
    poster_path: Optional[str] = None
    backdrop_path: Optional[str] = None


class TMDBClient:
    """
    Minimal TMDB v3 client using a v4 Read Access Token (Bearer).
    - No external dependencies
    - Uses urllib only
    """

    API_BASE = "https://api.themoviedb.org/3"
    IMG_BASE = "https://image.tmdb.org/t/p"

    def __init__(self, read_token_env: str = "TMDB_READ_TOKEN") -> None:
        self._token = os.environ.get(read_token_env, "").strip()
        if not self._token:
            raise RuntimeError(
                f"Missing TMDB read token. Set environment variable: {read_token_env}"
            )

    # -----------------------------
    # Low-level JSON GET helper
    # -----------------------------
    def _get_json(self, url: str) -> Dict[str, Any]:
        req = Request(
            url,
            headers={
                "accept": "application/json",
                "Authorization": f"Bearer {self._token}",
            },
        )
        with urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw)

    # -----------------------------
    # Search: multi (tv + movie)
    # -----------------------------
    def search_multi(self, query: str, limit: int = 12) -> List[TMDBHit]:
        """
        Uses /search/multi and filters to tv/movie only.
        """
        q = quote_plus(query.strip())
        url = f"{self.API_BASE}/search/multi?query={q}&include_adult=false&language=en-US&page=1"
        data = self._get_json(url)

        out: List[TMDBHit] = []

        for r in data.get("results", []):
            mt = str(r.get("media_type") or "")
            if mt not in ("tv", "movie"):
                continue

            tmdb_id = int(r.get("id") or 0)
            if tmdb_id <= 0:
                continue

            poster_path = r.get("poster_path") or None
            backdrop_path = r.get("backdrop_path") or None

            if mt == "tv":
                title = str(r.get("name") or r.get("original_name") or "").strip()
                date = str(r.get("first_air_date") or "")
            else:
                title = str(r.get("title") or r.get("original_title") or "").strip()
                date = str(r.get("release_date") or "")

            year = date[:4] if len(date) >= 4 else ""

            if not title:
                continue

            out.append(
                TMDBHit(
                    id=tmdb_id,
                    media_type=mt,
                    title=title,
                    year=year,
                    poster_path=poster_path,
                    backdrop_path=backdrop_path,
                )
            )

            if len(out) >= int(limit):
                break

        return out

    def get_item_details(self, media_type: str, tmdb_id: int) -> Dict[str, Any]:
        """
        Fetch details for a TMDB item.

        Returns a normalized payload suitable for app-level metadata enrichment.
        """
        mt = str(media_type or "").strip().casefold()
        if mt not in ("movie", "tv"):
            raise ValueError(f"Unsupported media_type: {media_type}")

        endpoint = "movie" if mt == "movie" else "tv"
        url = f"{self.API_BASE}/{endpoint}/{int(tmdb_id)}?language=en-US"
        data = self._get_json(url)

        if mt == "movie":
            title = str(data.get("title") or data.get("original_title") or "").strip()
            date = str(data.get("release_date") or "")
        else:
            title = str(data.get("name") or data.get("original_name") or "").strip()
            date = str(data.get("first_air_date") or "")

        genres = []
        for g in data.get("genres", []) or []:
            try:
                nm = str(g.get("name") or "").strip()
            except Exception:
                nm = ""
            if nm:
                genres.append(nm)

        year = None
        if len(date) >= 4 and date[:4].isdigit():
            year = int(date[:4])

        return {
            "id": int(data.get("id") or tmdb_id),
            "media_type": mt,
            "title": title,
            "year": year,
            "overview": str(data.get("overview") or "").strip(),
            "genres": genres,
            "vote_average": float(data.get("vote_average") or 0.0),
            "poster_path": data.get("poster_path") or None,
            "backdrop_path": data.get("backdrop_path") or None,
        }

    def get_item_images(self, media_type: str, tmdb_id: int, limit: int = 24) -> Dict[str, List[Dict[str, Any]]]:
        """
        Fetch ranked poster/backdrop variants for a TMDB item.

        Returns:
          {
            "posters": [{"file_path": "...", "kind": "poster", ...}, ...],
            "backdrops": [{"file_path": "...", "kind": "backdrop", ...}, ...],
          }
        """
        mt = str(media_type or "").strip().casefold()
        if mt not in ("movie", "tv"):
            raise ValueError(f"Unsupported media_type: {media_type}")

        endpoint = "movie" if mt == "movie" else "tv"
        url = (
            f"{self.API_BASE}/{endpoint}/{int(tmdb_id)}/images"
            "?include_image_language=en,null"
        )
        data = self._get_json(url)

        def _lang_rank(value: str) -> int:
            lang = str(value or "").strip().casefold()
            if lang == "en":
                return 2
            if not lang:
                return 1
            return 0

        def _normalize(items: Any, kind: str) -> List[Dict[str, Any]]:
            out: List[Dict[str, Any]] = []
            for raw in items or []:
                if not isinstance(raw, dict):
                    continue
                file_path = str(raw.get("file_path") or "").strip()
                if not file_path:
                    continue
                try:
                    width = int(raw.get("width") or 0)
                except Exception:
                    width = 0
                try:
                    height = int(raw.get("height") or 0)
                except Exception:
                    height = 0
                try:
                    vote_average = float(raw.get("vote_average") or 0.0)
                except Exception:
                    vote_average = 0.0
                try:
                    vote_count = int(raw.get("vote_count") or 0)
                except Exception:
                    vote_count = 0
                language = str(raw.get("iso_639_1") or "").strip().casefold()
                out.append(
                    {
                        "file_path": file_path,
                        "kind": str(kind),
                        "width": width,
                        "height": height,
                        "vote_average": vote_average,
                        "vote_count": vote_count,
                        "language": language,
                    }
                )
            out.sort(
                key=lambda item: (
                    _lang_rank(str(item.get("language") or "")),
                    float(item.get("vote_average") or 0.0),
                    int(item.get("vote_count") or 0),
                    int(item.get("width") or 0) * int(item.get("height") or 0),
                ),
                reverse=True,
            )
            return out[: max(1, int(limit))]

        return {
            "posters": _normalize(data.get("posters", []), "poster"),
            "backdrops": _normalize(data.get("backdrops", []), "backdrop"),
        }

    # -----------------------------
    # Images
    # -----------------------------
    def image_url(self, img_path: str, size: str = "w342") -> str:
        """
        size examples:
          w92, w154, w185, w342, w500, w780, w1280, original
        """
        if not img_path:
            raise ValueError("image_url called with empty img_path")
        p = img_path if img_path.startswith("/") else ("/" + img_path)
        return f"{self.IMG_BASE}/{size}{p}"

    def download_image_bytes(self, url: str) -> bytes:
        req = Request(url, headers={"accept": "image/*"})
        with urlopen(req, timeout=30) as resp:
            return resp.read()

