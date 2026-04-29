from __future__ import annotations

import copy
import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


PROFILE_LIMIT = 5
PROFILE_STORE_VERSION = 1
DEFAULT_PROFILE_NAME = "Primary"
DEFAULT_ACCENTS = (
    "#5CA0FF",
    "#FF7B72",
    "#8BD450",
    "#F6C453",
    "#C68CFF",
)


class ProfileStore:
    def __init__(
        self,
        path: Path,
        *,
        default_state_factory: Callable[[], Dict[str, Any]],
        legacy_state_path: Optional[Path] = None,
        profile_limit: int = PROFILE_LIMIT,
    ) -> None:
        self.path = Path(path)
        self.legacy_state_path = Path(legacy_state_path) if legacy_state_path is not None else None
        self.default_state_factory = default_state_factory
        self.profile_limit = max(1, int(profile_limit))
        self._data: Dict[str, Any] = {
            "version": int(PROFILE_STORE_VERSION),
            "active_profile_id": "",
            "profiles": [],
        }

    def load(self) -> Dict[str, Any]:
        raw_obj: Dict[str, Any] = {}
        try:
            if self.path.exists() and self.path.is_file():
                raw = self.path.read_text(encoding="utf-8", errors="ignore")
                parsed = json.loads(raw) if raw.strip() else {}
                if isinstance(parsed, dict):
                    raw_obj = parsed
        except Exception:
            raw_obj = {}

        profiles_raw = raw_obj.get("profiles", [])
        active_profile_id = str(raw_obj.get("active_profile_id") or "").strip()

        profiles: List[Dict[str, Any]] = []
        if isinstance(profiles_raw, list):
            for index, raw_profile in enumerate(profiles_raw[: self.profile_limit]):
                normalized = self._normalize_profile(raw_profile, index=index)
                if normalized is not None:
                    profiles.append(normalized)

        if not profiles:
            legacy_state = self._load_legacy_state()
            profiles.append(
                self._new_profile(
                    name=DEFAULT_PROFILE_NAME,
                    index=0,
                    migrated_state=legacy_state,
                )
            )

        if not any(str(item.get("id") or "").strip() == active_profile_id for item in profiles):
            active_profile_id = str(profiles[0].get("id") or "")

        self._data = {
            "version": int(PROFILE_STORE_VERSION),
            "active_profile_id": str(active_profile_id or profiles[0].get("id") or ""),
            "profiles": profiles[: self.profile_limit],
        }
        return copy.deepcopy(self._data)

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self._data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

    def data(self) -> Dict[str, Any]:
        return self._data

    def profiles(self) -> List[Dict[str, Any]]:
        raw = self._data.get("profiles", [])
        return list(raw) if isinstance(raw, list) else []

    def active_profile_id(self) -> str:
        return str(self._data.get("active_profile_id") or "").strip()

    def active_profile(self) -> Dict[str, Any]:
        active_id = self.active_profile_id()
        for profile in self.profiles():
            if str(profile.get("id") or "").strip() == active_id:
                return profile
        profiles = self.profiles()
        if not profiles:
            profile = self._new_profile(name=DEFAULT_PROFILE_NAME, index=0)
            self._data["profiles"] = [profile]
            self._data["active_profile_id"] = str(profile.get("id") or "")
            return profile
        profile = profiles[0]
        self._data["active_profile_id"] = str(profile.get("id") or "")
        return profile

    def active_state(self) -> Dict[str, Any]:
        profile = self.active_profile()
        state = profile.get("state")
        if not isinstance(state, dict):
            state = self._fresh_state()
            profile["state"] = state
        return state

    def can_add_profile(self) -> bool:
        return len(self.profiles()) < int(self.profile_limit)

    def create_profile(
        self,
        name: str,
        *,
        avatar_art_path: str = "",
        background_path: str = "",
    ) -> Optional[Dict[str, Any]]:
        if not self.can_add_profile():
            return None
        profile = self._new_profile(
            name=name,
            index=len(self.profiles()),
        )
        profile["avatar_art_path"] = str(avatar_art_path or "").strip()
        profile["background_path"] = str(background_path or "").strip()
        profiles = self.profiles()
        profiles.append(profile)
        self._data["profiles"] = profiles[: self.profile_limit]
        return profile

    def set_active_profile(self, profile_id: str) -> Optional[Dict[str, Any]]:
        wanted = str(profile_id or "").strip()
        if not wanted:
            return None
        now = int(time.time())
        for profile in self.profiles():
            if str(profile.get("id") or "").strip() != wanted:
                continue
            profile["last_used_at"] = now
            profile["updated_at"] = now
            self._data["active_profile_id"] = wanted
            return profile
        return None

    def replace_active_state(self, state: Dict[str, Any]) -> Dict[str, Any]:
        profile = self.active_profile()
        profile["state"] = self._normalize_state(state)
        profile["updated_at"] = int(time.time())
        return profile["state"]

    def update_profile_metadata(self, profile_id: str, **patch: Any) -> Optional[Dict[str, Any]]:
        wanted = str(profile_id or "").strip()
        if not wanted:
            return None
        allowed = {
            "name",
            "avatar_art_path",
            "background_path",
            "accent_color",
        }
        for profile in self.profiles():
            if str(profile.get("id") or "").strip() != wanted:
                continue
            for key, value in patch.items():
                if str(key) not in allowed:
                    continue
                profile[str(key)] = str(value or "").strip() if isinstance(value, str) else value
            profile["updated_at"] = int(time.time())
            return profile
        return None

    def delete_profile(self, profile_id: str) -> bool:
        wanted = str(profile_id or "").strip()
        profiles = self.profiles()
        if not wanted or len(profiles) <= 1:
            return False

        kept = [profile for profile in profiles if str(profile.get("id") or "").strip() != wanted]
        if len(kept) == len(profiles):
            return False

        self._data["profiles"] = kept[: self.profile_limit]
        active_id = str(self._data.get("active_profile_id") or "").strip()
        if active_id == wanted:
            self._data["active_profile_id"] = str((kept[0].get("id") if kept else "") or "")
        return True

    def _load_legacy_state(self) -> Optional[Dict[str, Any]]:
        path = self.legacy_state_path
        if path is None:
            return None
        try:
            if not path.exists() or not path.is_file():
                return None
            raw = path.read_text(encoding="utf-8", errors="ignore")
            obj = json.loads(raw) if raw.strip() else {}
            if isinstance(obj, dict):
                return self._normalize_state(obj)
        except Exception:
            return None
        return None

    def _fresh_state(self) -> Dict[str, Any]:
        try:
            base = self.default_state_factory()
        except Exception:
            base = {}
        return self._normalize_state(base)

    def _normalize_state(self, raw_state: Any) -> Dict[str, Any]:
        base = self._fresh_state_base()
        if isinstance(raw_state, dict):
            for key, value in raw_state.items():
                base[str(key)] = copy.deepcopy(value)
        return base

    def _fresh_state_base(self) -> Dict[str, Any]:
        try:
            base = self.default_state_factory()
        except Exception:
            base = {}
        if not isinstance(base, dict):
            base = {}
        return copy.deepcopy(base)

    def _normalize_profile(self, raw_profile: Any, *, index: int) -> Optional[Dict[str, Any]]:
        if not isinstance(raw_profile, dict):
            return None
        now = int(time.time())
        profile_id = str(raw_profile.get("id") or "").strip() or self._make_profile_id(index=index)
        name = str(raw_profile.get("name") or "").strip() or f"Profile {index + 1}"
        accent = str(raw_profile.get("accent_color") or "").strip() or self._accent_for_index(index)
        created_at = self._safe_int(raw_profile.get("created_at"), fallback=now)
        updated_at = self._safe_int(raw_profile.get("updated_at"), fallback=created_at)
        last_used_at = self._safe_int(raw_profile.get("last_used_at"), fallback=updated_at)
        return {
            "id": profile_id,
            "name": name,
            "avatar_art_path": str(raw_profile.get("avatar_art_path") or "").strip(),
            "background_path": str(raw_profile.get("background_path") or "").strip(),
            "accent_color": accent,
            "created_at": created_at,
            "updated_at": updated_at,
            "last_used_at": last_used_at,
            "state": self._normalize_state(raw_profile.get("state")),
        }

    def _new_profile(
        self,
        *,
        name: str,
        index: int,
        migrated_state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        now = int(time.time())
        clean_name = str(name or "").strip() or f"Profile {index + 1}"
        return {
            "id": self._make_profile_id(index=index),
            "name": clean_name,
            "avatar_art_path": "",
            "background_path": "",
            "accent_color": self._accent_for_index(index),
            "created_at": now,
            "updated_at": now,
            "last_used_at": now,
            "state": self._normalize_state(migrated_state),
        }

    def _make_profile_id(self, *, index: int) -> str:
        seed = f"{time.time_ns()}::{index}::{len(self.profiles())}"
        suffix = hex(abs(hash(seed)))[2:10]
        return f"profile-{suffix}"

    def _accent_for_index(self, index: int) -> str:
        accents = list(DEFAULT_ACCENTS or ("#5CA0FF",))
        return str(accents[int(index) % len(accents)])

    @staticmethod
    def _safe_int(raw: Any, *, fallback: int) -> int:
        try:
            return int(raw)
        except Exception:
            return int(fallback)
