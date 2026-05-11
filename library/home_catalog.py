from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

from omega.app.contracts import ShowGroup
from omega.app.text_naming import NameCleaner, extract_show_title_from_episode_filename, parse_season_episode
from omega.library.tmdb_client import TMDBClient, TMDBHit


@dataclass
class CatalogBuildResult:
    all_items: List[ShowGroup]
    movies: List[ShowGroup]
    tv_shows: List[ShowGroup]
    warnings: List[str]


class CatalogBuildCancelled(RuntimeError):
    pass


class HomeCatalogService:
    """
    Builds a metadata-enriched media catalog for the Home experience.

    Responsibilities:
    - discover movie candidates from messy local roots
    - enrich items with TMDB when available
    - classify items as movie vs TV with metadata + heuristics
    - provide stable output for rail building
    """

    def __init__(
        self,
        cache_dir: Path,
        video_exts: Set[str],
        image_exts: Set[str],
        logger: Optional[Callable[..., None]] = None,
    ) -> None:
        self._cache_dir = Path(cache_dir)
        self._video_exts = {str(x).lower() for x in (video_exts or set())}
        self._image_exts = {str(x).lower() for x in (image_exts or set())}
        self._log = logger

        self._cache_file = self._cache_dir / "catalog_enrichment.json"
        self._art_dir = self._cache_dir / "catalog_art"

        self._cache_data: Dict[str, object] = {"version": 1, "items": {}}
        self._warnings: List[str] = []
        self._tmdb: Optional[TMDBClient] = None
        self._tmdb_init_attempted = False
        self._build_allow_network = True
        self._build_network_budget = 24
        self._build_network_used = 0
        self._should_cancel: Optional[Callable[[], bool]] = None
        self._build_dir_entries_cache: Dict[str, Tuple[Path, ...]] = {}
        self._build_dir_image_index: Dict[str, Tuple[Dict[str, Path], Tuple[Path, ...]]] = {}

        self._load_cache()

    def build(
        self,
        tv_seed_groups: List[ShowGroup],
        *,
        sources: Sequence[Path],
        movies_dir: Path,
        loose_episode_roots: Optional[Sequence[Path]] = None,
        allow_network: bool = True,
        max_network_lookups: int = 24,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> CatalogBuildResult:
        t0 = float(time.time())
        self._warnings = []
        self._build_allow_network = bool(allow_network)
        self._build_network_budget = max(0, int(max_network_lookups))
        self._build_network_used = 0
        self._should_cancel = should_cancel
        self._build_dir_entries_cache = {}
        self._build_dir_image_index = {}
        try:
            self._log_msg(
                f"[CATALOG] build start allow_network={self._build_allow_network} ",
                f"budget={self._build_network_budget}",
            )
            self._raise_if_cancelled()

            tv_seed = list(tv_seed_groups or [])
            loose_episode_roots = tuple(loose_episode_roots or sources or ())
            loose_episode_groups = self._discover_loose_episode_groups(loose_episode_roots, tv_seed)
            movies = self._discover_movie_groups(tv_seed + loose_episode_groups, sources=sources, movies_dir=movies_dir)

            all_seed = tv_seed + loose_episode_groups + movies
            out: List[ShowGroup] = []
            for sg in all_seed:
                self._raise_if_cancelled()
                try:
                    out.append(self._enrich_group(sg))
                except CatalogBuildCancelled:
                    raise
                except Exception as exc:
                    self._warnings.append(
                        f"[CATALOG][ERROR] {str(getattr(sg, 'display_title', '') or getattr(sg, 'primary_dir', '') or 'title')}: "
                        f"{type(exc).__name__}: {exc}"
                    )
                    out.append(self._mark_failed_group(sg, exc))

            movies_out = [x for x in out if str(getattr(x, "media_type", "")).casefold() == "movie"]
            tv_out = [x for x in out if str(getattr(x, "media_type", "tv")).casefold() != "movie"]

            self._raise_if_cancelled()
            self._save_cache()
            elapsed = float(time.time()) - t0
            self._log_msg(
                f"[CATALOG] build done items={len(out)} movies={len(movies_out)} tv={len(tv_out)} ",
                f"network_used={self._build_network_used}/{self._build_network_budget} elapsed={elapsed:.2f}s",
            )

            return CatalogBuildResult(
                all_items=out,
                movies=movies_out,
                tv_shows=tv_out,
                warnings=list(self._warnings),
            )
        finally:
            self._should_cancel = None

    def _cancel_requested(self) -> bool:
        checker = self._should_cancel
        if checker is None:
            return False
        try:
            return bool(checker())
        except Exception:
            return False

    def _raise_if_cancelled(self) -> None:
        if self._cancel_requested():
            raise CatalogBuildCancelled("catalog build cancelled")

    def invalidate_item(self, content_key: str) -> None:
        key = str(content_key or "").strip()
        if not key:
            return
        items = self._cache_data.setdefault("items", {})
        if isinstance(items, dict):
            items.pop(key, None)
            self._save_cache()

    def search_tmdb_hits(
        self,
        query: str,
        *,
        limit: int = 8,
        media_hint: str = "",
    ) -> List[TMDBHit]:
        q = str(query or "").strip()
        if not q:
            return []

        client = self._get_tmdb()
        if client is None:
            return []

        hits = list(client.search_multi(q, limit=max(1, int(limit))))
        hint = str(media_hint or "").strip().casefold()
        if hint not in {"movie", "tv"}:
            return hits

        preferred = [hit for hit in hits if str(getattr(hit, "media_type", "") or "").strip().casefold() == hint]
        fallback = [hit for hit in hits if hit not in preferred]
        return preferred + fallback

    def set_manual_match(self, content_key: str, hit: TMDBHit) -> Optional[Dict[str, object]]:
        key = str(content_key or "").strip()
        if not key:
            return None

        client = self._get_tmdb()
        if client is None:
            return None

        metadata = self._metadata_payload_from_hit(client, hit)
        if not metadata:
            return None

        cache_items = self._cache_data.setdefault("items", {})
        if not isinstance(cache_items, dict):
            cache_items = {}
            self._cache_data["items"] = cache_items

        metadata["manual_match"] = True
        cache_items[key] = dict(metadata)
        self._save_cache()
        return dict(metadata)

    def _iter_loose_episode_candidate_dirs(self, roots: Sequence[Path], *, max_depth: int = 2) -> List[Path]:
        out: List[Path] = []
        seen: Set[str] = set()
        pending: List[Tuple[Path, int]] = []
        for root in roots or ():
            if root is None:
                continue
            try:
                p = Path(str(root))
            except Exception:
                continue
            pending.append((p, 0))

        max_depth = max(0, int(max_depth))
        while pending:
            folder, depth = pending.pop(0)
            if not folder.exists() or not folder.is_dir():
                continue
            key = self._canonical_path_key(folder)
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(folder)

            if depth >= max_depth:
                continue
            subdirs: List[Path] = []
            for child in self._folder_entries(folder):
                self._raise_if_cancelled()
                try:
                    if child.is_dir():
                        subdirs.append(child)
                except Exception:
                    continue
            for child in sorted(subdirs, key=lambda item: item.name.casefold()):
                pending.append((child, depth + 1))
        return out

    def _path_is_inside_any(self, path: Path, parents: Sequence[Path]) -> bool:
        try:
            resolved = Path(str(path)).resolve()
        except Exception:
            resolved = Path(str(path)).absolute()
        for parent in parents or ():
            try:
                parent_resolved = Path(str(parent)).resolve()
            except Exception:
                parent_resolved = Path(str(parent)).absolute()
            try:
                resolved.relative_to(parent_resolved)
                return True
            except Exception:
                continue
        return False

    def _loose_episode_title_key(self, title: str) -> str:
        cleaned = NameCleaner.clean(str(title or "")) or str(title or "")
        key = re.sub(r"[^a-z0-9]+", "-", cleaned.casefold()).strip("-")
        return key or "episodes"

    def _loose_episode_sort_key(self, episode_path: Path) -> Tuple[int, int, int, str]:
        s_num, e_num = parse_season_episode(Path(str(episode_path)).stem)
        if s_num is not None and e_num is not None:
            return (0, int(s_num), int(e_num), Path(str(episode_path)).name.casefold())
        if e_num is not None:
            return (1, 0, int(e_num), Path(str(episode_path)).name.casefold())
        return (9, 0, 0, Path(str(episode_path)).name.casefold())

    def _discover_loose_episode_groups(
        self,
        roots: Sequence[Path],
        tv_seed_groups: Sequence[ShowGroup],
    ) -> List[ShowGroup]:
        excluded_roots: List[Path] = []
        for sg in tv_seed_groups or ():
            for raw in list(getattr(sg, "all_dirs", []) or []) + [getattr(sg, "primary_dir", None)]:
                if raw is None:
                    continue
                try:
                    p = Path(str(raw))
                except Exception:
                    continue
                if p.exists() and p.is_dir():
                    excluded_roots.append(p)

        groups_by_key: Dict[str, Dict[str, object]] = {}
        seen_episode_paths: Set[str] = set()
        for folder in self._iter_loose_episode_candidate_dirs(roots):
            self._raise_if_cancelled()
            if self._path_is_inside_any(folder, excluded_roots):
                continue

            folder_key = self._canonical_path_key(folder)
            if not folder_key:
                continue

            try:
                direct_videos = [
                    item
                    for item in self._folder_entries(folder)
                    if item.is_file() and item.suffix.lower() in self._video_exts
                ]
            except Exception:
                direct_videos = []

            for video in direct_videos:
                self._raise_if_cancelled()
                if not self._looks_like_episode_name(video.stem):
                    continue
                video_key = self._canonical_path_key(video)
                if not video_key or video_key in seen_episode_paths:
                    continue
                inferred_title = extract_show_title_from_episode_filename(video.stem)
                title = inferred_title or NameCleaner.clean(folder.name) or folder.name
                title = str(title or "").strip()
                if not title:
                    continue
                loose_key = f"loose:{self._loose_episode_title_key(title)}"
                bucket = groups_by_key.setdefault(
                    loose_key,
                    {
                        "title": title,
                        "folders": [],
                        "episodes": [],
                    },
                )
                folders = bucket.setdefault("folders", [])
                if isinstance(folders, list):
                    folders.append(folder)
                episodes = bucket.setdefault("episodes", [])
                if isinstance(episodes, list):
                    episodes.append(video)
                    seen_episode_paths.add(video_key)

        out: List[ShowGroup] = []
        for content_key, bucket in groups_by_key.items():
            self._raise_if_cancelled()
            folders = [
                Path(str(item))
                for item in list(bucket.get("folders") or [])
                if item is not None and Path(str(item)).exists() and Path(str(item)).is_dir()
            ]
            folder = folders[0] if folders else Path(str(bucket.get("folder") or ""))
            title = str(bucket.get("title") or folder.name or "Loose Episodes").strip()
            episodes = [
                Path(str(item))
                for item in list(bucket.get("episodes") or [])
                if item is not None and Path(str(item)).exists() and Path(str(item)).is_file()
            ]
            episodes.sort(key=self._loose_episode_sort_key)
            if not episodes:
                continue
            mtime = self._best_mtime(folders + [folder] + episodes)
            out.append(
                ShowGroup(
                    display_title=title,
                    primary_dir=folder,
                    poster_path=self._find_local_art(folder),
                    group_mtime=float(mtime),
                    all_dirs=folders or [folder],
                    media_type="tv",
                    play_path=None,
                    content_key=content_key,
                    classification_reason="loose-episode-bundle",
                    episode_paths=tuple(episodes),
                    source_path=str(folder),
                    status="discovering",
                    source_status="available",
                    file_count=len(episodes),
                    episode_count=len(episodes),
                )
            )

        if out:
            self._log_msg(f"[CATALOG] grouped loose episodes bundles={len(out)}")
        return out

    def _discover_movie_groups(
        self,
        tv_seed_groups: List[ShowGroup],
        *,
        sources: Sequence[Path],
        movies_dir: Path,
    ) -> List[ShowGroup]:
        tv_roots = {
            self._canonical_path_key(getattr(sg, "primary_dir", Path("")))
            for sg in (tv_seed_groups or [])
        }

        roots: List[Path] = []
        roots.append(Path(movies_dir))
        for src in sources or []:
            if src is None:
                continue
            p = Path(str(src))
            roots.append(p)
            cand_movies = p / "Movies"
            if cand_movies.exists() and cand_movies.is_dir():
                roots.append(cand_movies)

        unique_roots: List[Path] = []
        seen_roots: Set[str] = set()
        for r in roots:
            if r is None:
                continue
            rk = self._canonical_path_key(r)
            if not rk or rk in seen_roots:
                continue
            seen_roots.add(rk)
            if r.exists() and r.is_dir():
                unique_roots.append(r)

        out: List[ShowGroup] = []
        seen_items: Set[str] = set()

        for root in unique_roots:
            self._raise_if_cancelled()
            for child in self._folder_entries(root):
                self._raise_if_cancelled()
                if child.is_dir():
                    videos = self._collect_video_files(child, max_depth=2, max_count=80)
                    if not videos:
                        continue
                    if self._looks_like_tv_bundle(child, videos):
                        continue

                    content_key = self._canonical_path_key(child)
                    if not content_key or content_key in seen_items or content_key in tv_roots:
                        continue
                    seen_items.add(content_key)

                    title = NameCleaner.clean(child.name) or child.name
                    poster = self._find_local_art(child)
                    mtime = self._best_mtime([child] + videos)

                    out.append(
                        ShowGroup(
                            display_title=str(title),
                            primary_dir=child,
                            poster_path=poster,
                            group_mtime=float(mtime),
                            all_dirs=[child],
                            media_type="movie",
                            play_path=videos[0],
                            content_key=content_key,
                            classification_reason="movie-folder-heuristic",
                            source_path=str(root),
                            status="discovering",
                            source_status="available",
                            file_count=len(videos),
                            episode_count=0,
                        )
                    )
                    continue

                if child.is_file() and child.suffix.lower() in self._video_exts:
                    if self._looks_like_episode_name(child.stem):
                        continue

                    content_key = self._canonical_path_key(child)
                    if not content_key or content_key in seen_items:
                        continue
                    seen_items.add(content_key)

                    title = NameCleaner.clean(child.stem) or child.stem
                    poster = self._find_local_art(root)
                    mtime = self._best_mtime([child])

                    out.append(
                        ShowGroup(
                            display_title=str(title),
                            primary_dir=child,
                            poster_path=poster,
                            group_mtime=float(mtime),
                            all_dirs=[root],
                            media_type="movie",
                            play_path=child,
                            content_key=content_key,
                            classification_reason="single-file-movie-heuristic",
                            source_path=str(root),
                            status="discovering",
                            source_status="available",
                            file_count=1,
                            episode_count=0,
                        )
                    )

        return out

    def _enrich_group(self, sg: ShowGroup) -> ShowGroup:
        self._raise_if_cancelled()
        now = int(time.time())
        base_key = str(getattr(sg, "content_key", "") or "").strip()
        if not base_key:
            base_key = self._canonical_path_key(getattr(sg, "primary_dir", Path("")))

        title_fallback = str(getattr(sg, "display_title", "") or "").strip()
        media_hint = str(getattr(sg, "media_type", "") or "").strip().casefold()
        if media_hint not in ("movie", "tv"):
            media_hint = "tv" if self._looks_like_tv_path(getattr(sg, "primary_dir", Path(""))) else "movie"

        cache_items = self._cache_data.setdefault("items", {})
        if not isinstance(cache_items, dict):
            cache_items = {}
            self._cache_data["items"] = cache_items

        cached = cache_items.get(base_key)
        if not isinstance(cached, dict):
            cached = {}

        year_hint = self._infer_year(str(title_fallback) + " " + str(getattr(sg, "primary_dir", "")))
        query = self._clean_query_title(title_fallback)

        metadata = None
        if self._cache_entry_fresh(cached):
            metadata = dict(cached)
        else:
            metadata = self._fetch_metadata(query, media_hint=media_hint, year_hint=year_hint, allow_network=self._build_allow_network)
            if metadata is None:
                metadata = {
                    "updated_at": int(time.time()),
                    "title": title_fallback,
                    "media_type": media_hint,
                    "year": year_hint,
                    "genres": [],
                    "overview": "",
                    "vote_average": None,
                    "tmdb_id": None,
                    "tmdb_media_type": "",
                    "poster_local": "",
                    "backdrop_local": "",
                    "metadata_found": False,
                }
            cache_items[base_key] = metadata

        md_type = str(metadata.get("media_type") or media_hint or "tv").casefold()
        if md_type not in ("movie", "tv"):
            md_type = media_hint

        md_title = str(metadata.get("title") or "").strip() or title_fallback
        md_year = metadata.get("year")
        if not isinstance(md_year, int):
            md_year = year_hint

        md_genres = metadata.get("genres") or []
        genres = [str(g).strip() for g in md_genres if str(g).strip()]
        if not genres:
            genres = self._infer_genres(md_title, getattr(sg, "primary_dir", Path("")))

        md_overview = str(metadata.get("overview") or "").strip()
        md_vote = metadata.get("vote_average")
        try:
            rating = float(md_vote) if md_vote is not None else None
        except Exception:
            rating = None

        poster_local = self._path_or_none(metadata.get("poster_local"))
        backdrop_local = self._path_or_none(metadata.get("backdrop_local"))
        local_poster = self._find_local_art_variant(getattr(sg, "primary_dir", Path("")), "poster")
        local_backdrop = self._find_local_art_variant(getattr(sg, "primary_dir", Path("")), "backdrop")
        local_any = local_backdrop or local_poster or self._find_local_art(getattr(sg, "primary_dir", Path("")))

        poster = local_poster or local_any or getattr(sg, "poster_path", None) or poster_local or backdrop_local
        backdrop = local_backdrop or local_any or backdrop_local or poster_local or poster

        play_path = getattr(sg, "play_path", None)
        if play_path is None and md_type == "movie":
            play_path = self._discover_play_path_for_movie(getattr(sg, "primary_dir", Path("")))

        reason = str(getattr(sg, "classification_reason", "") or "")
        if bool(metadata.get("metadata_found")):
            reason = "tmdb-match"
        elif not reason:
            reason = "heuristic"

        warnings = list(dict.fromkeys([*(getattr(sg, "warnings", ()) or ())]))
        if not bool(metadata.get("metadata_found")) and media_hint != md_type:
            warning = f"[CATALOG][AMBIGUOUS] {base_key} -> guessed '{md_type}'"
            self._warnings.append(warning)
            if warning not in warnings:
                warnings.append(warning)

        return ShowGroup(
            display_title=md_title,
            primary_dir=Path(str(getattr(sg, "primary_dir", Path("")))),
            poster_path=poster,
            group_mtime=float(getattr(sg, "group_mtime", 0.0) or 0.0),
            all_dirs=[Path(str(p)) for p in (getattr(sg, "all_dirs", []) or []) if p is not None],
            media_type=md_type,
            play_path=play_path,
            content_key=base_key,
            year=md_year,
            genres=tuple(genres),
            overview=md_overview,
            rating=rating,
            tmdb_id=self._safe_int(metadata.get("tmdb_id")),
            tmdb_media_type=str(metadata.get("tmdb_media_type") or ""),
            backdrop_path=backdrop,
            classification_reason=reason,
            episode_paths=tuple(getattr(sg, "episode_paths", ()) or ()),
            title_id=str(getattr(sg, "title_id", "") or ""),
            status="ready" if bool(metadata.get("metadata_found")) and bool(poster or backdrop) else ("partial" if bool(metadata.get("metadata_found")) else "metadata_pending"),
            source_path=str(getattr(sg, "source_path", "") or getattr(sg, "primary_dir", Path(""))),
            source_status=str(getattr(sg, "source_status", "") or "available"),
            source_enabled=bool(getattr(sg, "source_enabled", True)),
            created_at=int(getattr(sg, "created_at", 0) or 0),
            updated_at=now,
            last_scanned_at=now,
            metadata_updated_at=now if bool(metadata.get("metadata_found")) else int(getattr(sg, "metadata_updated_at", 0) or 0),
            art_updated_at=now if bool(poster or backdrop) else int(getattr(sg, "art_updated_at", 0) or 0),
            warnings=tuple(dict.fromkeys(warnings)),
            errors=tuple(getattr(sg, "errors", ()) or ()),
            duplicate_paths=tuple(getattr(sg, "duplicate_paths", ()) or ()),
            duplicate_of=str(getattr(sg, "duplicate_of", "") or ""),
            metadata_source="tmdb" if bool(metadata.get("metadata_found")) else "",
            art_source="local" if bool(poster or backdrop) else "",
            file_count=int(getattr(sg, "file_count", 0) or len(list(getattr(sg, "all_dirs", []) or [])) or 0),
            episode_count=int(getattr(sg, "episode_count", 0) or len(tuple(getattr(sg, "episode_paths", ()) or ())) or 0),
        )

    def _mark_failed_group(self, sg: ShowGroup, exc: Exception) -> ShowGroup:
        message = f"{type(exc).__name__}: {exc}"
        warnings = list(getattr(sg, "warnings", ()) or ())
        errors = list(getattr(sg, "errors", ()) or ())
        if message not in errors:
            errors.append(message)
        return replace(
            sg,
            status="failed",
            warnings=tuple(dict.fromkeys(warnings)),
            errors=tuple(dict.fromkeys(errors)),
            updated_at=int(time.time()),
            last_scanned_at=int(time.time()),
        )

    def _fetch_metadata(self, query: str, *, media_hint: str, year_hint: Optional[int], allow_network: bool) -> Optional[Dict[str, object]]:
        self._raise_if_cancelled()
        q = str(query or "").strip()
        if not q:
            return None
        if not allow_network:
            return None

        if int(self._build_network_used) >= int(self._build_network_budget):
            return None

        self._build_network_used += 1

        client = self._get_tmdb()
        if client is None:
            return None

        try:
            hits = client.search_multi(q, limit=10)
        except Exception as e:
            self._log_msg("[CATALOG][TMDB][WARN] search failed:", e)
            return None

        self._raise_if_cancelled()
        if not hits:
            return None

        hit = self._pick_best_hit(q, hits, media_hint=media_hint, year_hint=year_hint)
        if hit is None:
            return None
        return self._metadata_payload_from_hit(client, hit)

    def _pick_best_hit(
        self,
        query: str,
        hits: Sequence[TMDBHit],
        *,
        media_hint: str,
        year_hint: Optional[int],
    ) -> Optional[TMDBHit]:
        best: Optional[TMDBHit] = None
        best_score = -1.0

        q = self._norm_for_match(query)
        for h in hits:
            self._raise_if_cancelled()
            h_title = self._norm_for_match(getattr(h, "title", ""))
            if not h_title:
                continue

            score = SequenceMatcher(None, q, h_title).ratio()
            hm = str(getattr(h, "media_type", "") or "").strip().casefold()
            if media_hint in ("movie", "tv") and hm == media_hint:
                score += 0.22

            hy = self._safe_int(getattr(h, "year", None))
            if year_hint is not None and hy is not None:
                diff = abs(int(year_hint) - int(hy))
                if diff == 0:
                    score += 0.08
                elif diff <= 1:
                    score += 0.04

            if score > best_score:
                best_score = score
                best = h

        if best is None or best_score < 0.45:
            return None
        return best

    def _discover_play_path_for_movie(self, primary: Path) -> Optional[Path]:
        p = Path(str(primary))
        if p.is_file() and p.suffix.lower() in self._video_exts:
            return p
        if not p.exists() or not p.is_dir():
            return None
        videos = self._collect_video_files(p, max_depth=2, max_count=12)
        return videos[0] if videos else None

    def _looks_like_tv_bundle(self, folder: Path, videos: Sequence[Path]) -> bool:
        if self._looks_like_tv_path(folder):
            return True
        episode_like = 0
        for v in videos:
            if self._looks_like_episode_name(v.stem):
                episode_like += 1
        return episode_like >= 2

    def _looks_like_tv_path(self, p: Path) -> bool:
        folder = Path(str(p))
        if folder.is_file():
            folder = folder.parent
        if not folder.exists() or not folder.is_dir():
            return False

        for sub in self._folder_entries(folder):
            try:
                if not sub.is_dir():
                    continue
            except Exception:
                continue
            nm = sub.name.strip().casefold()
            if nm.startswith("season"):
                return True
            if re.fullmatch(r"s\d{1,2}", nm):
                return True
            if "season" in nm and any(ch.isdigit() for ch in nm):
                return True

        return False

    def _looks_like_episode_name(self, stem: str) -> bool:
        s_num, e_num = parse_season_episode(stem)
        if s_num is not None and e_num is not None:
            return True
        return bool(re.search(r"\bE\d{1,3}\b", stem, re.IGNORECASE))

    def _collect_video_files(self, root: Path, *, max_depth: int, max_count: int) -> List[Path]:
        out: List[Path] = []
        base = Path(str(root))
        if not base.exists() or not base.is_dir():
            return out

        max_depth = max(0, int(max_depth))
        max_items = max(1, int(max_count))
        pending: List[Tuple[Path, int]] = [(base, 0)]
        while pending and len(out) < max_items:
            folder, depth = pending.pop()
            entries = self._folder_entries(folder)
            if not entries:
                continue

            subdirs: List[Path] = []
            for p in entries:
                self._raise_if_cancelled()
                try:
                    if p.is_file():
                        if p.suffix.lower() not in self._video_exts:
                            continue
                        out.append(p)
                        if len(out) >= max_items:
                            break
                        continue
                    if depth < max_depth and p.is_dir():
                        subdirs.append(p)
                except Exception:
                    continue
            if depth >= max_depth or len(out) >= max_items:
                continue
            for subdir in sorted(subdirs, key=lambda item: str(item).casefold(), reverse=True):
                pending.append((subdir, depth + 1))

        out.sort(key=lambda x: str(x).casefold())
        return out

    def _folder_entries(self, folder: Path) -> Tuple[Path, ...]:
        try:
            target = Path(str(folder))
        except Exception:
            return ()
        key = self._canonical_path_key(target)
        if key:
            cached = self._build_dir_entries_cache.get(key)
            if cached is not None:
                return cached
        try:
            entries = tuple(target.iterdir()) if target.is_dir() else ()
        except Exception:
            entries = ()
        if key:
            self._build_dir_entries_cache[key] = entries
        return entries

    def _folder_image_index(self, folder: Path) -> Tuple[Dict[str, Path], Tuple[Path, ...]]:
        key = self._canonical_path_key(folder)
        if key:
            cached = self._build_dir_image_index.get(key)
            if cached is not None:
                return cached

        ordered_images: List[Path] = []
        name_map: Dict[str, Path] = {}
        for cand in self._folder_entries(folder):
            try:
                if not cand.is_file() or cand.suffix.lower() not in self._image_exts:
                    continue
            except Exception:
                continue
            ordered_images.append(cand)
            norm_name = cand.name.casefold()
            if norm_name not in name_map:
                name_map[norm_name] = cand

        indexed = (name_map, tuple(ordered_images))
        if key:
            self._build_dir_image_index[key] = indexed
        return indexed

    def _find_local_art(self, base: Path) -> Optional[Path]:
        p = Path(str(base))
        folder = p if p.is_dir() else p.parent
        if not folder.exists() or not folder.is_dir():
            return None

        name_map, ordered_images = self._folder_image_index(folder)
        preferred = ["backdrop", "Backdrop", "poster", "Poster", "folder", "Folder", "cover", "Cover"]
        for bn in preferred:
            for ext in self._image_exts:
                cand = name_map.get(f"{bn}{ext}".casefold())
                if cand is not None:
                    return cand

        return ordered_images[0] if ordered_images else None

    def _find_local_art_variant(self, base: Path, kind: str) -> Optional[Path]:
        p = Path(str(base))
        folder = p if p.is_dir() else p.parent
        if not folder.exists() or not folder.is_dir():
            return None

        name_map, _ordered_images = self._folder_image_index(folder)
        kind_key = str(kind or "").strip().casefold()
        if kind_key == "backdrop":
            preferred = ["backdrop", "Backdrop", "fanart", "Fanart"]
        elif kind_key == "poster":
            preferred = ["poster", "Poster", "folder", "Folder", "cover", "Cover"]
        else:
            preferred = []

        for bn in preferred:
            for ext in self._image_exts:
                cand = name_map.get(f"{bn}{ext}".casefold())
                if cand is not None:
                    return cand
        return None

    def _cache_remote_art(self, client: TMDBClient, remote_path: object, filename: str, *, size: str) -> Optional[Path]:
        rp = str(remote_path or "").strip()
        if not rp:
            return None

        try:
            self._art_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            return None

        out = self._art_dir / str(filename)
        if out.exists() and out.is_file():
            return out

        try:
            url = client.image_url(rp, size=size)
            data = client.download_image_bytes(url)
            out.write_bytes(data)
            return out
        except Exception as e:
            self._log_msg("[CATALOG][TMDB][WARN] art cache failed:", e)
            return None

    def _metadata_payload_from_hit(self, client: TMDBClient, hit: TMDBHit) -> Dict[str, object]:
        try:
            details = client.get_item_details(hit.media_type, int(hit.id))
        except Exception as e:
            self._log_msg("[CATALOG][TMDB][WARN] detail fetch failed:", e)
            details = {
                "id": int(hit.id),
                "media_type": str(hit.media_type),
                "title": str(hit.title),
                "year": self._safe_int(hit.year),
                "overview": "",
                "genres": [],
                "vote_average": None,
                "poster_path": hit.poster_path,
                "backdrop_path": hit.backdrop_path,
            }

        poster_local = self._cache_remote_art(client, details.get("poster_path"), f"{hit.media_type}_{hit.id}_poster.jpg", size="w500")
        backdrop_local = self._cache_remote_art(client, details.get("backdrop_path"), f"{hit.media_type}_{hit.id}_backdrop.jpg", size="w1280")

        return {
            "updated_at": int(time.time()),
            "title": str(details.get("title") or hit.title or "").strip(),
            "media_type": str(details.get("media_type") or hit.media_type or "").strip().casefold(),
            "year": self._safe_int(details.get("year")) or self._safe_int(hit.year),
            "genres": [str(g).strip() for g in (details.get("genres") or []) if str(g).strip()],
            "overview": str(details.get("overview") or "").strip(),
            "vote_average": details.get("vote_average"),
            "tmdb_id": int(hit.id),
            "tmdb_media_type": str(hit.media_type),
            "poster_local": str(poster_local) if poster_local is not None else "",
            "backdrop_local": str(backdrop_local) if backdrop_local is not None else "",
            "metadata_found": True,
        }

    def _infer_genres(self, title: str, primary_path: Path) -> List[str]:
        blob = self._norm_for_match(f"{title} {primary_path}")
        rules: List[Tuple[str, Tuple[str, ...]]] = [
            ("Horror", ("horror", "slasher", "haunt", "ghost", "zombie")),
            ("Action", ("action", "war", "combat", "mission", "adventure")),
            ("Comedy", ("comedy", "sitcom", "funny", "laugh")),
            ("Drama", ("drama", "romance", "soap")),
            ("Sci-Fi", ("sci fi", "sci-fi", "science fiction", "space", "future")),
            ("Fantasy", ("fantasy", "magic", "dragon", "myth")),
            ("Animation", ("animation", "animated", "cartoon")),
            ("Anime", ("anime", "ova")),
            ("Documentary", ("documentary", "docuseries", "history", "biography")),
            ("Family", ("family", "kids", "children")),
            ("Crime", ("crime", "detective", "police", "mafia")),
            ("Thriller", ("thriller", "suspense", "mystery")),
        ]
        out: List[str] = []
        for genre, kws in rules:
            if any(k in blob for k in kws):
                out.append(genre)
        return out

    def _cache_entry_fresh(self, entry: Dict[str, object]) -> bool:
        try:
            ts = int(entry.get("updated_at") or 0)
        except Exception:
            ts = 0
        if ts <= 0:
            return False

        found = bool(entry.get("metadata_found"))
        ttl_days = 45 if found else 7
        age = int(time.time()) - int(ts)
        return age <= (ttl_days * 24 * 60 * 60)

    def _load_cache(self) -> None:
        try:
            if not self._cache_file.exists() or not self._cache_file.is_file():
                return
            raw = self._cache_file.read_text(encoding="utf-8", errors="ignore")
            obj = json.loads(raw) if raw.strip() else {}
            if isinstance(obj, dict):
                self._cache_data = obj
                self._cache_data.setdefault("version", 1)
                self._cache_data.setdefault("items", {})
        except Exception:
            self._cache_data = {"version": 1, "items": {}}

    def _save_cache(self) -> None:
        try:
            self._cache_file.parent.mkdir(parents=True, exist_ok=True)
            self._cache_file.write_text(json.dumps(self._cache_data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def _get_tmdb(self) -> Optional[TMDBClient]:
        if self._tmdb_init_attempted:
            return self._tmdb

        self._tmdb_init_attempted = True
        try:
            self._tmdb = TMDBClient()
        except Exception as e:
            self._tmdb = None
            self._log_msg("[CATALOG][TMDB] unavailable:", e)
        return self._tmdb

    def _clean_query_title(self, title: str) -> str:
        t = str(title or "").strip()
        t = re.sub(r"\((19\d{2}|20\d{2})\)", "", t).strip()
        return t

    def _canonical_path_key(self, p: Path) -> str:
        try:
            return str(Path(str(p)).resolve()).rstrip("\\/").casefold()
        except Exception:
            return str(p).rstrip("\\/").casefold()

    def _path_or_none(self, raw: object) -> Optional[Path]:
        s = str(raw or "").strip()
        if not s:
            return None
        p = Path(s)
        return p if p.exists() else None

    def _norm_for_match(self, s: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", str(s or "").casefold()).strip()

    def _infer_year(self, text: str) -> Optional[int]:
        m = re.search(r"(19\d{2}|20\d{2})", str(text or ""))
        if not m:
            return None
        y = int(m.group(1))
        if 1900 <= y <= 2099:
            return y
        return None

    def _safe_int(self, raw: object) -> Optional[int]:
        try:
            return int(raw)
        except Exception:
            return None

    def _best_mtime(self, paths: Sequence[Path]) -> float:
        best = 0.0
        for p in paths:
            try:
                best = max(best, float(Path(str(p)).stat().st_mtime))
            except Exception:
                continue
        return best

    def _log_msg(self, *args: object) -> None:
        if self._log is None:
            return
        try:
            self._log(*args)
        except Exception:
            pass
