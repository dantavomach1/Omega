from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ============================================================
# Tuning zone
# ============================================================


@dataclass(frozen=True)
class SmartShuffleTuning:
    max_preview_paths_per_show: int = 6
    default_movie_runtime_min: int = 110
    default_tv_runtime_min: int = 46
    default_short_tv_runtime_min: int = 24
    default_session_target_min: int = 95
    warmup_share: float = 0.18
    landing_share: float = 0.16
    continuity_lock_threshold: float = 0.70
    hidden_gem_gap_days: int = 35
    max_explanations: int = 4


# ============================================================
# Inputs + raw library sources
# ============================================================


@dataclass(frozen=True)
class SmartShuffleIntake:
    session_mode: str = "smart_shuffle"
    current_energy: str = "neutral"
    night_kind: str = "surprise_me"
    focus_availability: str = "some_focus"
    available_time: str = "60_120"
    familiarity_preference: str = "mix"
    variety_preference: str = "balanced"
    emotional_intensity: str = "medium"
    tonight_pace: str = "smooth"
    end_preference: str = "clean_stop"
    protect_story_arcs: bool = True
    prefer_tv_over_movies: bool = False
    prefer_movies_over_tv: bool = False
    rewatch_safe_only: bool = False
    avoid_dark_content: bool = False
    avoid_subtitles_tonight: bool = False
    background_friendly_only: bool = False
    family_safe: bool = False
    mature_only: bool = False
    bring_back_forgotten_favorites: bool = False
    show_hidden_gems: bool = False
    trust_me: bool = False


@dataclass(frozen=True)
class SmartTitleSource:
    content_key: str
    title: str
    media_type: str
    genres: Tuple[str, ...] = ()
    overview: str = ""
    year: Optional[int] = None
    rating: Optional[float] = None
    play_path: str = ""
    show_dirs: Tuple[str, ...] = ()
    next_episode_paths: Tuple[str, ...] = ()
    poster_path: str = ""
    backdrop_path: str = ""
    selected_by_user: bool = False


# ============================================================
# Enriched metadata
# ============================================================


@dataclass(frozen=True)
class SmartEpisode:
    content_key: str
    show_title: str
    episode_path: str
    season_number: Optional[int]
    episode_number: Optional[int]
    runtime_minutes: int
    title: str
    arc_type: str
    arc_group_id: str
    arc_position: str
    arc_strength: float
    cliffhanger_strength: float
    interruptibility_score: float
    continuity_dependency: float
    must_continue_probability: float
    lore_density: float
    emotional_intensity: float
    tonal_darkness: float
    comfort_value: float
    comedy_value: float
    tension_value: float
    late_night_friendliness: float
    background_friendliness: float
    metadata_confidence: float


@dataclass(frozen=True)
class SmartTitleProfile:
    content_key: str
    title: str
    media_type: str
    genres: Tuple[str, ...]
    overview: str
    primary_moods: Dict[str, float]
    secondary_moods: Dict[str, float]
    energy_profile: float
    comfort_score: float
    focus_required: float
    emotional_weight: float
    darkness_level: float
    novelty_score: float
    late_night_friendliness: float
    background_friendliness: float
    user_familiarity_score: float
    user_affinity_score: float
    hidden_gem_score: float
    preferred_session_length_min: int
    movie_runtime_minutes: int
    play_path: str = ""
    poster_path: str = ""
    backdrop_path: str = ""
    next_episodes: Tuple[SmartEpisode, ...] = ()
    metadata_confidence: float = 0.55
    mood_confidence: float = 0.50
    arc_confidence: float = 0.40
    interruptibility_confidence: float = 0.42
    is_hidden_from_shuffle: bool = False
    best_as_cluster: bool = False
    safe_single_episode: bool = False
    selected_by_user: bool = False
    watched_completion_score: float = 0.0
    resume_progress_ratio: float = 0.0
    resume_path: str = ""
    resume_freshness_score: float = 0.0
    recency_score: float = 0.0
    fatigue_score: float = 0.0
    rewatch_comfort_score: float = 0.0
    saved_mix_score: float = 0.0
    cluster_bias: float = 0.0
    family_friendly_score: float = 0.5
    maturity_score: float = 0.5
    subtitle_load_score: float = 0.5


# ============================================================
# Scoring + session plan
# ============================================================


@dataclass(frozen=True)
class SmartCandidate:
    candidate_id: str
    content_key: str
    title: str
    media_type: str
    role_hint: str
    runtime_minutes: int
    media_paths: Tuple[str, ...]
    moods: Dict[str, float]
    continuity_pressure: float
    protected_run: bool
    stop_quality: float
    novelty_score: float
    familiarity_score: float
    intensity_score: float
    background_score: float
    late_night_score: float
    explanation_tags: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ScoreBreakdown:
    mood_fit: float
    cognitive_fit: float
    session_utility: float
    narrative_continuity: float
    personal_taste: float
    practical_fit: float
    sequence_harmony: float
    total: float


@dataclass(frozen=True)
class ScoredCandidate:
    candidate: SmartCandidate
    breakdown: ScoreBreakdown
    rejection_notes: Tuple[str, ...] = ()


@dataclass(frozen=True)
class SmartShuffleSegment:
    role: str
    title: str
    media_type: str
    content_key: str
    runtime_minutes: int
    media_paths: Tuple[str, ...]
    protected_run: bool
    explanation: str
    confidence: float
    badges: Tuple[str, ...] = ()


@dataclass(frozen=True)
class SmartShufflePlan:
    session_id: str
    mode_label: str
    session_name: str
    summary: str
    tone_banner: str
    estimated_runtime_minutes: int
    protected_arc_active: bool
    variety_strategy: str
    confidence_label: str
    confidence_score: float
    explanation_lines: Tuple[str, ...]
    segments: Tuple[SmartShuffleSegment, ...]
    debug_notes: Tuple[str, ...] = ()


@dataclass(frozen=True)
class SmartShuffleResult:
    intake: SmartShuffleIntake
    plan: SmartShufflePlan
    profiles: Tuple[SmartTitleProfile, ...]
    scored_candidates: Tuple[ScoredCandidate, ...] = ()


@dataclass
class SmartShuffleFeedback:
    session_id: str
    verdict: str
    notes: Tuple[str, ...] = ()
    timestamp: int = 0


@dataclass
class SmartShuffleSessionState:
    plan: SmartShufflePlan
    playlist_paths: List[str] = field(default_factory=list)
    playlist_content_keys: List[str] = field(default_factory=list)
    current_playlist_index: int = 0
    source: str = ""
    keep_continuity_bias: float = 0.0
    increase_variety_bias: float = 0.0

