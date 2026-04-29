from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median
from typing import Callable, Dict, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class SegmentSkipTuning:
    intro_button_min_ms: int = 3_000
    outro_button_min_ms: int = 3_000
    season_profile_min_samples: int = 2
    season_profile_max_deviation_ms: int = 18_000
    chapter_intro_max_start_ms: int = 20 * 60 * 1000
    chapter_outro_min_remaining_ms: int = 3 * 60 * 1000
    auto_skip_fudge_ms: int = 350
    capture_status_ms: int = 2_400


TUNING = SegmentSkipTuning()


@dataclass
class SkipSegment:
    start_ms: int
    end_ms: int
    source: str = "manual"
    confidence: float = 1.0

    def normalized(self, duration_ms: int) -> Optional["SkipSegment"]:
        dur = max(0, int(duration_ms or 0))
        start = max(0, int(self.start_ms or 0))
        end = max(0, int(self.end_ms or 0))
        if dur > 0:
            start = min(start, dur)
            end = min(end, dur)
        if end <= start:
            return None
        return SkipSegment(
            start_ms=int(start),
            end_ms=int(end),
            source=str(self.source or "manual"),
            confidence=float(max(0.0, min(1.0, self.confidence or 0.0))),
        )


@dataclass
class EpisodeSkipMarkers:
    path_key: str
    path: str
    show_key: str = ""
    season_number: Optional[int] = None
    duration_ms: int = 0
    intro: Optional[SkipSegment] = None
    outro: Optional[SkipSegment] = None
    updated_at: int = 0


@dataclass
class SeasonSkipProfile:
    season_key: str
    show_key: str
    season_number: Optional[int]
    sample_count: int = 0
    intro: Optional[SkipSegment] = None
    outro: Optional[SkipSegment] = None
    updated_at: int = 0


