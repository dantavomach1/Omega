# omega/library/migrate.py
"""
Migration helper:
- Reads legacy Media/sources.txt (one path per line)
- Writes/updates a library.json file that contains those sources

This is intentionally conservative:
- It will NOT delete anything.
- It will merge new sources into an existing library.json.
- It will skip invalid / non-existent paths.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Any, Optional


def _read_sources_txt(sources_txt_path: Path) -> List[str]:
    """
    Read sources.txt lines into a cleaned list of absolute paths (strings).
    Lines starting with # are treated as comments.
    Empty lines are ignored.
    """
    if not sources_txt_path.exists():
        return []

    lines = sources_txt_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    out: List[str] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        # Allow quotes, just in case someone pasted paths with quotes
        if (line.startswith('"') and line.endswith('"')) or (line.startswith("'") and line.endswith("'")):
            line = line[1:-1].strip()

        out.append(line)
    return out


def _load_json(path: Path) -> Dict[str, Any]:
    """
    Load JSON safely. If missing or broken, return an empty dict.
    """
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return {}


def _save_json(path: Path, data: Dict[str, Any]) -> None:
    """
    Save JSON with stable formatting.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def migrate_sources_txt_to_library_json(
    sources_txt_path: Optional[Path] = None,
    library_json_path: Optional[Path] = None,
) -> str:
    """
    Migrate legacy sources.txt into library.json.

    Expected call style from controller:
        migrate_sources_txt_to_library_json(media_dir/"sources.txt", library_file)

    Returns a short status message (string) that you can log.
    """
    # --------
    # Defaults (safe fallbacks)
    # --------
    if sources_txt_path is None:
        sources_txt_path = Path("Media") / "sources.txt"
    if library_json_path is None:
        library_json_path = Path("Media") / "library.json"

    sources_txt_path = Path(sources_txt_path)
    library_json_path = Path(library_json_path)

    # If there's no legacy file, nothing to do.
    if not sources_txt_path.exists():
        return f"[MIGRATE] No legacy sources.txt found at: {sources_txt_path}"

    # Read legacy sources
    raw_sources = _read_sources_txt(sources_txt_path)

    # Normalize + validate
    valid_sources: List[str] = []
    for s in raw_sources:
        p = Path(s).expanduser()
        # Keep it absolute when possible (helps consistency)
        try:
            p = p.resolve()
        except Exception:
            # If resolve fails (weird path), keep as-is
            pass

        if p.exists():
            valid_sources.append(str(p))
        else:
            # If it doesn't exist, skip it (better than poisoning your library)
            # You can add logging later if you want to see skipped ones.
            pass

    if not valid_sources:
        return f"[MIGRATE] sources.txt found but no valid existing paths inside: {sources_txt_path}"

    # Load existing library.json (if any) and merge
    lib = _load_json(library_json_path)

    # We store sources under lib["sources"] as a list of strings.
    existing = lib.get("sources", [])
    if not isinstance(existing, list):
        existing = []

    # Merge unique (preserve order: existing first, then new)
    seen = set()
    merged: List[str] = []

    for item in existing:
        if isinstance(item, str) and item not in seen:
            seen.add(item)
            merged.append(item)

    added_count = 0
    for item in valid_sources:
        if item not in seen:
            seen.add(item)
            merged.append(item)
            added_count += 1

    lib["sources"] = merged

    # Optional metadata fields (safe defaults)
    lib.setdefault("version", 1)
    lib.setdefault("note", "Auto-generated / updated by migration from sources.txt")

    _save_json(library_json_path, lib)

    return f"[MIGRATE] Migrated sources.txt -> library.json | added={added_count} total={len(merged)} | {library_json_path}"
