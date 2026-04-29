from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Sequence

from omega.shuffle.debug import smart_debug
from omega.shuffle.explain import SmartShuffleExplainer
from omega.shuffle.intake import default_intake
from omega.shuffle.learning import SmartShuffleLearningStore
from omega.shuffle.metadata import SmartShuffleMetadataBuilder
from omega.shuffle.models import SmartShuffleIntake, SmartShuffleResult, SmartTitleSource
from omega.shuffle.scoring import SmartShuffleScorer
from omega.shuffle.session_director import SmartShuffleSessionDirector


# ============================================================
# Tuning zone
# ============================================================


@dataclass(frozen=True)
class EngineTuning:
    minimum_sources_required: int = 1


class SmartShuffleEngine:
    def __init__(self, cache_dir: Path, logger=None, tuning: EngineTuning = EngineTuning()) -> None:
        self._cache_dir = Path(cache_dir)
        self._logger = logger
        self._tuning = tuning
        self._learning = SmartShuffleLearningStore(cache_dir=self._cache_dir, logger=logger)
        self._metadata = SmartShuffleMetadataBuilder(logger=logger)
        self._scorer = SmartShuffleScorer(logger=logger)
        self._director = SmartShuffleSessionDirector(scorer=self._scorer, logger=logger)
        self._explainer = SmartShuffleExplainer()

    @property
    def learning(self) -> SmartShuffleLearningStore:
        return self._learning

    def default_intake(self, mode: str = "smart_shuffle") -> SmartShuffleIntake:
        return default_intake(mode)

    def generate(
        self,
        *,
        sources: Sequence[SmartTitleSource],
        intake: SmartShuffleIntake,
        state: Dict[str, object],
        remember_session: bool = True,
    ) -> SmartShuffleResult:
        clean_sources = tuple(source for source in (sources or ()) if str(getattr(source, "content_key", "") or "").strip())
        if len(clean_sources) < int(self._tuning.minimum_sources_required):
            raise ValueError("Smart Shuffle requires at least one verified library item.")

        learned_biases = self._learning.learned_biases()
        metadata_overrides = self._learning.metadata_overrides()
        profiles = self._metadata.build_profiles(clean_sources, state=state, learned_biases=learned_biases, metadata_overrides=metadata_overrides)
        directed = self._director.build_session(profiles=profiles, intake=intake, state=state)
        plan = self._explainer.build_plan(intake=intake, directed=directed)

        smart_debug(self._logger, "SESSION", "mode", intake.session_mode, "segments", len(plan.segments), "runtime", plan.estimated_runtime_minutes, "confidence", f"{plan.confidence_score:.2f}")

        result = SmartShuffleResult(
            intake=intake,
            plan=plan,
            profiles=profiles,
            scored_candidates=tuple(directed.scored_candidates),
        )

        if bool(remember_session):
            self._learning.remember_session_profile(
                {
                    "session_id": plan.session_id,
                    "mode": plan.mode_label,
                    "summary": plan.summary,
                    "estimated_runtime_minutes": plan.estimated_runtime_minutes,
                    "protected_arc_active": plan.protected_arc_active,
                    "confidence_score": plan.confidence_score,
                    "segments": [
                        {
                            "role": seg.role,
                            "title": seg.title,
                            "content_key": seg.content_key,
                            "runtime_minutes": seg.runtime_minutes,
                            "protected_run": seg.protected_run,
                        }
                        for seg in plan.segments
                    ],
                }
            )
        return result
