from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

from omega.shuffle.debug import smart_debug


# ============================================================
# Tuning zone
# ============================================================


@dataclass(frozen=True)
class LearningTuning:
    max_history_events: int = 1200
    affinity_gain_finish: float = 0.08
    affinity_gain_start: float = 0.02
    affinity_penalty_skip: float = 0.12
    dark_penalty_gain: float = 0.12
    familiarity_bias_gain: float = 0.08
    feedback_affinity_gain: float = 0.06
    feedback_affinity_penalty: float = 0.05
    feedback_cluster_gain: int = 1


class SmartShuffleLearningStore:
    def __init__(self, cache_dir: Path, logger=None, tuning: LearningTuning = LearningTuning()) -> None:
        self._cache_dir = Path(cache_dir)
        self._logger = logger
        self._tuning = tuning
        self._history_path = self._cache_dir / "smart_shuffle_user_history.json"
        self._feedback_path = self._cache_dir / "smart_shuffle_feedback.json"
        self._prefs_path = self._cache_dir / "smart_shuffle_learned_preferences.json"
        self._profiles_path = self._cache_dir / "smart_shuffle_profiles.json"
        self._metadata_path = self._cache_dir / "smart_shuffle_metadata.json"

        self._history = self._load_json(self._history_path, {"events": []})
        self._feedback = self._load_json(self._feedback_path, {"feedback": []})
        self._prefs = self._load_json(
            self._prefs_path,
            {
                "affinity": {},
                "late_night_dark_skip_penalty": 0.0,
                "prefer_familiar_when_tired": 0.0,
                "show_cluster_bias": {},
            },
        )
        self._profiles = self._load_json(self._profiles_path, {"sessions": []})
        self._metadata = self._load_json(self._metadata_path, {"titles": {}, "episodes": {}})

    def _load_json(self, path: Path, fallback: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if not path.exists() or not path.is_file():
                return dict(fallback)
            raw = path.read_text(encoding="utf-8", errors="ignore")
            obj = json.loads(raw) if raw.strip() else {}
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
        return dict(fallback)

    def _save_json(self, path: Path, payload: Dict[str, Any]) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            smart_debug(self._logger, "LEARN", "save failed", str(path), exc)

    def metadata_overrides(self) -> Dict[str, Dict[str, Any]]:
        return {
            "titles": dict(self._metadata.get("titles", {}) if isinstance(self._metadata.get("titles"), dict) else {}),
            "episodes": dict(self._metadata.get("episodes", {}) if isinstance(self._metadata.get("episodes"), dict) else {}),
        }

    def learned_biases(self) -> Dict[str, Any]:
        out = dict(self._prefs)
        out.setdefault("affinity", {})
        out.setdefault("late_night_dark_skip_penalty", 0.0)
        out.setdefault("prefer_familiar_when_tired", 0.0)
        out.setdefault("show_cluster_bias", {})
        return out

    def remember_session_profile(self, payload: Dict[str, Any]) -> None:
        sessions = self._profiles.setdefault("sessions", [])
        if not isinstance(sessions, list):
            sessions = []
            self._profiles["sessions"] = sessions
        sessions.insert(0, dict(payload))
        self._profiles["sessions"] = sessions[:80]
        self._save_json(self._profiles_path, self._profiles)

    def record_event(
        self,
        *,
        session_id: str,
        event_type: str,
        content_key: str,
        title: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        events = self._history.setdefault("events", [])
        if not isinstance(events, list):
            events = []
            self._history["events"] = events
        event = {
            "session_id": str(session_id or ""),
            "event_type": str(event_type or ""),
            "content_key": str(content_key or ""),
            "title": str(title or ""),
            "timestamp": int(time.time()),
            "metadata": dict(metadata or {}),
        }
        events.insert(0, event)
        self._history["events"] = events[: int(self._tuning.max_history_events)]
        self._save_json(self._history_path, self._history)
        self._apply_event_learning(event)

    def record_feedback(self, session_id: str, verdict: str, notes: Iterable[str]) -> None:
        rows = self._feedback.setdefault("feedback", [])
        if not isinstance(rows, list):
            rows = []
            self._feedback["feedback"] = rows
        clean_notes = [str(x) for x in notes if str(x).strip()]
        rows.insert(
            0,
            {
                "session_id": str(session_id or ""),
                "verdict": str(verdict or ""),
                "notes": list(clean_notes),
                "timestamp": int(time.time()),
            },
        )
        self._feedback["feedback"] = rows[:240]
        self._save_json(self._feedback_path, self._feedback)
        self._apply_feedback_learning(str(session_id or ""), str(verdict or ""), tuple(clean_notes))

    def _apply_event_learning(self, event: Dict[str, Any]) -> None:
        content_key = str(event.get("content_key") or "").strip()
        event_type = str(event.get("event_type") or "").strip()
        meta = event.get("metadata", {}) if isinstance(event.get("metadata"), dict) else {}
        if not content_key or not event_type:
            return

        affinity = self._prefs.setdefault("affinity", {})
        if not isinstance(affinity, dict):
            affinity = {}
            self._prefs["affinity"] = affinity
        current = float(affinity.get(content_key, 0.0) or 0.0)

        if event_type == "finish":
            current += float(self._tuning.affinity_gain_finish)
        elif event_type == "start":
            current += float(self._tuning.affinity_gain_start)
        elif event_type in {"skip", "abandon"}:
            current -= float(self._tuning.affinity_penalty_skip)

        affinity[content_key] = max(-0.6, min(1.0, current))

        if bool(meta.get("late_night")) and bool(meta.get("dark")) and event_type in {"skip", "abandon"}:
            self._prefs["late_night_dark_skip_penalty"] = max(
                0.0,
                min(1.0, float(self._prefs.get("late_night_dark_skip_penalty", 0.0) or 0.0) + float(self._tuning.dark_penalty_gain)),
            )

        if bool(meta.get("tired")) and bool(meta.get("familiar")) and event_type == "finish":
            self._prefs["prefer_familiar_when_tired"] = max(
                0.0,
                min(1.0, float(self._prefs.get("prefer_familiar_when_tired", 0.0) or 0.0) + float(self._tuning.familiarity_bias_gain)),
            )

        if meta.get("cluster_size"):
            show_cluster = self._prefs.setdefault("show_cluster_bias", {})
            if not isinstance(show_cluster, dict):
                show_cluster = {}
                self._prefs["show_cluster_bias"] = show_cluster
            if event_type == "finish":
                show_cluster[content_key] = int(max(int(show_cluster.get(content_key, 1) or 1), int(meta.get("cluster_size") or 1)))

        self._save_json(self._prefs_path, self._prefs)
        smart_debug(self._logger, "LEARN", "updated", content_key, event_type, self._prefs.get("affinity", {}).get(content_key, 0.0))

    def infer_recently_loved_keys(self) -> Tuple[str, ...]:
        affinity = self._prefs.get("affinity", {}) if isinstance(self._prefs.get("affinity"), dict) else {}
        ranked = sorted(((str(k), float(v or 0.0)) for k, v in affinity.items()), key=lambda pair: pair[1], reverse=True)
        return tuple(k for k, score in ranked if score >= 0.24)[:24]

    def _apply_feedback_learning(self, session_id: str, verdict: str, notes: Tuple[str, ...]) -> None:
        if not session_id:
            return
        sessions = self._profiles.get("sessions", []) if isinstance(self._profiles.get("sessions"), list) else []
        session = next((row for row in sessions if isinstance(row, dict) and str(row.get("session_id") or "") == session_id), None)
        if session is None:
            return

        affinity = self._prefs.setdefault("affinity", {})
        if not isinstance(affinity, dict):
            affinity = {}
            self._prefs["affinity"] = affinity

        show_cluster = self._prefs.setdefault("show_cluster_bias", {})
        if not isinstance(show_cluster, dict):
            show_cluster = {}
            self._prefs["show_cluster_bias"] = show_cluster

        verdict_key = str(verdict or "").strip().casefold()
        note_blob = " ".join(str(x or "").strip().casefold() for x in notes)
        gain = float(self._tuning.feedback_affinity_gain)
        if verdict_key in {"too_heavy", "wrong_tone"}:
            gain = -float(self._tuning.feedback_affinity_penalty)
        elif verdict_key in {"great", "perfect"}:
            gain = float(self._tuning.feedback_affinity_gain)
        elif verdict_key in {"mixed"}:
            gain = 0.01

        segments = session.get("segments", []) if isinstance(session.get("segments"), list) else []
        for seg in segments:
            if not isinstance(seg, dict):
                continue
            content_key = str(seg.get("content_key") or "").strip()
            if not content_key:
                continue
            current = float(affinity.get(content_key, 0.0) or 0.0)
            affinity[content_key] = max(-0.6, min(1.0, current + gain))

            if verdict_key in {"great", "perfect"} and bool(seg.get("protected_run", False)):
                current_cluster = int(show_cluster.get(content_key, 1) or 1)
                runtime_minutes = int(seg.get("runtime_minutes", 0) or 0)
                desired_cluster = 3 if runtime_minutes > 60 else 2
                show_cluster[content_key] = max(current_cluster, desired_cluster)

        if verdict_key in {"too_heavy", "wrong_tone"} and ("dark" in note_blob or "heavy" in note_blob):
            self._prefs["late_night_dark_skip_penalty"] = max(
                0.0,
                min(1.0, float(self._prefs.get("late_night_dark_skip_penalty", 0.0) or 0.0) + float(self._tuning.dark_penalty_gain) * 0.6),
            )
        if verdict_key in {"great", "perfect"} and ("comfort" in note_blob or "easy" in note_blob or "familiar" in note_blob):
            self._prefs["prefer_familiar_when_tired"] = max(
                0.0,
                min(1.0, float(self._prefs.get("prefer_familiar_when_tired", 0.0) or 0.0) + float(self._tuning.familiarity_bias_gain) * 0.6),
            )

        self._save_json(self._prefs_path, self._prefs)
        smart_debug(self._logger, "LEARN", "feedback updated", session_id, verdict_key)
