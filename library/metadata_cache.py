# omega/library/metadata_cache.py
from __future__ import annotations

import json
import os
import time
import hashlib
from pathlib import Path
from typing import Dict, Any, Optional


class MetadataCache:
    """
    Local-only cache.

    Purpose:
    - store cleaned titles
    - later store IDs (TMDB/TVDB) without rewriting UI

    Safety:
    - never crashes app if cache is corrupt
    """

    def __init__(self, cache_file: Path):
        self.cache_file = Path(cache_file)
        self.data: Dict[str, Any] = {"version": 1, "shows": {}}
        self._load()

    def _load(self) -> None:
        if not self.cache_file.exists():
            return
        try:
            raw = self.cache_file.read_text(encoding="utf-8", errors="ignore")
            obj = json.loads(raw) if raw.strip() else {}
            if isinstance(obj, dict):
                self.data = obj
        except Exception:
            self.data = {"version": 1, "shows": {}}

    def save(self) -> None:
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(str(tmp), str(self.cache_file))
        except Exception:
            pass

    @staticmethod
    def show_key(show_dir: Path) -> str:
        try:
            s = str(show_dir.resolve())
        except Exception:
            s = str(show_dir.absolute())
        return hashlib.sha1(s.encode("utf-8", errors="ignore")).hexdigest()

    def get_show_title(self, show_dir: Path) -> Optional[str]:
        k = self.show_key(show_dir)
        return self.data.get("shows", {}).get(k, {}).get("title")

    def set_show_title(self, show_dir: Path, title: str) -> None:
        k = self.show_key(show_dir)
        self.data.setdefault("shows", {}).setdefault(k, {})
        self.data["shows"][k]["title"] = str(title)
        self.data["shows"][k]["updated_at"] = int(time.time())
        self.save()


class MetadataProvider:
    """
    Future: TMDB/TVDB provider.

    Today: pass-through provider to keep interface stable.
    """

    def get_show_display_title(self, show_dir: Path, fallback: str) -> str:
        return fallback

    def get_episode_display_title(
        self,
        show_dir: Path,
        episode_path: Path,
        fallback: str,
        season_num: Optional[int],
        episode_num: Optional[int],
    ) -> str:
        return fallback
