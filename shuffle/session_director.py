from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

from omega.shuffle.debug import smart_debug
from omega.shuffle.intake import intake_time_budget_minutes
from omega.shuffle.models import (
    ScoredCandidate,
    SmartCandidate,
    SmartEpisode,
    SmartShuffleIntake,
    SmartShuffleSegment,
    SmartTitleProfile,
    SmartShuffleTuning,
)
from omega.shuffle.scoring import SmartShuffleScorer


# ============================================================
# Tuning zone
# ============================================================


@dataclass(frozen=True)
class SessionDirectorTuning:
    minimum_candidate_score: float = 0.34
    minimum_landing_score: float = 0.30
    minimum_warmup_score: float = 0.28
    max_session_segments: int = 4
    cluster_arc_strength_threshold: float = 0.64
    strong_continuity_threshold: float = 0.74
    late_night_hour: int = 22
    early_morning_hour: int = 5


@dataclass(frozen=True)
class SessionDirectorResult:
    segments: Tuple[SmartShuffleSegment, ...]
    scored_candidates: Tuple[ScoredCandidate, ...]
    protected_arc_active: bool
    variety_strategy: str
    confidence_base: float
    debug_notes: Tuple[str, ...]


class SmartShuffleSessionDirector:
    def __init__(
        self,
        scorer: SmartShuffleScorer,
        logger=None,
        tuning: SessionDirectorTuning = SessionDirectorTuning(),
        smart_tuning: SmartShuffleTuning = SmartShuffleTuning(),
    ) -> None:
        self._scorer = scorer
        self._logger = logger
        self._tuning = tuning
        self._smart_tuning = smart_tuning

    def build_session(
        self,
        *,
        profiles: Sequence[SmartTitleProfile],
        intake: SmartShuffleIntake,
        state: Dict[str, object],
    ) -> SessionDirectorResult:
        late_night = self._is_late_night()
        candidates, pool_notes = self._build_candidate_pool(profiles)
        recent_keys = self._recent_keys(state)
        momentum_keys = self._momentum_keys(state)
        budget_min = intake_time_budget_minutes(intake.available_time)
        requested_roles = self._phase_roles(intake, budget_min)
        momentum_focus_key = self._best_momentum_key(profiles=profiles, momentum_keys=momentum_keys, intake=intake)
        locked_story_key = momentum_focus_key if str(intake.session_mode) == "continue_momentum" else ""

        smart_debug(self._logger, "INTAKE", "mode", intake.session_mode, "budget", budget_min, "late", late_night)
        smart_debug(self._logger, "POOL", "candidates", len(candidates), "roles", ",".join(requested_roles))

        profiles_by_key = {str(profile.content_key): profile for profile in profiles}
        ranked_for_debug = self._scorer.score_candidates(
            candidates=candidates,
            intake=intake,
            profiles_by_key=profiles_by_key,
            requested_role="core",
            previous=None,
            time_remaining_min=budget_min,
            late_night=late_night,
            recent_keys=recent_keys,
            momentum_keys=momentum_keys,
        )

        remaining = int(budget_min)
        chosen_segments: List[SmartShuffleSegment] = []
        used_ids: set[str] = set()
        previous_candidate: Optional[SmartCandidate] = None
        protected_arc_active = False
        accumulated_scores: List[float] = []

        for role in requested_roles:
            available = [row.candidate for row in ranked_for_debug if row.candidate.candidate_id not in used_ids]
            if not available:
                break
            if locked_story_key and role in {"core", "peak", "landing"}:
                story_locked = [cand for cand in available if cand.content_key == locked_story_key]
                if story_locked:
                    available = story_locked
            ranked = self._scorer.score_candidates(
                candidates=available,
                intake=intake,
                profiles_by_key=profiles_by_key,
                requested_role=role,
                previous=previous_candidate,
                time_remaining_min=remaining,
                late_night=late_night,
                recent_keys=recent_keys,
                momentum_keys=momentum_keys,
            )
            chosen = self._pick_best_for_role(
                role=role,
                ranked=ranked,
                intake=intake,
                remaining=remaining,
                chosen_segments=tuple(chosen_segments),
                locked_story_key=locked_story_key,
                momentum_focus_key=momentum_focus_key,
            )
            if chosen is None:
                continue

            used_ids.add(chosen.candidate.candidate_id)
            previous_candidate = chosen.candidate
            remaining = max(0, remaining - int(chosen.candidate.runtime_minutes))
            accumulated_scores.append(float(chosen.breakdown.total))
            protected_arc_active = protected_arc_active or bool(chosen.candidate.protected_run)
            chosen_segments.append(self._candidate_to_segment(chosen.candidate, chosen.breakdown.total, role))
            if str(intake.variety_preference) in {"one_story", "mostly_one_story"} or str(intake.session_mode) == "continue_momentum":
                locked_story_key = str(chosen.candidate.content_key or locked_story_key)

            if len(chosen_segments) >= int(self._tuning.max_session_segments):
                break
            if remaining <= 12:
                break

        if not chosen_segments and ranked_for_debug:
            fallback = ranked_for_debug[0]
            chosen_segments.append(self._candidate_to_segment(fallback.candidate, fallback.breakdown.total, "core"))
            protected_arc_active = bool(fallback.candidate.protected_run)
            accumulated_scores.append(float(fallback.breakdown.total))
            remaining = max(0, remaining - int(fallback.candidate.runtime_minutes))

        # If the session is intentionally continuous, avoid adding tonal noise at the end.
        if len(chosen_segments) >= 2 and protected_arc_active and str(intake.variety_preference) in {"one_story", "mostly_one_story"}:
            first_key = chosen_segments[0].content_key
            chosen_segments = [seg for seg in chosen_segments if seg.content_key == first_key] or chosen_segments

        debug_notes = list(pool_notes)
        debug_notes.append(f"budget={budget_min}")
        debug_notes.append(f"remaining={remaining}")
        debug_notes.append(f"protected_arc_active={protected_arc_active}")
        debug_notes.append(f"momentum_focus={momentum_focus_key or '-'}")
        debug_notes.append(f"recent_keys={','.join(recent_keys[:4])}")

        return SessionDirectorResult(
            segments=tuple(chosen_segments),
            scored_candidates=tuple(ranked_for_debug),
            protected_arc_active=bool(protected_arc_active),
            variety_strategy=self._variety_strategy(intake, protected_arc_active),
            confidence_base=float(sum(accumulated_scores) / float(max(1, len(accumulated_scores)))) if accumulated_scores else 0.0,
            debug_notes=tuple(debug_notes),
        )

    def _build_candidate_pool(self, profiles: Sequence[SmartTitleProfile]) -> Tuple[Tuple[SmartCandidate, ...], Tuple[str, ...]]:
        candidates: List[SmartCandidate] = []
        notes: List[str] = []
        for profile in profiles:
            if profile.is_hidden_from_shuffle:
                notes.append(f"hidden:{profile.content_key}")
                continue
            if str(profile.media_type) == "movie":
                if profile.movie_runtime_minutes <= 0:
                    notes.append(f"no-runtime:{profile.content_key}")
                    continue
                if not str(profile.play_path or "").strip():
                    notes.append(f"no-play-path:{profile.content_key}")
                    continue
                candidates.append(self._movie_candidate(profile))
                continue
            if not profile.next_episodes:
                notes.append(f"no-episodes:{profile.content_key}")
                continue
            first = profile.next_episodes[0]
            candidates.append(self._episode_candidate(profile, first))
            cluster = self._cluster_candidate(profile)
            if cluster is not None:
                candidates.append(cluster)
            landing = self._landing_candidate(profile)
            if landing is not None:
                candidates.append(landing)
        return tuple(candidates), tuple(notes)

    def _movie_candidate(self, profile: SmartTitleProfile) -> SmartCandidate:
        intensity = max(0.12, min(1.0, (float(profile.energy_profile) * 0.36) + (float(profile.darkness_level) * 0.26) + (float(profile.emotional_weight) * 0.18) + 0.20))
        stop_quality = 0.82 if profile.movie_runtime_minutes <= 130 else 0.70
        media_paths = (str(profile.play_path),) if str(profile.play_path or "").strip() else ()
        return SmartCandidate(
            candidate_id=f"{profile.content_key}:movie",
            content_key=str(profile.content_key),
            title=str(profile.title),
            media_type="movie",
            role_hint="movie",
            runtime_minutes=int(profile.movie_runtime_minutes),
            media_paths=media_paths,
            moods=dict(profile.primary_moods),
            continuity_pressure=0.18,
            protected_run=False,
            stop_quality=float(stop_quality),
            novelty_score=float(profile.novelty_score),
            familiarity_score=float(profile.user_familiarity_score),
            intensity_score=float(intensity),
            background_score=float(profile.background_friendliness),
            late_night_score=float(profile.late_night_friendliness),
            explanation_tags=("main-event", "movie"),
        )

    def _episode_candidate(self, profile: SmartTitleProfile, episode: SmartEpisode) -> SmartCandidate:
        intensity = max(0.12, min(1.0, (float(episode.tension_value) * 0.44) + (float(episode.emotional_intensity) * 0.24) + (float(episode.tonal_darkness) * 0.16) + 0.16))
        tags = ["easy entry" if episode.interruptibility_score >= 0.58 else "story pressure"]
        if episode.arc_strength >= 0.60:
            tags.append("arc-aware")
        return SmartCandidate(
            candidate_id=f"{profile.content_key}:single:{episode.episode_path}",
            content_key=str(profile.content_key),
            title=f"{profile.title} • Next episode",
            media_type="tv",
            role_hint="single",
            runtime_minutes=int(episode.runtime_minutes),
            media_paths=(str(episode.episode_path),),
            moods=dict(profile.primary_moods),
            continuity_pressure=float(episode.must_continue_probability),
            protected_run=False,
            stop_quality=float(episode.interruptibility_score),
            novelty_score=float(profile.novelty_score),
            familiarity_score=float(profile.user_familiarity_score),
            intensity_score=float(intensity),
            background_score=float(episode.background_friendliness),
            late_night_score=float(episode.late_night_friendliness),
            explanation_tags=tuple(tags),
        )

    def _cluster_candidate(self, profile: SmartTitleProfile) -> Optional[SmartCandidate]:
        episodes = list(profile.next_episodes[:3])
        if len(episodes) < 2:
            return None
        lead = episodes[0]
        if not (
            profile.best_as_cluster
            or lead.arc_strength >= float(self._tuning.cluster_arc_strength_threshold)
            or lead.must_continue_probability >= 0.60
            or float(profile.cluster_bias) >= 0.34
            or float(profile.resume_progress_ratio) >= 0.18
        ):
            return None
        long_run = (
            len(episodes) >= 3
            and (
                lead.arc_strength >= 0.70
                or float(profile.cluster_bias) >= 0.50
                or float(profile.resume_progress_ratio) >= 0.24
            )
        )
        chosen = episodes[:3] if long_run else episodes[:2]
        runtime = sum(int(ep.runtime_minutes) for ep in chosen)
        intensity = sum(float(ep.tension_value) + float(ep.emotional_intensity) for ep in chosen) / float(max(1, len(chosen) * 2))
        stop_quality = float(chosen[-1].interruptibility_score)
        if chosen[-1].arc_position in {"resolution", "cooldown"}:
            stop_quality = min(1.0, stop_quality + 0.18)
        return SmartCandidate(
            candidate_id=f"{profile.content_key}:cluster:{len(chosen)}",
            content_key=str(profile.content_key),
            title=f"{profile.title} • {len(chosen)} episode run",
            media_type="tv",
            role_hint="cluster",
            runtime_minutes=int(runtime),
            media_paths=tuple(str(ep.episode_path) for ep in chosen),
            moods=dict(profile.primary_moods),
            continuity_pressure=max(float(ep.must_continue_probability) for ep in chosen),
            protected_run=True,
            stop_quality=max(0.20, min(1.0, stop_quality)),
            novelty_score=float(profile.novelty_score),
            familiarity_score=float(profile.user_familiarity_score),
            intensity_score=max(0.12, min(1.0, float(intensity))),
            background_score=sum(float(ep.background_friendliness) for ep in chosen) / float(max(1, len(chosen))),
            late_night_score=sum(float(ep.late_night_friendliness) for ep in chosen) / float(max(1, len(chosen))),
            explanation_tags=("protected arc", "continuity"),
        )

    def _landing_candidate(self, profile: SmartTitleProfile) -> Optional[SmartCandidate]:
        if not profile.next_episodes:
            return None
        for episode in profile.next_episodes:
            if episode.interruptibility_score >= 0.62 or episode.arc_position in {"resolution", "cooldown"}:
                intensity = max(0.10, min(1.0, (float(episode.tension_value) * 0.34) + (float(episode.emotional_intensity) * 0.20) + (float(episode.tonal_darkness) * 0.12) + 0.12))
                return SmartCandidate(
                    candidate_id=f"{profile.content_key}:landing:{episode.episode_path}",
                    content_key=str(profile.content_key),
                    title=f"{profile.title} • Clean stop",
                    media_type="tv",
                    role_hint="landing",
                    runtime_minutes=int(episode.runtime_minutes),
                    media_paths=(str(episode.episode_path),),
                    moods=dict(profile.primary_moods),
                    continuity_pressure=max(0.05, float(episode.must_continue_probability) * 0.68),
                    protected_run=False,
                    stop_quality=min(1.0, float(episode.interruptibility_score) + 0.16),
                    novelty_score=float(profile.novelty_score),
                    familiarity_score=float(profile.user_familiarity_score),
                    intensity_score=float(intensity),
                    background_score=float(episode.background_friendliness),
                    late_night_score=float(episode.late_night_friendliness),
                    explanation_tags=("soft exit", "clean stop"),
                )
        return None

    def _pick_best_for_role(
        self,
        *,
        role: str,
        ranked: Sequence[ScoredCandidate],
        intake: SmartShuffleIntake,
        remaining: int,
        chosen_segments: Sequence[SmartShuffleSegment],
        locked_story_key: str = "",
        momentum_focus_key: str = "",
    ) -> Optional[ScoredCandidate]:
        minimum = float(self._tuning.minimum_candidate_score)
        if role == "landing":
            minimum = float(self._tuning.minimum_landing_score)
        elif role == "warmup":
            minimum = float(self._tuning.minimum_warmup_score)

        chosen_keys = {seg.content_key for seg in chosen_segments}
        one_story = str(intake.variety_preference) in {"one_story", "mostly_one_story"}
        movie_mode = str(intake.session_mode) == "movie_night"

        if movie_mode and role == "warmup":
            short_openers = [
                row for row in ranked
                if row.candidate.media_type != "movie" and row.candidate.runtime_minutes <= 42 and row.breakdown.total >= minimum
            ]
            if short_openers:
                return short_openers[0]

        for row in ranked:
            candidate = row.candidate
            if row.breakdown.total < minimum:
                continue
            if candidate.runtime_minutes > remaining + 10:
                continue
            if movie_mode and role in {"core", "peak"} and candidate.media_type != "movie":
                continue
            if locked_story_key and role in {"core", "peak", "landing"} and candidate.content_key != locked_story_key:
                continue
            if one_story and chosen_keys and candidate.content_key not in chosen_keys and role != "warmup":
                continue
            if not one_story and str(intake.variety_preference) in {"mix_it_up", "anything"} and chosen_keys and role in {"peak", "landing"} and candidate.content_key in chosen_keys and not candidate.protected_run:
                continue
            if momentum_focus_key and str(intake.session_mode) == "continue_momentum" and role in {"core", "peak"}:
                if candidate.content_key != momentum_focus_key and candidate.protected_run:
                    continue
            return row
        return None

    def _candidate_to_segment(self, candidate: SmartCandidate, confidence: float, role: str) -> SmartShuffleSegment:
        expl = {
            "warmup": "Low-friction opener matched to your current headspace.",
            "core": "This is the main block that best fits the night you described.",
            "peak": "This is where the session reaches its strongest pull.",
            "landing": "This is positioned to end the night the way you asked.",
        }.get(str(role), "This pick fits the current session shape.")
        badges = list(candidate.explanation_tags)
        badges.insert(0, role.replace("_", " ").title())
        return SmartShuffleSegment(
            role=str(role),
            title=str(candidate.title),
            media_type=str(candidate.media_type),
            content_key=str(candidate.content_key),
            runtime_minutes=int(candidate.runtime_minutes),
            media_paths=tuple(candidate.media_paths),
            protected_run=bool(candidate.protected_run),
            explanation=str(expl),
            confidence=float(max(0.0, min(1.0, confidence))),
            badges=tuple(badges[:4]),
        )

    def _recent_keys(self, state: Dict[str, object]) -> Tuple[str, ...]:
        rows = state.get("recently_played", []) if isinstance(state.get("recently_played"), list) else []
        out: List[str] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            key = str(row.get("key") or "").strip()
            if key and key not in out:
                out.append(key)
        return tuple(out[:12])

    def _momentum_keys(self, state: Dict[str, object]) -> Tuple[str, ...]:
        progress = state.get("watch_progress", {}) if isinstance(state.get("watch_progress"), dict) else {}
        ranked = sorted(
            (
                (str(key).strip(), int(payload.get("updated_at", 0) or 0))
                for key, payload in progress.items()
                if str(key).strip() and isinstance(payload, dict)
            ),
            key=lambda pair: pair[1],
            reverse=True,
        )
        out = [key for key, _updated_at in ranked]
        return tuple(out[:8])

    def _phase_roles(self, intake: SmartShuffleIntake, budget_min: int) -> Tuple[str, ...]:
        if str(intake.session_mode) == "continue_momentum":
            if budget_min < 40:
                return ("core",)
            if budget_min < 90:
                return ("core", "landing")
            if budget_min < 140:
                return ("core", "peak", "landing")
            return ("warmup", "core", "peak", "landing")
        if str(intake.session_mode) == "movie_night":
            if budget_min >= 150:
                return ("warmup", "core", "landing")
            return ("core", "landing")
        if budget_min < 35:
            return ("core",)
        if budget_min < 70:
            return ("core", "landing")
        if budget_min < 115:
            return ("warmup", "core")
        if str(intake.variety_preference) in {"mix_it_up", "anything"}:
            return ("warmup", "core", "landing")
        return ("warmup", "core", "peak", "landing")

    def _variety_strategy(self, intake: SmartShuffleIntake, protected_arc_active: bool) -> str:
        if str(intake.session_mode) == "movie_night":
            return "movie_first"
        if protected_arc_active:
            return "protected_run"
        if str(intake.variety_preference) in {"mix_it_up", "anything"}:
            return "guided_mix"
        if str(intake.variety_preference) in {"one_story", "mostly_one_story"}:
            return "single_show_bias"
        return "balanced"

    def _is_late_night(self) -> bool:
        hour = int(datetime.now().hour)
        return hour >= int(self._tuning.late_night_hour) or hour <= int(self._tuning.early_morning_hour)

    def _best_momentum_key(
        self,
        *,
        profiles: Sequence[SmartTitleProfile],
        momentum_keys: Sequence[str],
        intake: SmartShuffleIntake,
    ) -> str:
        if not momentum_keys:
            return ""
        lookup = {str(profile.content_key): profile for profile in profiles}
        best_key = ""
        best_score = -1.0
        for key in momentum_keys:
            profile = lookup.get(str(key))
            if profile is None:
                continue
            score = (
                float(profile.resume_progress_ratio) * 0.42
                + float(profile.resume_freshness_score) * 0.28
                + float(profile.cluster_bias) * 0.14
                + max(0.0, float(profile.user_affinity_score)) * 0.10
                + float(profile.saved_mix_score) * 0.06
            )
            if str(intake.session_mode) == "continue_momentum":
                score += 0.12
            if score > best_score:
                best_score = score
                best_key = str(key)
        return best_key


