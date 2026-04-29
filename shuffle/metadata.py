from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from omega.app.text_naming import episode_fallback_label, extract_episode_title_from_filename, parse_season_episode
from omega.shuffle.debug import smart_debug
from omega.shuffle.models import SmartEpisode, SmartTitleProfile, SmartTitleSource, SmartShuffleTuning


# ============================================================
# Tuning zone
# ============================================================


@dataclass(frozen=True)
class MetadataTuning:
    default_metadata_confidence: float = 0.52
    default_arc_confidence: float = 0.36
    default_interruptibility_confidence: float = 0.34
    default_mood_confidence: float = 0.48
    favorite_bonus: float = 0.16
    selected_bonus: float = 0.10
    recent_bonus: float = 0.12
    hidden_gem_gap_days: int = 35


class SmartShuffleMetadataBuilder:
    def __init__(self, logger=None, tuning: MetadataTuning = MetadataTuning()) -> None:
        self._logger = logger
        self._tuning = tuning

    def build_profiles(
        self,
        sources: Sequence[SmartTitleSource],
        state: Dict[str, object],
        learned_biases: Dict[str, object],
        metadata_overrides: Dict[str, Dict[str, object]],
    ) -> Tuple[SmartTitleProfile, ...]:
        recent_keys = self._recent_keys(state)
        favorite_keys = {str(x).strip() for x in (state.get("favorites", []) if isinstance(state.get("favorites"), list) else []) if str(x).strip()}
        watched_map = state.get("watched", {}) if isinstance(state.get("watched"), dict) else {}
        progress_map = state.get("watch_progress", {}) if isinstance(state.get("watch_progress"), dict) else {}
        play_counts = state.get("play_counts", {}) if isinstance(state.get("play_counts"), dict) else {}
        last_watched = state.get("last_watched", {}) if isinstance(state.get("last_watched"), dict) else {}
        saved_mix_scores = self._saved_mix_scores(state)
        hidden_from_shuffle = metadata_overrides.get("titles", {}) if isinstance(metadata_overrides.get("titles"), dict) else {}
        cluster_bias_map = learned_biases.get("show_cluster_bias", {}) if isinstance(learned_biases.get("show_cluster_bias"), dict) else {}

        out: List[SmartTitleProfile] = []
        for source in list(sources or []):
            moods = self._infer_moods(source)
            secondary = self._secondary_moods(moods)
            runtime = self._estimate_runtime_minutes(source)
            play_count = int(play_counts.get(source.content_key, 0) or 0)
            watched = bool(watched_map.get(source.content_key, False))
            progress_row = progress_map.get(source.content_key, {}) if isinstance(progress_map.get(source.content_key), dict) else {}
            resume_ratio = float(progress_row.get("ratio", 0.0) or 0.0)
            if resume_ratio <= 0.0 or resume_ratio >= 0.97:
                resume_ratio = 0.0
            resume_updated_at = int(progress_row.get("updated_at", 0) or 0)
            resume_path = str(progress_row.get("path") or "").strip() if isinstance(progress_row, dict) else ""
            last_seen = int(last_watched.get(source.content_key, 0) or 0)

            familiarity = 0.20
            if source.content_key in favorite_keys:
                familiarity += float(self._tuning.favorite_bonus)
            if source.content_key in recent_keys:
                familiarity += float(self._tuning.recent_bonus)
            if source.selected_by_user:
                familiarity += float(self._tuning.selected_bonus)
            familiarity += min(0.22, float(play_count) * 0.035)
            if watched:
                familiarity += 0.10
            if resume_ratio > 0.0:
                familiarity += 0.06

            affinity_map = learned_biases.get("affinity", {}) if isinstance(learned_biases.get("affinity"), dict) else {}
            user_affinity = float(affinity_map.get(source.content_key, 0.0) or 0.0)
            hidden_gem = self._hidden_gem_score(source, state, learned_biases)
            episodes = self._build_episode_profiles(source)
            watched_completion = self._watched_completion_score(watched=watched, play_count=play_count, resume_ratio=resume_ratio)
            resume_freshness = self._resume_freshness_score(resume_updated_at)
            recency_score = self._recency_score(last_seen)
            fatigue_score = self._fatigue_score(last_seen=last_seen, resume_updated_at=resume_updated_at, resume_ratio=resume_ratio)
            saved_mix_score = float(saved_mix_scores.get(source.content_key, 0.0) or 0.0)
            cluster_bias = max(0.0, min(1.0, float(cluster_bias_map.get(source.content_key, 0) or 0) / 3.0))
            rewatch_comfort = self._rewatch_comfort_score(
                familiarity=familiarity,
                comfort=float(moods.get("comfort", 0.0) + moods.get("cozy", 0.0) + moods.get("warm", 0.0)) / 3.0,
                play_count=play_count,
                watched=watched,
                saved_mix_score=saved_mix_score,
            )
            family_score = self._family_friendly_score(source, moods)
            maturity_score = self._maturity_score(source, moods)
            subtitle_load = self._subtitle_load_score(source, moods)

            title_override = hidden_from_shuffle.get(source.content_key, {}) if isinstance(hidden_from_shuffle.get(source.content_key), dict) else {}
            is_hidden = bool(title_override.get("is_hidden_from_shuffle", False))
            cluster_pref = bool(title_override.get("better_in_clusters", False))
            single_safe = bool(title_override.get("safe_single_episode", False))

            profile = SmartTitleProfile(
                content_key=str(source.content_key),
                title=str(source.title),
                media_type=str(source.media_type or "tv"),
                genres=tuple(source.genres or ()),
                overview=str(source.overview or ""),
                primary_moods=moods,
                secondary_moods=secondary,
                energy_profile=self._energy_profile(moods),
                comfort_score=float(moods.get("comfort", 0.0) + moods.get("cozy", 0.0) + moods.get("wholesome", 0.0)) / 3.0,
                focus_required=self._focus_required(source, moods, episodes),
                emotional_weight=float(moods.get("emotional", 0.0) + moods.get("heartbreaking", 0.0) + moods.get("melancholic", 0.0)) / 3.0,
                darkness_level=float(moods.get("dark", 0.0) + moods.get("gritty", 0.0) + moods.get("high_stakes", 0.0)) / 3.0,
                novelty_score=self._novelty_score(source, moods, familiarity),
                late_night_friendliness=self._late_night_friendliness(moods, episodes),
                background_friendliness=self._background_friendliness(moods, episodes),
                user_familiarity_score=max(0.0, min(1.0, familiarity)),
                user_affinity_score=max(-0.6, min(1.0, user_affinity)),
                hidden_gem_score=hidden_gem,
                preferred_session_length_min=runtime * (2 if source.media_type != "movie" else 1),
                movie_runtime_minutes=runtime,
                play_path=str(source.play_path or ""),
                poster_path=str(source.poster_path or ""),
                backdrop_path=str(source.backdrop_path or ""),
                next_episodes=episodes,
                metadata_confidence=float(self._tuning.default_metadata_confidence),
                mood_confidence=float(self._tuning.default_mood_confidence),
                arc_confidence=float(self._tuning.default_arc_confidence + (0.10 if episodes else 0.0)),
                interruptibility_confidence=float(self._tuning.default_interruptibility_confidence + (0.12 if episodes else 0.0)),
                is_hidden_from_shuffle=is_hidden,
                best_as_cluster=cluster_pref or any(ep.arc_strength >= 0.72 for ep in episodes) or cluster_bias >= 0.34,
                safe_single_episode=single_safe or any(ep.interruptibility_score >= 0.72 for ep in episodes[:1]),
                selected_by_user=bool(source.selected_by_user),
                watched_completion_score=watched_completion,
                resume_progress_ratio=resume_ratio,
                resume_path=resume_path,
                resume_freshness_score=resume_freshness,
                recency_score=recency_score,
                fatigue_score=fatigue_score,
                rewatch_comfort_score=rewatch_comfort,
                saved_mix_score=saved_mix_score,
                cluster_bias=cluster_bias,
                family_friendly_score=family_score,
                maturity_score=maturity_score,
                subtitle_load_score=subtitle_load,
            )
            out.append(profile)

        smart_debug(self._logger, "POOL", "profiles built", len(out))
        return tuple(out)

    def _recent_keys(self, state: Dict[str, object]) -> Tuple[str, ...]:
        feed = state.get("recently_played", []) if isinstance(state.get("recently_played"), list) else []
        out: List[str] = []
        for row in feed:
            if not isinstance(row, dict):
                continue
            key = str(row.get("key") or "").strip()
            if key and key not in out:
                out.append(key)
        return tuple(out[:32])

    def _infer_moods(self, source: SmartTitleSource) -> Dict[str, float]:
        bucket = {
            "comfort": 0.08,
            "cozy": 0.06,
            "funny": 0.05,
            "absurd": 0.02,
            "adventurous": 0.10,
            "epic": 0.06,
            "intense": 0.08,
            "suspenseful": 0.06,
            "cerebral": 0.04,
            "emotional": 0.06,
            "heartbreaking": 0.02,
            "awe": 0.04,
            "nostalgic": 0.03,
            "romantic": 0.02,
            "dark": 0.04,
            "mysterious": 0.04,
            "heroic": 0.04,
            "chaotic": 0.03,
            "easygoing": 0.05,
            "background": 0.04,
            "prestige": 0.03,
            "high_stakes": 0.04,
            "weird": 0.03,
            "dreamy": 0.02,
            "soothing": 0.03,
            "warm": 0.03,
            "sharp": 0.03,
            "pulpy": 0.02,
            "stylish": 0.03,
            "uplifting": 0.03,
            "cathartic": 0.02,
            "melancholic": 0.02,
            "gritty": 0.03,
            "wholesome": 0.02,
        }
        terms = " ".join([source.title, source.overview, " ".join(source.genres)]).casefold()
        genre_map = {
            "comedy": {"funny": 0.55, "easygoing": 0.35, "comfort": 0.26},
            "animation": {"comfort": 0.30, "wholesome": 0.26, "background": 0.22},
            "anime": {"adventurous": 0.24, "emotional": 0.18, "cerebral": 0.16},
            "family": {"warm": 0.34, "comfort": 0.32, "wholesome": 0.38},
            "kids": {"background": 0.32, "wholesome": 0.30, "comfort": 0.26},
            "drama": {"emotional": 0.36, "prestige": 0.20, "melancholic": 0.18},
            "crime": {"gritty": 0.35, "suspenseful": 0.30, "dark": 0.20},
            "thriller": {"intense": 0.38, "suspenseful": 0.40, "dark": 0.24},
            "mystery": {"mysterious": 0.44, "cerebral": 0.24, "suspenseful": 0.24},
            "action": {"adventurous": 0.44, "intense": 0.30, "heroic": 0.18},
            "adventure": {"adventurous": 0.48, "heroic": 0.16, "awe": 0.14},
            "fantasy": {"awe": 0.32, "dreamy": 0.24, "epic": 0.22},
            "science fiction": {"cerebral": 0.28, "awe": 0.22, "epic": 0.18},
            "sci-fi": {"cerebral": 0.28, "awe": 0.22, "epic": 0.18},
            "romance": {"romantic": 0.46, "warm": 0.20, "emotional": 0.22},
            "horror": {"dark": 0.52, "intense": 0.34, "suspenseful": 0.30},
            "documentary": {"cerebral": 0.34, "prestige": 0.20, "background": 0.18},
            "history": {"prestige": 0.22, "cerebral": 0.28, "epic": 0.12},
        }
        for genre in source.genres:
            g = str(genre).casefold()
            for key, boosts in genre_map.items():
                if key in g:
                    for mood, delta in boosts.items():
                        bucket[mood] = min(1.0, bucket.get(mood, 0.0) + float(delta))

        text_rules = {
            "funny": ["funny", "comedy", "laugh", "sitcom"],
            "comfort": ["comfort", "comforting", "favorite", "warm"],
            "dark": ["dark", "grim", "violent", "murder", "killer"],
            "emotional": ["love", "loss", "family", "heart", "grief"],
            "intense": ["war", "hunt", "fight", "danger", "mission"],
            "cerebral": ["mind", "mystery", "future", "experiment", "detective"],
            "background": ["easy", "gentle", "slice of life", "casual"],
            "adventurous": ["quest", "journey", "explore", "treasure"],
            "nostalgic": ["classic", "retro", "old friends", "return"],
            "weird": ["strange", "odd", "weird", "surreal"],
        }
        for mood, tokens in text_rules.items():
            if any(tok in terms for tok in tokens):
                bucket[mood] = min(1.0, bucket.get(mood, 0.0) + 0.18)

        if source.media_type == "movie":
            bucket["prestige"] = min(1.0, bucket.get("prestige", 0.0) + 0.06)
            bucket["epic"] = min(1.0, bucket.get("epic", 0.0) + 0.05)
        else:
            bucket["comfort"] = min(1.0, bucket.get("comfort", 0.0) + 0.04)
            bucket["background"] = min(1.0, bucket.get("background", 0.0) + 0.04)

        return bucket

    def _secondary_moods(self, primary: Dict[str, float]) -> Dict[str, float]:
        ranked = sorted(primary.items(), key=lambda pair: pair[1], reverse=True)
        return {k: float(v) for k, v in ranked[3:6]}

    def _estimate_runtime_minutes(self, source: SmartTitleSource) -> int:
        genres = " ".join(source.genres).casefold()
        if source.media_type == "movie":
            return 108
        if any(token in genres for token in ("animation", "anime", "kids", "comedy")):
            return 24
        return 46

    def _build_episode_profiles(self, source: SmartTitleSource) -> Tuple[SmartEpisode, ...]:
        out: List[SmartEpisode] = []
        for raw_path in list(source.next_episode_paths or ()):
            ep_path = Path(str(raw_path))
            season_num, episode_num = parse_season_episode(ep_path.stem)
            runtime = self._estimate_runtime_minutes(source)
            try:
                title = extract_episode_title_from_filename(str(source.title or ""), ep_path.stem)
            except Exception:
                title = ""
            if not str(title or "").strip():
                fallback_index = int(episode_num) if episode_num is not None else (len(out) + 1)
                title = episode_fallback_label(fallback_index, season_num, episode_num)
            arc_group_id, arc_position, arc_strength, cliffhanger, interruptibility = self._episode_arc_shape(season_num, episode_num)
            continuity = max(0.18, min(0.98, arc_strength + (cliffhanger * 0.22)))
            must_continue = max(0.14, min(0.98, cliffhanger + (arc_strength * 0.20)))
            lore = 0.30 if source.media_type != "movie" else 0.18
            if any(token in " ".join(source.genres).casefold() for token in ("science", "fantasy", "mystery", "anime")):
                lore = min(0.88, lore + 0.26)
            moods = self._infer_moods(source)
            emotional = float(moods.get("emotional", 0.0) + moods.get("heartbreaking", 0.0) + moods.get("melancholic", 0.0)) / 3.0
            darkness = float(moods.get("dark", 0.0) + moods.get("gritty", 0.0)) / 2.0
            comfort = float(moods.get("comfort", 0.0) + moods.get("cozy", 0.0)) / 2.0
            comedy = float(moods.get("funny", 0.0) + moods.get("easygoing", 0.0)) / 2.0
            tension = float(moods.get("intense", 0.0) + moods.get("suspenseful", 0.0) + cliffhanger) / 3.0
            late_night = max(0.05, 1.0 - ((darkness * 0.62) + (lore * 0.38)))
            background = max(0.05, 1.0 - max(tension, lore * 0.88))
            out.append(
                SmartEpisode(
                    content_key=str(source.content_key),
                    show_title=str(source.title),
                    episode_path=str(ep_path),
                    season_number=season_num,
                    episode_number=episode_num,
                    runtime_minutes=int(runtime),
                    title=str(title),
                    arc_type="serialized" if arc_strength >= 0.58 else "standalone",
                    arc_group_id=arc_group_id,
                    arc_position=arc_position,
                    arc_strength=arc_strength,
                    cliffhanger_strength=cliffhanger,
                    interruptibility_score=interruptibility,
                    continuity_dependency=continuity,
                    must_continue_probability=must_continue,
                    lore_density=lore,
                    emotional_intensity=emotional,
                    tonal_darkness=darkness,
                    comfort_value=comfort,
                    comedy_value=comedy,
                    tension_value=tension,
                    late_night_friendliness=late_night,
                    background_friendliness=background,
                    metadata_confidence=0.42,
                )
            )
        return tuple(out)

    def _episode_arc_shape(self, season_num: Optional[int], episode_num: Optional[int]) -> Tuple[str, str, float, float, float]:
        if episode_num is None:
            return (f"season:{season_num or 0}:standalone", "standalone", 0.30, 0.18, 0.74)
        block = max(0, int((int(episode_num) - 1) // 3))
        group_id = f"season:{season_num or 0}:block:{block}"
        remainder = int(episode_num) % 3
        if int(episode_num) == 1:
            return (group_id, "entry", 0.68, 0.42, 0.32)
        if remainder == 1:
            return (group_id, "setup", 0.56, 0.32, 0.46)
        if remainder == 2:
            return (group_id, "escalation", 0.76, 0.62, 0.22)
        return (group_id, "resolution", 0.64, 0.48, 0.52)

    def _energy_profile(self, moods: Dict[str, float]) -> float:
        return max(0.0, min(1.0, (moods.get("intense", 0.0) * 0.45) + (moods.get("adventurous", 0.0) * 0.30) + (moods.get("funny", 0.0) * 0.10) + 0.08))

    def _focus_required(self, source: SmartTitleSource, moods: Dict[str, float], episodes: Sequence[SmartEpisode]) -> float:
        lore = max((ep.lore_density for ep in episodes), default=0.18)
        serialized = max((ep.continuity_dependency for ep in episodes), default=0.18)
        prestige = moods.get("prestige", 0.0)
        cerebral = moods.get("cerebral", 0.0)
        return max(0.0, min(1.0, (lore * 0.34) + (serialized * 0.24) + (prestige * 0.22) + (cerebral * 0.20)))

    def _novelty_score(self, source: SmartTitleSource, moods: Dict[str, float], familiarity: float) -> float:
        novelty = 0.28 + moods.get("weird", 0.0) * 0.24 + moods.get("stylish", 0.0) * 0.12
        if source.media_type == "movie":
            novelty += 0.06
        novelty -= familiarity * 0.26
        return max(0.0, min(1.0, novelty))

    def _late_night_friendliness(self, moods: Dict[str, float], episodes: Sequence[SmartEpisode]) -> float:
        episode_score = max((ep.late_night_friendliness for ep in episodes), default=0.58)
        darkness = moods.get("dark", 0.0) + moods.get("gritty", 0.0) + moods.get("high_stakes", 0.0)
        return max(0.0, min(1.0, episode_score - (darkness * 0.10) + 0.08))

    def _background_friendliness(self, moods: Dict[str, float], episodes: Sequence[SmartEpisode]) -> float:
        episode_score = max((ep.background_friendliness for ep in episodes), default=0.44)
        comfort = moods.get("comfort", 0.0) + moods.get("easygoing", 0.0)
        return max(0.0, min(1.0, episode_score + (comfort * 0.12)))

    def _hidden_gem_score(self, source: SmartTitleSource, state: Dict[str, object], learned_biases: Dict[str, object]) -> float:
        last_watched = state.get("last_watched", {}) if isinstance(state.get("last_watched"), dict) else {}
        play_counts = state.get("play_counts", {}) if isinstance(state.get("play_counts"), dict) else {}
        last_seen = int(last_watched.get(source.content_key, 0) or 0)
        play_count = int(play_counts.get(source.content_key, 0) or 0)
        if play_count <= 0:
            return 0.38
        if last_seen <= 0:
            return 0.34
        return max(0.0, min(1.0, 0.12 + (0.30 if play_count <= 3 else 0.0)))

    def _watched_completion_score(self, *, watched: bool, play_count: int, resume_ratio: float) -> float:
        if watched:
            return 1.0
        base = min(0.72, float(play_count) * 0.12)
        if resume_ratio > 0.0:
            base = max(base, min(0.94, float(resume_ratio)))
        return max(0.0, min(1.0, base))

    def _resume_freshness_score(self, updated_at: int) -> float:
        if updated_at <= 0:
            return 0.0
        age_hours = max(0.0, (float(time.time()) - float(updated_at)) / 3600.0)
        if age_hours <= 24.0:
            return 1.0
        if age_hours <= 72.0:
            return 0.84
        if age_hours <= 168.0:
            return 0.62
        if age_hours <= 336.0:
            return 0.42
        return 0.18

    def _recency_score(self, last_seen: int) -> float:
        if last_seen <= 0:
            return 0.0
        age_days = max(0.0, (float(time.time()) - float(last_seen)) / 86400.0)
        if age_days <= 1.0:
            return 1.0
        if age_days <= 3.0:
            return 0.82
        if age_days <= 10.0:
            return 0.58
        if age_days <= 30.0:
            return 0.28
        return 0.08

    def _fatigue_score(self, *, last_seen: int, resume_updated_at: int, resume_ratio: float) -> float:
        if resume_ratio > 0.0 and resume_updated_at > 0:
            # In-progress titles should feel "ready to continue", not punished for being recent.
            return max(0.0, min(0.52, self._recency_score(resume_updated_at) * 0.42))
        return self._recency_score(last_seen)

    def _rewatch_comfort_score(
        self,
        *,
        familiarity: float,
        comfort: float,
        play_count: int,
        watched: bool,
        saved_mix_score: float,
    ) -> float:
        base = (float(familiarity) * 0.44) + (float(comfort) * 0.28) + (float(saved_mix_score) * 0.18)
        if watched:
            base += 0.10
        if play_count >= 3:
            base += 0.08
        return max(0.0, min(1.0, base))

    def _saved_mix_scores(self, state: Dict[str, object]) -> Dict[str, float]:
        rows = state.get("saved_mixes", []) if isinstance(state.get("saved_mixes"), list) else []
        counts: Dict[str, float] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            weight = 1.0
            mode = str(row.get("mode") or "").strip().casefold()
            if mode in {"smart_shuffle", "trust_me", "continue_momentum", "movie_night"}:
                weight = 1.25
            keys = []
            keys.extend(str(x).strip() for x in (row.get("playlist_content_keys") or []) if str(x).strip())
            keys.extend(str(x).strip() for x in (row.get("seed_keys") or []) if str(x).strip())
            seen_local: set[str] = set()
            for key in keys:
                if key in seen_local:
                    continue
                seen_local.add(key)
                counts[key] = float(counts.get(key, 0.0) or 0.0) + weight
        if not counts:
            return {}
        max_score = max(float(v or 0.0) for v in counts.values())
        if max_score <= 0.0:
            return {}
        return {key: max(0.0, min(1.0, float(score) / float(max_score))) for key, score in counts.items()}

    def _family_friendly_score(self, source: SmartTitleSource, moods: Dict[str, float]) -> float:
        terms = " ".join(source.genres).casefold()
        score = 0.42
        if any(token in terms for token in ("family", "kids", "animation", "comedy")):
            score += 0.28
        if any(token in terms for token in ("horror", "thriller", "crime")):
            score -= 0.24
        score += float(moods.get("wholesome", 0.0) * 0.24)
        score += float(moods.get("comfort", 0.0) * 0.12)
        score -= float(moods.get("dark", 0.0) * 0.16)
        score -= float(moods.get("gritty", 0.0) * 0.12)
        return max(0.0, min(1.0, score))

    def _maturity_score(self, source: SmartTitleSource, moods: Dict[str, float]) -> float:
        terms = " ".join(source.genres).casefold()
        score = 0.34
        if any(token in terms for token in ("horror", "thriller", "crime", "war")):
            score += 0.22
        if source.media_type == "movie":
            score += 0.04
        score += float(moods.get("dark", 0.0) * 0.22)
        score += float(moods.get("gritty", 0.0) * 0.18)
        score += float(moods.get("high_stakes", 0.0) * 0.12)
        score -= float(moods.get("wholesome", 0.0) * 0.16)
        return max(0.0, min(1.0, score))

    def _subtitle_load_score(self, source: SmartTitleSource, moods: Dict[str, float]) -> float:
        terms = " ".join(source.genres).casefold()
        score = 0.32
        if any(token in terms for token in ("anime", "documentary", "history", "mystery")):
            score += 0.24
        if any(token in terms for token in ("comedy", "action", "family", "animation")):
            score -= 0.08
        score += float(moods.get("prestige", 0.0) * 0.14)
        score += float(moods.get("cerebral", 0.0) * 0.18)
        return max(0.0, min(1.0, score))


