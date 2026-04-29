# omega/sources.py
import json
from pathlib import Path

from omega.paths import CONFIG_DIR, SOURCES_PATH, MEDIA_DIR


def _norm_path_str(p: str) -> str:
    try:
        return str(Path(p).resolve())
    except Exception:
        return str(p)


def load_sources() -> list[dict]:
    """
    Returns list of sources:
      [{"path": "...", "enabled": bool, "name": "..."}]
    Accepts both:
      {"sources":[...]}  and  [...]
    """
    try:
        if not SOURCES_PATH.exists():
            return []

        raw = SOURCES_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)

        if isinstance(data, dict) and "sources" in data:
            data = data["sources"]

        if not isinstance(data, list):
            return []

        out: list[dict] = []
        for s in data:
            if not isinstance(s, dict):
                continue
            path = s.get("path")
            if not path:
                continue
            out.append(
                {
                    "path": _norm_path_str(str(path)),
                    "enabled": bool(s.get("enabled", True)),
                    "name": str(s.get("name", "")),
                }
            )
        return out
    except Exception as e:
        print(f"[WARN] Failed to load sources.json: {e}")
        return []


def save_sources(sources: list[dict]) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        payload = {"sources": sources}
        SOURCES_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"[DEBUG] Saved sources: {SOURCES_PATH}")
    except Exception as e:
        print(f"[WARN] Failed to save sources.json: {e}")


def effective_source_folders() -> list[Path]:
    """
    Always includes MEDIA_DIR (project Media folder),
    plus any enabled folders in sources.json, de-duplicated.
    """
    folders: list[Path] = [MEDIA_DIR]
    sources = load_sources()

    for s in sources:
        if not s.get("enabled", True):
            continue
        try:
            folders.append(Path(s["path"]))
        except Exception:
            continue

    seen: set[str] = set()
    out: list[Path] = []

    for f in folders:
        try:
            key = str(f.resolve()).lower()
        except Exception:
            key = str(f).lower()

        if key in seen:
            continue
        seen.add(key)
        out.append(f)

    return out