class SegmentSkipStore:
    def __init__(self, path: Path, logger: Optional[Callable[..., None]] = None) -> None:
        self.path = Path(path)
        self._log = logger or (lambda *args, **kwargs: None)
        self._data: Dict[str, object] = {
            "version": 1,
            "settings": {
                "auto_skip_intro": False,
                "auto_skip_outro": False,
            },
            "episodes": {},
            "season_profiles": {},
        }
        self.load()

    def load(self) -> None:
        try:
            if not self.path.exists() or not self.path.is_file():
                return
            raw = self.path.read_text(encoding="utf-8", errors="ignore")
            obj = json.loads(raw) if raw.strip() else {}
            if isinstance(obj, dict):
                self._data.update(obj)
        except Exception as exc:
            self._log("[SKIP][WARN] load failed:", exc)

    def save(self) -> None:
        self._rebuild_profiles()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        except Exception as exc:
            self._log("[SKIP][WARN] save failed:", exc)

    def get_auto_skip(self, kind: str) -> bool:
        settings = self._settings()
        key = "auto_skip_intro" if str(kind) == "intro" else "auto_skip_outro"
        return bool(settings.get(key, False))

    def set_auto_skip(self, kind: str, enabled: bool) -> None:
        settings = self._settings()
        key = "auto_skip_intro" if str(kind) == "intro" else "auto_skip_outro"
        settings[key] = bool(enabled)
        self.save()

    def get_episode_markers(self, path_key: str) -> Optional[EpisodeSkipMarkers]:
        episodes = self._episodes()
        raw = episodes.get(str(path_key), None)
        return self._episode_from_raw(str(path_key), raw)

    def clear_segment(self, path_key: str, kind: str) -> None:
        rec = self.get_episode_markers(path_key)
        if rec is None:
            return
        if str(kind) == "intro":
            rec.intro = None
        else:
            rec.outro = None
        rec.updated_at = int(time.time())
        self._episodes()[str(path_key)] = self._episode_to_raw(rec)
        self.save()

    def set_segment(
        self,
        *,
        path_key: str,
        path: str,
        show_key: str,
        season_number: Optional[int],
        duration_ms: int,
        kind: str,
        start_ms: int,
        end_ms: int,
        source: str,
        confidence: float,
    ) -> Optional[SkipSegment]:
        rec = self.get_episode_markers(path_key)
        if rec is None:
            rec = EpisodeSkipMarkers(
                path_key=str(path_key),
                path=str(path),
                show_key=str(show_key or ""),
                season_number=int(season_number) if season_number is not None else None,
                duration_ms=int(max(0, duration_ms or 0)),
                updated_at=int(time.time()),
            )
        else:
            rec.path = str(path)
            rec.show_key = str(show_key or rec.show_key or "")
            rec.season_number = int(season_number) if season_number is not None else rec.season_number
            rec.duration_ms = int(max(rec.duration_ms or 0, duration_ms or 0))
            rec.updated_at = int(time.time())

        segment = SkipSegment(
            start_ms=int(start_ms),
            end_ms=int(end_ms),
            source=str(source or "manual"),
            confidence=float(max(0.0, min(1.0, confidence))),
        ).normalized(int(duration_ms or rec.duration_ms or 0))
        if segment is None:
            return None

        if str(kind) == "intro":
            rec.intro = segment
        else:
            rec.outro = segment
        self._episodes()[str(path_key)] = self._episode_to_raw(rec)
        self.save()
        return segment

    def get_effective_segments(
        self,
        *,
        path_key: str,
        path: str,
        show_key: str,
        season_number: Optional[int],
        duration_ms: int,
        chapters: Optional[Sequence[dict]] = None,
    ) -> Tuple[Optional[SkipSegment], Optional[SkipSegment], Dict[str, str]]:
        sources: Dict[str, str] = {}
        rec = self.get_episode_markers(path_key)
        intro = rec.intro.normalized(duration_ms) if rec is not None and rec.intro is not None else None
        outro = rec.outro.normalized(duration_ms) if rec is not None and rec.outro is not None else None
        if intro is not None:
            sources["intro"] = str(intro.source or "episode")
        if outro is not None:
            sources["outro"] = str(outro.source or "episode")

        if intro is None or outro is None:
            inferred_intro, inferred_outro = self.infer_from_chapters(chapters or (), duration_ms)
            if intro is None and inferred_intro is not None:
                intro = inferred_intro
                sources["intro"] = str(inferred_intro.source or "chapters")
                self.set_segment(
                    path_key=path_key,
                    path=path,
                    show_key=show_key,
                    season_number=season_number,
                    duration_ms=duration_ms,
                    kind="intro",
                    start_ms=int(inferred_intro.start_ms),
                    end_ms=int(inferred_intro.end_ms),
                    source=str(inferred_intro.source or "chapters"),
                    confidence=float(inferred_intro.confidence),
                )
            if outro is None and inferred_outro is not None:
                outro = inferred_outro
                sources["outro"] = str(inferred_outro.source or "chapters")
                self.set_segment(
                    path_key=path_key,
                    path=path,
                    show_key=show_key,
                    season_number=season_number,
                    duration_ms=duration_ms,
                    kind="outro",
                    start_ms=int(inferred_outro.start_ms),
                    end_ms=int(inferred_outro.end_ms),
                    source=str(inferred_outro.source or "chapters"),
                    confidence=float(inferred_outro.confidence),
                )

        profile = self.get_season_profile(show_key=show_key, season_number=season_number)
        if profile is not None:
            if intro is None and profile.intro is not None:
                intro = profile.intro.normalized(duration_ms)
                if intro is not None:
                    intro.source = "season_profile"
                    sources["intro"] = "season_profile"
            if outro is None and profile.outro is not None:
                outro = profile.outro.normalized(duration_ms)
                if outro is not None:
                    outro.source = "season_profile"
                    sources["outro"] = "season_profile"

        return intro, outro, sources

    def get_season_profile(self, *, show_key: str, season_number: Optional[int]) -> Optional[SeasonSkipProfile]:
        season_key = self._season_key(show_key, season_number)
        if not season_key:
            return None
        raw = self._season_profiles().get(season_key, None)
        return self._season_from_raw(season_key, raw)

    def infer_from_chapters(self, chapters: Sequence[dict], duration_ms: int) -> Tuple[Optional[SkipSegment], Optional[SkipSegment]]:
        if not chapters:
            return None, None
        items: List[Tuple[int, str]] = []
        for chapter in chapters:
            if not isinstance(chapter, dict):
                continue
            title = str(chapter.get("title") or chapter.get("name") or chapter.get("label") or "").strip()
            try:
                start_ms = int(round(float(chapter.get("start_ms", chapter.get("time_ms", 0))) ))
            except Exception:
                try:
                    start_ms = int(round(float(chapter.get("time", chapter.get("start", 0.0))) * 1000.0))
                except Exception:
                    start_ms = 0
            items.append((max(0, start_ms), title))
        if not items:
            return None, None
        items.sort(key=lambda pair: pair[0])

        intro = None
        outro = None
        intro_tokens = ("opening", "intro", "theme", "op")
        outro_tokens = ("ending", "credits", "credit", "preview", "next episode", "outro", "ed")

        for index, (start_ms, title) in enumerate(items):
            norm = self._norm_label(title)
            next_start = items[index + 1][0] if index + 1 < len(items) else int(duration_ms)
            if intro is None and start_ms <= int(TUNING.chapter_intro_max_start_ms):
                if any(token in norm for token in intro_tokens):
                    intro = SkipSegment(
                        start_ms=int(start_ms),
                        end_ms=max(int(start_ms), int(next_start)),
                        source="chapters",
                        confidence=0.92,
                    ).normalized(duration_ms)
            remaining = max(0, int(duration_ms) - int(start_ms))
            if outro is None and remaining >= int(TUNING.chapter_outro_min_remaining_ms):
                if any(token in norm for token in outro_tokens):
                    outro = SkipSegment(
                        start_ms=int(start_ms),
                        end_ms=int(duration_ms),
                        source="chapters",
                        confidence=0.88,
                    ).normalized(duration_ms)
        return intro, outro

    def _settings(self) -> Dict[str, object]:
        settings = self._data.get("settings", {})
        if not isinstance(settings, dict):
            settings = {}
            self._data["settings"] = settings
        return settings

    def _episodes(self) -> Dict[str, object]:
        episodes = self._data.get("episodes", {})
        if not isinstance(episodes, dict):
            episodes = {}
            self._data["episodes"] = episodes
        return episodes

    def _season_profiles(self) -> Dict[str, object]:
        profiles = self._data.get("season_profiles", {})
        if not isinstance(profiles, dict):
            profiles = {}
            self._data["season_profiles"] = profiles
        return profiles

    def _rebuild_profiles(self) -> None:
        buckets: Dict[str, Dict[str, object]] = {}
        for path_key, raw in list(self._episodes().items()):
            rec = self._episode_from_raw(str(path_key), raw)
            if rec is None or not rec.show_key:
                continue
            season_key = self._season_key(rec.show_key, rec.season_number)
            if not season_key:
                continue
            bucket = buckets.setdefault(season_key, {
                "show_key": rec.show_key,
                "season_number": rec.season_number,
                "intro": [],
                "outro": [],
            })
            if rec.intro is not None and rec.intro.confidence >= 0.72:
                cast_list = bucket["intro"]
                if isinstance(cast_list, list):
                    cast_list.append(rec.intro)
            if rec.outro is not None and rec.outro.confidence >= 0.72:
                cast_list = bucket["outro"]
                if isinstance(cast_list, list):
                    cast_list.append(rec.outro)

        profiles: Dict[str, object] = {}
        for season_key, bucket in buckets.items():
            intro = self._aggregate_segments(bucket.get("intro", []))
            outro = self._aggregate_segments(bucket.get("outro", []))
            sample_count = max(
                len(bucket.get("intro", [])) if isinstance(bucket.get("intro", []), list) else 0,
                len(bucket.get("outro", [])) if isinstance(bucket.get("outro", []), list) else 0,
            )
            profiles[season_key] = self._season_to_raw(
                SeasonSkipProfile(
                    season_key=str(season_key),
                    show_key=str(bucket.get("show_key") or ""),
                    season_number=int(bucket.get("season_number")) if bucket.get("season_number") is not None else None,
                    sample_count=int(sample_count),
                    intro=intro,
                    outro=outro,
                    updated_at=int(time.time()),
                )
            )
        self._data["season_profiles"] = profiles

    def _aggregate_segments(self, values: object) -> Optional[SkipSegment]:
        if not isinstance(values, list):
            return None
        segments = [seg for seg in values if isinstance(seg, SkipSegment)]
        if len(segments) < int(TUNING.season_profile_min_samples):
            return None
        starts = [int(seg.start_ms) for seg in segments]
        ends = [int(seg.end_ms) for seg in segments]
        med_start = int(median(starts))
        med_end = int(median(ends))
        if med_end <= med_start:
            return None
        for start_ms, end_ms in zip(starts, ends):
            if abs(int(start_ms) - med_start) > int(TUNING.season_profile_max_deviation_ms):
                return None
            if abs(int(end_ms) - med_end) > int(TUNING.season_profile_max_deviation_ms):
                return None
        confidence = min(0.96, 0.70 + (0.06 * len(segments)))
        return SkipSegment(start_ms=med_start, end_ms=med_end, source="season_profile", confidence=confidence)

    def _episode_from_raw(self, path_key: str, raw: object) -> Optional[EpisodeSkipMarkers]:
        if not isinstance(raw, dict):
            return None
        return EpisodeSkipMarkers(
            path_key=str(path_key),
            path=str(raw.get("path") or ""),
            show_key=str(raw.get("show_key") or ""),
            season_number=int(raw.get("season_number")) if raw.get("season_number") is not None else None,
            duration_ms=int(raw.get("duration_ms") or 0),
            intro=self._segment_from_raw(raw.get("intro")),
            outro=self._segment_from_raw(raw.get("outro")),
            updated_at=int(raw.get("updated_at") or 0),
        )

    def _episode_to_raw(self, rec: EpisodeSkipMarkers) -> Dict[str, object]:
        return {
            "path": str(rec.path or ""),
            "show_key": str(rec.show_key or ""),
            "season_number": int(rec.season_number) if rec.season_number is not None else None,
            "duration_ms": int(rec.duration_ms or 0),
            "intro": self._segment_to_raw(rec.intro),
            "outro": self._segment_to_raw(rec.outro),
            "updated_at": int(rec.updated_at or 0),
        }

    def _season_from_raw(self, season_key: str, raw: object) -> Optional[SeasonSkipProfile]:
        if not isinstance(raw, dict):
            return None
        return SeasonSkipProfile(
            season_key=str(season_key),
            show_key=str(raw.get("show_key") or ""),
            season_number=int(raw.get("season_number")) if raw.get("season_number") is not None else None,
            sample_count=int(raw.get("sample_count") or 0),
            intro=self._segment_from_raw(raw.get("intro")),
            outro=self._segment_from_raw(raw.get("outro")),
            updated_at=int(raw.get("updated_at") or 0),
        )

    def _season_to_raw(self, rec: SeasonSkipProfile) -> Dict[str, object]:
        return {
            "show_key": str(rec.show_key or ""),
            "season_number": int(rec.season_number) if rec.season_number is not None else None,
            "sample_count": int(rec.sample_count or 0),
            "intro": self._segment_to_raw(rec.intro),
            "outro": self._segment_to_raw(rec.outro),
            "updated_at": int(rec.updated_at or 0),
        }

    def _segment_from_raw(self, raw: object) -> Optional[SkipSegment]:
        if not isinstance(raw, dict):
            return None
        try:
            return SkipSegment(
                start_ms=int(raw.get("start_ms") or 0),
                end_ms=int(raw.get("end_ms") or 0),
                source=str(raw.get("source") or "manual"),
                confidence=float(raw.get("confidence") or 0.0),
            )
        except Exception:
            return None

    def _segment_to_raw(self, seg: Optional[SkipSegment]) -> Optional[Dict[str, object]]:
        if seg is None:
            return None
        return {
            "start_ms": int(seg.start_ms),
            "end_ms": int(seg.end_ms),
            "source": str(seg.source or "manual"),
            "confidence": float(seg.confidence),
        }

    def _season_key(self, show_key: str, season_number: Optional[int]) -> str:
        key = str(show_key or "").strip()
        if not key or season_number is None:
            return ""
        return f"{key}::season::{int(season_number)}"

    def _norm_label(self, value: str) -> str:
        return " ".join(str(value or "").strip().casefold().replace("_", " ").replace("-", " ").split())
