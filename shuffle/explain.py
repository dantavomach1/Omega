from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence, Tuple

from omega.shuffle.intake import (
    ENDING_OPTIONS,
    ENERGY_OPTIONS,
    ENTRY_MODES,
    FAMILIARITY_OPTIONS,
    FOCUS_OPTIONS,
    NIGHT_KIND_OPTIONS,
    TIME_OPTIONS,
    VARIETY_OPTIONS,
    intake_label,
)
from omega.shuffle.models import SmartShuffleIntake, SmartShufflePlan, SmartShuffleSegment
from omega.shuffle.session_director import SessionDirectorResult


# ============================================================
# Tuning zone
# ============================================================


@dataclass(frozen=True)
class ExplainTuning:
    max_explanations: int = 4
    high_confidence_threshold: float = 0.74
    medium_confidence_threshold: float = 0.56
    late_night_hour: int = 22
    early_morning_hour: int = 5


class SmartShuffleExplainer:
    def __init__(self, tuning: ExplainTuning = ExplainTuning()) -> None:
        self._tuning = tuning

    def build_plan(self, *, intake: SmartShuffleIntake, directed: SessionDirectorResult) -> SmartShufflePlan:
        segments = tuple(directed.segments)
        runtime = sum(int(seg.runtime_minutes) for seg in segments)
        confidence_score = float(max(0.0, min(1.0, directed.confidence_base)))
        confidence_label = self._confidence_label(confidence_score)
        mode_label = self._mode_label(intake)
        tone_banner = self._tone_banner(intake, directed)
        summary = self._summary_sentence(intake, directed)
        explanations = self._explanations(intake, directed)
        session_name = self._session_name(intake, directed)
        return SmartShufflePlan(
            session_id=self._session_id(intake, session_name),
            mode_label=str(mode_label),
            session_name=str(session_name),
            summary=str(summary),
            tone_banner=str(tone_banner),
            estimated_runtime_minutes=int(runtime),
            protected_arc_active=bool(directed.protected_arc_active),
            variety_strategy=str(directed.variety_strategy),
            confidence_label=str(confidence_label),
            confidence_score=float(confidence_score),
            explanation_lines=tuple(explanations[: int(self._tuning.max_explanations)]),
            segments=segments,
            debug_notes=tuple(directed.debug_notes),
        )

    def _mode_label(self, intake: SmartShuffleIntake) -> str:
        value = str(intake.session_mode or "smart_shuffle")
        for mode_key, label, _desc in ENTRY_MODES:
            if mode_key == value:
                return str(label)
        if str(intake.variety_preference) in {"one_story", "mostly_one_story"}:
            return "One Story Mode"
        return "Smart Shuffle"

    def _tone_banner(self, intake: SmartShuffleIntake, directed: SessionDirectorResult) -> str:
        night = intake_label(intake.night_kind, NIGHT_KIND_OPTIONS)
        energy = intake_label(intake.current_energy, ENERGY_OPTIONS)
        focus = intake_label(intake.focus_availability, FOCUS_OPTIONS)
        if directed.protected_arc_active:
            return f"{night} night, {energy.lower()} energy, protected continuity"
        return f"{night} night, {energy.lower()} energy, {focus.lower()}"

    def _summary_sentence(self, intake: SmartShuffleIntake, directed: SessionDirectorResult) -> str:
        familiar = intake_label(intake.familiarity_preference, FAMILIARITY_OPTIONS).lower()
        variety = intake_label(intake.variety_preference, VARIETY_OPTIONS).lower()
        ending = intake_label(intake.end_preference, ENDING_OPTIONS).lower()
        if directed.protected_arc_active:
            return f"Tonight leans {familiar}, immersive, and deliberately paced, with a protected story run and a {ending} finish."
        return f"Tonight leans {familiar}, {variety}, and emotionally aligned to your current state, with a {ending} finish."

    def _explanations(self, intake: SmartShuffleIntake, directed: SessionDirectorResult) -> Tuple[str, ...]:
        lines = []
        lines.append(
            f"You asked for {intake_label(intake.night_kind, NIGHT_KIND_OPTIONS).lower()} with {intake_label(intake.focus_availability, FOCUS_OPTIONS).lower()}, so the lineup avoids low-value friction."
        )
        if directed.protected_arc_active:
            lines.append("A strong arc showed up in the scoring, so I kept you inside the same story long enough for the momentum to pay off.")
        else:
            if directed.variety_strategy == "guided_mix":
                lines.append("You wanted more variation, so the session mixes titles without cutting away at a bad narrative moment.")
            else:
                lines.append("This plan stays practical about runtime and stop points instead of chasing random novelty.")
        if self._is_late_night() or intake.current_energy in {"drained", "low_okay"}:
            lines.append("Because this looks like a lower-energy window, darker and harder-to-reenter picks were pushed down.")
        if intake.end_preference in {"clean_stop", "end_soft"}:
            lines.append("The ending was shaped around a softer stop so you are not left in a punishing cliffhanger by accident.")
        elif intake.end_preference == "end_strong":
            lines.append("The last block is allowed to land with more punch because you asked for a stronger finish.")
        return tuple(lines)

    def _session_name(self, intake: SmartShuffleIntake, directed: SessionDirectorResult) -> str:
        if directed.protected_arc_active and str(intake.variety_preference) in {"one_story", "mostly_one_story"}:
            return "Locked In"
        names = {
            "comfort": "Velvet Landing",
            "fun": "Warm Circuit",
            "adventure": "Quiet Fire",
            "deep_story": "Deep Waters",
            "intense": "Night Voltage",
            "emotional": "Soft Gravity",
            "easy_background": "Gentle Drift",
            "surprise_me": "Strange Comfort",
        }
        if str(intake.session_mode) == "continue_momentum":
            return "One More Episode"
        if str(intake.session_mode) == "movie_night":
            return "Main Event"
        return str(names.get(str(intake.night_kind), "Old Friends, New Night"))

    def _confidence_label(self, score: float) -> str:
        if score >= float(self._tuning.high_confidence_threshold):
            return "High confidence"
        if score >= float(self._tuning.medium_confidence_threshold):
            return "Steady confidence"
        return "Experimental mix"

    def _session_id(self, intake: SmartShuffleIntake, name: str) -> str:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        slug = "-".join(part for part in str(name).lower().replace("'", "").split() if part)[:28]
        return f"smart-{stamp}-{slug or intake.session_mode}"

    def _is_late_night(self) -> bool:
        hour = int(datetime.now().hour)
        return hour >= int(self._tuning.late_night_hour) or hour <= int(self._tuning.early_morning_hour)
