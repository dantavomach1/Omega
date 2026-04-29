from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Sequence, Tuple

from omega.shuffle.debug import smart_debug
from omega.shuffle.intake import intake_time_budget_minutes
from omega.shuffle.models import (
    ScoreBreakdown,
    ScoredCandidate,
    SmartCandidate,
    SmartShuffleIntake,
    SmartTitleProfile,
)


# ============================================================
# Tuning zone
# ============================================================


@dataclass(frozen=True)
class ScoringTuning:
    min_practical_runtime_ratio: float = 0.55
    runtime_overflow_grace_min: int = 14
    total_weight_mood: float = 0.22
    total_weight_cognitive: float = 0.16
    total_weight_session: float = 0.16
    total_weight_continuity: float = 0.14
    total_weight_personal: float = 0.12
    total_weight_practical: float = 0.12
    total_weight_sequence: float = 0.08
    late_night_hour: int = 22


MOOD_TARGETS: Dict[str, Dict[str, float]] = {
    "comfort": {"comfort": 1.0, "cozy": 0.9, "warm": 0.7, "wholesome": 0.8, "easygoing": 0.5, "background": 0.3},
    "fun": {"funny": 1.0, "uplifting": 0.6, "stylish": 0.4, "adventurous": 0.5, "chaotic": 0.3},
    "adventure": {"adventurous": 1.0, "heroic": 0.7, "epic": 0.7, "awe": 0.6, "pulpy": 0.3},
    "deep_story": {"prestige": 0.8, "cerebral": 0.8, "emotional": 0.5, "high_stakes": 0.6, "mysterious": 0.5},
    "intense": {"intense": 1.0, "suspenseful": 0.9, "high_stakes": 0.7, "gritty": 0.4, "dark": 0.3},
    "emotional": {"emotional": 1.0, "heartbreaking": 0.7, "cathartic": 0.7, "warm": 0.3, "melancholic": 0.5},
    "easy_background": {"background": 1.0, "easygoing": 0.8, "soothing": 0.7, "comfort": 0.5, "cozy": 0.4},
    "surprise_me": {"weird": 0.6, "stylish": 0.5, "novelty": 0.7, "adventurous": 0.5, "chaotic": 0.4},
}

ENERGY_TARGETS = {
    "drained": 0.18,
    "low_okay": 0.32,
    "neutral": 0.50,
    "alert": 0.70,
    "locked_in": 0.88,
}

FOCUS_TARGETS = {
    "very_low": 0.16,
    "some_focus": 0.42,
    "good_focus": 0.70,
    "full_attention": 0.90,
}

FAMILIARITY_TARGETS = {
    "familiar_only": 0.95,
    "mostly_familiar": 0.78,
    "mix": 0.56,
    "fresh": 0.34,
    "surprise": 0.48,
}

INTENSITY_TARGETS = {
    "very_light": 0.18,
    "light_medium": 0.34,
    "medium": 0.56,
    "heavy_okay": 0.80,
    "anything": 0.62,
}

VARIETY_TARGETS = {
    "one_story": 0.92,
    "mostly_one_story": 0.74,
    "balanced": 0.52,
    "mix_it_up": 0.28,
    "anything": 0.40,
}

PACE_TARGETS = {
    "slow_cozy": 0.22,
    "smooth": 0.44,
    "build_up": 0.56,
    "start_strong": 0.76,
    "rollercoaster": 0.66,
}

ENDING_TARGETS = {
    "clean_stop": (0.82, 0.18),
    "cliffhanger_okay": (0.30, 0.84),
    "end_soft": (0.88, 0.14),
    "end_strong": (0.46, 0.66),
    "dont_care": (0.52, 0.52),
}


