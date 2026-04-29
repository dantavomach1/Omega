from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class HomeRuntimeConfig:
    """Tunable guard rails for responsive Home rebuild behavior."""

    resize_width_threshold_px: int = 10
    resize_height_threshold_px: int = 18
    resize_cooldown_ms: int = 120
    resize_quantum_px: int = 6


class HomeRuntimeCoordinator:
    """Tracks viewport changes and prevents redundant Home rebuild churn."""

    def __init__(self, config: Optional[HomeRuntimeConfig] = None) -> None:
        self.config = config or HomeRuntimeConfig()

        self._last_resize_raw: Tuple[int, int] = (0, 0)
        self._last_resize_quant: Tuple[int, int] = (0, 0)
        self._last_resize_accepted_ms: int = 0

        self._last_profile_signature: Tuple[int, ...] = tuple()
        self._rebuild_inflight: bool = False
        self._rebuild_pending: bool = False

    def _quantize(self, value: int) -> int:
        q = max(1, int(self.config.resize_quantum_px))
        return int(round(float(max(1, value)) / float(q)) * q)

    def observe_viewport_resize(self, width_px: int, height_px: int, now_ms: int) -> tuple[bool, str]:
        """
        Returns whether a responsive rebuild should be scheduled for this resize.
        """

        w = max(1, int(width_px))
        h = max(1, int(height_px))
        self._last_resize_raw = (w, h)

        qw = self._quantize(w)
        qh = self._quantize(h)
        quant = (qw, qh)

        if self._last_resize_quant == (0, 0):
            self._last_resize_quant = quant
            self._last_resize_accepted_ms = int(now_ms)
            return True, "first-resize"

        prev_w, prev_h = self._last_resize_quant
        dw = abs(qw - prev_w)
        dh = abs(qh - prev_h)

        width_thr = max(1, int(self.config.resize_width_threshold_px))
        height_thr = max(1, int(self.config.resize_height_threshold_px))

        if dw < width_thr and dh < height_thr:
            return False, "below-threshold"

        cooldown_ms = max(0, int(self.config.resize_cooldown_ms))
        if cooldown_ms > 0 and (int(now_ms) - int(self._last_resize_accepted_ms)) < cooldown_ms:
            if dw < (width_thr * 2) and dh < (height_thr * 2):
                return False, "cooldown"

        self._last_resize_quant = quant
        self._last_resize_accepted_ms = int(now_ms)
        return True, "accepted"

    def profile_signature(self, profile: Dict[str, int]) -> Tuple[int, ...]:
        keys = (
            "vw",
            "vh",
            "lane_w",
            "visible",
            "card_w",
            "card_h",
            "spacing",
            "gutter",
            "hero_space",
        )
        return tuple(int(profile.get(k, 0) or 0) for k in keys)

    def needs_rebuild_for_profile(self, profile: Dict[str, int]) -> tuple[bool, tuple[int, ...]]:
        sig = self.profile_signature(profile)
        if not self._last_profile_signature:
            return True, sig
        return sig != self._last_profile_signature, sig

    def remember_profile(self, profile: Dict[str, int]) -> None:
        self._last_profile_signature = self.profile_signature(profile)

    def request_rebuild_slot(self) -> bool:
        if self._rebuild_inflight:
            self._rebuild_pending = True
            return False
        self._rebuild_inflight = True
        return True

    def finish_rebuild(self, profile: Optional[Dict[str, int]] = None) -> None:
        if profile is not None:
            self.remember_profile(profile)
        self._rebuild_inflight = False

    def consume_pending_rebuild(self) -> bool:
        if not self._rebuild_pending:
            return False
        self._rebuild_pending = False
        return True
