from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Tuple

from omega.shuffle.models import SmartShuffleIntake


# ============================================================
# Tuning zone
# ============================================================


@dataclass(frozen=True)
class IntakeDefaults:
    late_night_hour: int = 22
    early_morning_hour: int = 5


INTAKE_DEFAULTS = IntakeDefaults()

ENERGY_OPTIONS: Tuple[Tuple[str, str], ...] = (
    ("drained", "Drained"),
    ("low_okay", "Low but okay"),
    ("neutral", "Neutral"),
    ("alert", "Alert"),
    ("locked_in", "Locked in"),
)

NIGHT_KIND_OPTIONS: Tuple[Tuple[str, str], ...] = (
    ("comfort", "Comfort"),
    ("fun", "Fun"),
    ("adventure", "Adventure"),
    ("deep_story", "Deep story"),
    ("intense", "Intense"),
    ("emotional", "Emotional"),
    ("easy_background", "Easy background"),
    ("surprise_me", "Surprise me"),
)

FOCUS_OPTIONS: Tuple[Tuple[str, str], ...] = (
    ("very_low", "Very low focus"),
    ("some_focus", "Some focus"),
    ("good_focus", "Good focus"),
    ("full_attention", "Full attention"),
)

TIME_OPTIONS: Tuple[Tuple[str, str], ...] = (
    ("under_30", "Under 30 min"),
    ("30_60", "30-60 min"),
    ("60_120", "60-120 min"),
    ("120_plus", "2+ hours"),
    ("until_stop", "Until I stop"),
)

FAMILIARITY_OPTIONS: Tuple[Tuple[str, str], ...] = (
    ("familiar_only", "Familiar only"),
    ("mostly_familiar", "Mostly familiar"),
    ("mix", "Mix familiar and fresh"),
    ("fresh", "Fresh is fine"),
    ("surprise", "Surprise me"),
)

VARIETY_OPTIONS: Tuple[Tuple[str, str], ...] = (
    ("one_story", "One story only"),
    ("mostly_one_story", "Mostly one story"),
    ("balanced", "Balanced"),
    ("mix_it_up", "Mix it up"),
    ("anything", "Anything"),
)

INTENSITY_OPTIONS: Tuple[Tuple[str, str], ...] = (
    ("very_light", "Very light"),
    ("light_medium", "Light-medium"),
    ("medium", "Medium"),
    ("heavy_okay", "Heavy is fine"),
    ("anything", "Anything"),
)

PACE_OPTIONS: Tuple[Tuple[str, str], ...] = (
    ("slow_cozy", "Slow and cozy"),
    ("smooth", "Smooth and steady"),
    ("build_up", "Build up gradually"),
    ("start_strong", "Start strong"),
    ("rollercoaster", "Rollercoaster"),
)

ENDING_OPTIONS: Tuple[Tuple[str, str], ...] = (
    ("clean_stop", "Clean stopping point"),
    ("cliffhanger_okay", "Cliffhanger okay"),
    ("end_soft", "End soft"),
    ("end_strong", "End strong"),
    ("dont_care", "Don't care"),
)

ENTRY_MODES: Tuple[Tuple[str, str, str], ...] = (
    ("smart_shuffle", "Smart Shuffle", "Interactive and mood-aware"),
    ("trust_me", "Trust Me Tonight", "Minimal questions, heavier automation"),
    ("continue_momentum", "Continue My Momentum", "Pick up where the story energy already lives"),
    ("movie_night", "Build a Movie Night", "Movie-first curation with thoughtful pacing"),
    ("surprise", "Surprise Me", "Curated chaos, but not dumb randomness"),
)


def default_intake(mode: str = "smart_shuffle") -> SmartShuffleIntake:
    intake = SmartShuffleIntake(session_mode=str(mode or "smart_shuffle"))
    now = datetime.now()
    hour = int(now.hour)
    late_night = hour >= int(INTAKE_DEFAULTS.late_night_hour) or hour <= int(INTAKE_DEFAULTS.early_morning_hour)

    if str(mode) == "trust_me":
        intake = SmartShuffleIntake(
            session_mode="trust_me",
            current_energy="low_okay" if late_night else "neutral",
            night_kind="comfort" if late_night else "surprise_me",
            focus_availability="some_focus",
            available_time="60_120",
            familiarity_preference="mostly_familiar",
            variety_preference="balanced",
            emotional_intensity="light_medium" if late_night else "medium",
            tonight_pace="smooth",
            end_preference="end_soft" if late_night else "clean_stop",
            protect_story_arcs=True,
            trust_me=True,
            avoid_dark_content=late_night,
        )
    elif str(mode) == "continue_momentum":
        intake = SmartShuffleIntake(
            session_mode="continue_momentum",
            current_energy="alert" if not late_night else "low_okay",
            night_kind="deep_story",
            focus_availability="good_focus",
            available_time="120_plus",
            familiarity_preference="mostly_familiar",
            variety_preference="mostly_one_story",
            emotional_intensity="medium",
            tonight_pace="build_up",
            end_preference="clean_stop",
            protect_story_arcs=True,
            trust_me=True,
        )
    elif str(mode) == "movie_night":
        intake = SmartShuffleIntake(
            session_mode="movie_night",
            current_energy="neutral",
            night_kind="adventure",
            focus_availability="good_focus",
            available_time="120_plus",
            familiarity_preference="mix",
            variety_preference="balanced",
            emotional_intensity="medium",
            tonight_pace="build_up",
            end_preference="end_strong",
            prefer_movies_over_tv=True,
            protect_story_arcs=False,
        )
    elif str(mode) == "surprise":
        intake = SmartShuffleIntake(
            session_mode="surprise",
            current_energy="neutral",
            night_kind="surprise_me",
            focus_availability="some_focus",
            available_time="60_120",
            familiarity_preference="mix",
            variety_preference="mix_it_up",
            emotional_intensity="anything",
            tonight_pace="rollercoaster",
            end_preference="dont_care",
            show_hidden_gems=True,
            bring_back_forgotten_favorites=True,
            trust_me=True,
        )

    return intake


def intake_time_budget_minutes(value: str) -> int:
    mapping = {
        "under_30": 26,
        "30_60": 48,
        "60_120": 96,
        "120_plus": 150,
        "until_stop": 170,
    }
    return int(mapping.get(str(value or "60_120"), 96))


def option_map(entries: Tuple[Tuple[str, str], ...]) -> Dict[str, str]:
    return {str(k): str(v) for k, v in entries}


def intake_label(value: str, entries: Tuple[Tuple[str, str], ...]) -> str:
    return option_map(entries).get(str(value or ""), str(value or ""))


def advanced_toggle_rows() -> List[Tuple[str, str]]:
    return [
        ("protect_story_arcs", "Protect story arcs"),
        ("prefer_tv_over_movies", "Prefer TV over movies"),
        ("prefer_movies_over_tv", "Prefer movies over TV"),
        ("rewatch_safe_only", "Rewatch-safe only"),
        ("avoid_dark_content", "Avoid dark content"),
        ("avoid_subtitles_tonight", "Avoid subtitles tonight"),
        ("family_safe", "Family-safe"),
        ("background_friendly_only", "Background-friendly only"),
        ("bring_back_forgotten_favorites", "Bring back forgotten favorites"),
        ("show_hidden_gems", "Show hidden gems from my library"),
    ]