class SmartShuffleScorer:
    def __init__(self, logger=None, tuning: ScoringTuning = ScoringTuning()) -> None:
        self._logger = logger
        self._tuning = tuning

    def score_candidates(
        self,
        *,
        candidates: Sequence[SmartCandidate],
        intake: SmartShuffleIntake,
        profiles_by_key: Dict[str, SmartTitleProfile],
        requested_role: str,
        previous: Optional[SmartCandidate] = None,
        time_remaining_min: Optional[int] = None,
        late_night: bool = False,
        recent_keys: Sequence[str] = (),
        momentum_keys: Sequence[str] = (),
    ) -> Tuple[ScoredCandidate, ...]:
        remaining = int(time_remaining_min or intake_time_budget_minutes(intake.available_time))
        out = []
        for candidate in candidates:
            profile = profiles_by_key.get(candidate.content_key)
            breakdown, notes = self._score_one(
                candidate=candidate,
                profile=profile,
                intake=intake,
                requested_role=requested_role,
                previous=previous,
                time_remaining_min=remaining,
                late_night=late_night,
                recent_keys=recent_keys,
                momentum_keys=momentum_keys,
            )
            out.append(ScoredCandidate(candidate=candidate, breakdown=breakdown, rejection_notes=tuple(notes)))

        ranked = tuple(sorted(out, key=lambda row: row.breakdown.total, reverse=True))
        smart_debug(self._logger, "SCORE", requested_role, "count", len(ranked), "top", ", ".join(f"{x.candidate.title}:{x.breakdown.total:.2f}" for x in ranked[:5]))
        return ranked

    def _score_one(
        self,
        *,
        candidate: SmartCandidate,
        profile: Optional[SmartTitleProfile],
        intake: SmartShuffleIntake,
        requested_role: str,
        previous: Optional[SmartCandidate],
        time_remaining_min: int,
        late_night: bool,
        recent_keys: Sequence[str],
        momentum_keys: Sequence[str],
    ) -> Tuple[ScoreBreakdown, Tuple[str, ...]]:
        notes = []
        mood_fit = self._mood_fit(candidate, intake)
        cognitive_fit = self._cognitive_fit(candidate, profile, intake, late_night)
        session_utility = self._session_utility(candidate, requested_role, intake, time_remaining_min)
        narrative_continuity = self._continuity_fit(candidate, profile, intake, requested_role)
        personal_taste = self._personal_fit(candidate, profile, intake, recent_keys, momentum_keys)
        practical_fit = self._practical_fit(candidate, intake, time_remaining_min)
        sequence_harmony = self._sequence_fit(candidate, previous, intake)

        if candidate.runtime_minutes > (time_remaining_min + int(self._tuning.runtime_overflow_grace_min)):
            notes.append("runtime over budget")
        if intake.avoid_dark_content and candidate.intensity_score >= 0.76:
            notes.append("too heavy for avoid-dark request")
        if intake.background_friendly_only and candidate.background_score <= 0.42:
            notes.append("not background friendly enough")
        if candidate.media_type == "movie" and intake.prefer_tv_over_movies:
            notes.append("tv preference penalty")
        if candidate.media_type != "movie" and intake.prefer_movies_over_tv:
            notes.append("movie preference penalty")
        if intake.family_safe and profile is not None and float(profile.family_friendly_score) <= 0.42:
            notes.append("not family-safe enough")
        if intake.mature_only and profile is not None and float(profile.maturity_score) <= 0.42:
            notes.append("not mature enough")
        if intake.avoid_subtitles_tonight and profile is not None and float(profile.subtitle_load_score) >= 0.66:
            notes.append("subtitle load too high")

        total = (
            mood_fit * float(self._tuning.total_weight_mood)
            + cognitive_fit * float(self._tuning.total_weight_cognitive)
            + session_utility * float(self._tuning.total_weight_session)
            + narrative_continuity * float(self._tuning.total_weight_continuity)
            + personal_taste * float(self._tuning.total_weight_personal)
            + practical_fit * float(self._tuning.total_weight_practical)
            + sequence_harmony * float(self._tuning.total_weight_sequence)
        )
        if notes and total > 0.0:
            total *= 0.96

        return (
            ScoreBreakdown(
                mood_fit=float(max(0.0, min(1.0, mood_fit))),
                cognitive_fit=float(max(0.0, min(1.0, cognitive_fit))),
                session_utility=float(max(0.0, min(1.0, session_utility))),
                narrative_continuity=float(max(0.0, min(1.0, narrative_continuity))),
                personal_taste=float(max(0.0, min(1.0, personal_taste))),
                practical_fit=float(max(0.0, min(1.0, practical_fit))),
                sequence_harmony=float(max(0.0, min(1.0, sequence_harmony))),
                total=float(max(0.0, min(1.0, total))),
            ),
            tuple(notes),
        )

    def _mood_fit(self, candidate: SmartCandidate, intake: SmartShuffleIntake) -> float:
        target = dict(MOOD_TARGETS.get(str(intake.night_kind or "surprise_me"), MOOD_TARGETS["surprise_me"]))
        if intake.show_hidden_gems:
            target["novelty"] = max(target.get("novelty", 0.0), 0.55)
        total_weight = 0.0
        score = 0.0
        for mood, weight in target.items():
            total_weight += float(weight)
            if mood == "novelty":
                score += float(weight) * float(candidate.novelty_score)
            else:
                score += float(weight) * float(candidate.moods.get(mood, 0.0))
        base = score / float(max(0.01, total_weight))
        if intake.avoid_dark_content:
            base -= float(candidate.moods.get("dark", 0.0) * 0.32)
            base -= float(candidate.moods.get("gritty", 0.0) * 0.18)
        if intake.rewatch_safe_only:
            base = (base * 0.72) + (float(candidate.familiarity_score) * 0.28)
        return max(0.0, min(1.0, base))

    def _cognitive_fit(self, candidate: SmartCandidate, profile: Optional[SmartTitleProfile], intake: SmartShuffleIntake, late_night: bool) -> float:
        energy_target = float(ENERGY_TARGETS.get(str(intake.current_energy or "neutral"), 0.50))
        focus_target = float(FOCUS_TARGETS.get(str(intake.focus_availability or "some_focus"), 0.42))
        intensity_target = float(INTENSITY_TARGETS.get(str(intake.emotional_intensity or "medium"), 0.56))
        focus_required = float(getattr(profile, "focus_required", candidate.intensity_score))
        intensity_gap = 1.0 - min(1.0, abs(float(candidate.intensity_score) - intensity_target))
        energy_gap = 1.0 - min(1.0, abs(float(candidate.intensity_score) - energy_target))
        focus_gap = 1.0 - min(1.0, abs(float(focus_required) - focus_target))
        base = (intensity_gap * 0.34) + (energy_gap * 0.28) + (focus_gap * 0.38)
        if str(intake.focus_availability) == "very_low":
            base = (base * 0.72) + (float(candidate.background_score) * 0.28)
        if late_night:
            base = (base * 0.76) + (float(candidate.late_night_score) * 0.24)
        if profile is not None and intake.avoid_subtitles_tonight:
            base = (base * 0.78) + ((1.0 - float(profile.subtitle_load_score)) * 0.22)
        return max(0.0, min(1.0, base))

    def _session_utility(self, candidate: SmartCandidate, requested_role: str, intake: SmartShuffleIntake, time_remaining_min: int) -> float:
        requested = str(requested_role or "core")
        pace_target = float(PACE_TARGETS.get(str(intake.tonight_pace or "smooth"), 0.44))
        clean_stop_target, cliffhanger_target = ENDING_TARGETS.get(str(intake.end_preference or "clean_stop"), ENDING_TARGETS["clean_stop"])
        role_base = 0.46
        if requested == "warmup":
            role_base = (float(candidate.background_score) * 0.42) + (float(candidate.familiarity_score) * 0.22) + ((1.0 - float(candidate.intensity_score)) * 0.36)
        elif requested == "landing":
            role_base = (float(candidate.stop_quality) * clean_stop_target) + ((1.0 - float(candidate.continuity_pressure)) * 0.18) + ((1.0 - float(candidate.intensity_score)) * 0.16) + (float(candidate.familiarity_score) * 0.12)
            role_base += float(candidate.continuity_pressure) * cliffhanger_target * 0.20
        elif requested == "peak":
            role_base = (float(candidate.intensity_score) * 0.44) + (float(candidate.continuity_pressure) * 0.24) + (pace_target * 0.16) + (float(candidate.novelty_score) * 0.16)
        else:
            role_base = (float(candidate.intensity_score) * 0.26) + (float(candidate.continuity_pressure) * 0.26) + (float(candidate.stop_quality) * 0.18) + (pace_target * 0.14) + (float(candidate.familiarity_score) * 0.16)

        if candidate.runtime_minutes > time_remaining_min:
            ratio = float(time_remaining_min) / float(max(1, candidate.runtime_minutes))
            role_base *= max(0.0, min(1.0, ratio / float(self._tuning.min_practical_runtime_ratio)))
        return max(0.0, min(1.0, role_base))

    def _continuity_fit(self, candidate: SmartCandidate, profile: Optional[SmartTitleProfile], intake: SmartShuffleIntake, requested_role: str) -> float:
        continuity_target = float(VARIETY_TARGETS.get(str(intake.variety_preference or "balanced"), 0.52))
        continuity_pref = max(continuity_target, 0.78) if intake.protect_story_arcs else continuity_target
        if str(intake.session_mode) in {"continue_momentum", "one_story", "deep_immersion"}:
            continuity_pref = max(continuity_pref, 0.88)
        if profile is not None:
            continuity_pref = max(
                continuity_pref,
                (float(profile.resume_progress_ratio) * 0.34) + (float(profile.cluster_bias) * 0.30),
            )
        if requested_role == "landing" and str(intake.end_preference) == "clean_stop":
            return max(0.0, min(1.0, (float(candidate.stop_quality) * 0.68) + ((1.0 - float(candidate.continuity_pressure)) * 0.32)))
        if continuity_pref >= 0.60:
            return max(0.0, min(1.0, (float(candidate.continuity_pressure) * 0.74) + (0.20 if candidate.protected_run else 0.0)))
        return max(0.0, min(1.0, (float(candidate.stop_quality) * 0.54) + ((1.0 - float(candidate.continuity_pressure)) * 0.46)))

    def _personal_fit(
        self,
        candidate: SmartCandidate,
        profile: Optional[SmartTitleProfile],
        intake: SmartShuffleIntake,
        recent_keys: Sequence[str],
        momentum_keys: Sequence[str],
    ) -> float:
        recent_set = {str(x) for x in recent_keys}
        momentum_set = {str(x) for x in momentum_keys}
        familiarity_target = float(FAMILIARITY_TARGETS.get(str(intake.familiarity_preference or "mix"), 0.56))
        familiarity_gap = 1.0 - min(1.0, abs(float(candidate.familiarity_score) - familiarity_target))
        affinity = float(getattr(profile, "user_affinity_score", 0.0))
        hidden_gem = float(getattr(profile, "hidden_gem_score", 0.0))
        base = (familiarity_gap * 0.40) + ((affinity + 0.6) / 1.6 * 0.24) + (float(candidate.novelty_score) * 0.08)
        if profile is not None:
            base += float(profile.rewatch_comfort_score) * 0.10
            base += float(profile.saved_mix_score) * 0.08
            if candidate.content_key in momentum_set or str(intake.session_mode) == "continue_momentum":
                base += float(profile.resume_progress_ratio) * 0.16
                base += float(profile.resume_freshness_score) * 0.12
            elif candidate.content_key in recent_set:
                base -= float(profile.fatigue_score) * 0.18
        if intake.show_hidden_gems or intake.bring_back_forgotten_favorites:
            base += hidden_gem * 0.18
        if candidate.content_key in momentum_set:
            base += 0.16
        if candidate.content_key in recent_set and candidate.content_key not in momentum_set and str(intake.variety_preference) in {"mix_it_up", "anything"}:
            base -= 0.08
        if intake.rewatch_safe_only:
            comfort = float(getattr(profile, "rewatch_comfort_score", candidate.familiarity_score))
            base = (base * 0.68) + (comfort * 0.32)
        return max(0.0, min(1.0, base))

    def _practical_fit(self, candidate: SmartCandidate, intake: SmartShuffleIntake, time_remaining_min: int) -> float:
        ratio = float(time_remaining_min) / float(max(1, candidate.runtime_minutes))
        if candidate.runtime_minutes <= time_remaining_min:
            runtime_fit = min(1.0, 0.66 + (ratio * 0.18))
        else:
            runtime_fit = max(0.0, min(1.0, ratio / float(self._tuning.min_practical_runtime_ratio)))

        media_fit = 0.72
        if candidate.media_type == "movie":
            if intake.prefer_movies_over_tv or str(intake.session_mode) == "movie_night":
                media_fit = 0.96
            elif intake.prefer_tv_over_movies:
                media_fit = 0.34
        else:
            if intake.prefer_tv_over_movies:
                media_fit = 0.94
            elif intake.prefer_movies_over_tv or str(intake.session_mode) == "movie_night":
                media_fit = 0.40

        late_fit = float(candidate.late_night_score) if intake.current_energy in {"drained", "low_okay"} else 0.64
        return max(0.0, min(1.0, (runtime_fit * 0.54) + (media_fit * 0.28) + (late_fit * 0.18)))

    def _sequence_fit(self, candidate: SmartCandidate, previous: Optional[SmartCandidate], intake: SmartShuffleIntake) -> float:
        if previous is None:
            return 0.70
        shared = 0.0
        for key in set(previous.moods.keys()) | set(candidate.moods.keys()):
            shared += min(float(previous.moods.get(key, 0.0)), float(candidate.moods.get(key, 0.0)))
        shared = max(0.0, min(1.0, shared / 3.0))
        intensity_gap = 1.0 - min(1.0, abs(float(previous.intensity_score) - float(candidate.intensity_score)))
        if str(intake.tonight_pace) == "rollercoaster":
            intensity_gap = 1.0 - intensity_gap
        if previous.content_key == candidate.content_key and str(intake.variety_preference) in {"mix_it_up", "anything"}:
            intensity_gap *= 0.82
        if previous.content_key == candidate.content_key and str(intake.session_mode) == "continue_momentum":
            intensity_gap = min(1.0, intensity_gap + 0.18)
        if previous.content_key != candidate.content_key and str(intake.variety_preference) in {"one_story", "mostly_one_story"}:
            intensity_gap *= 0.82
        return max(0.0, min(1.0, (shared * 0.56) + (intensity_gap * 0.44)))
