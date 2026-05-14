from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from omega.app.contracts import ShowGroup
from omega.app.text_naming import NameCleaner
from omega.library.search_index import LibrarySearchIndex


def _now_ts() -> int:
    return int(time.time())


def _debug_log(*args: object) -> None:
    flag = str(os.environ.get("OMEGA_DEBUG", "")).strip().casefold()
    if flag not in {"1", "true", "yes", "on"}:
        return
    try:
        print(*args)
    except Exception:
        pass


def _safe_str(raw: object) -> str:
    return str(raw or "").strip()


def _safe_int(raw: object, default: int = 0) -> int:
    try:
        return int(raw)
    except Exception:
        return int(default)


def _safe_float(raw: object, default: float = 0.0) -> float:
    try:
        return float(raw)
    except Exception:
        return float(default)


def _normalize_path_key(raw: object) -> str:
    try:
        path = Path(str(raw or "")).expanduser()
    except Exception:
        return ""
    try:
        path = path.resolve()
    except Exception:
        try:
            path = path.absolute()
        except Exception:
            pass
    return str(path).rstrip("\\/").casefold()


def _coerce_path_list(values: object) -> List[str]:
    out: List[str] = []
    if not isinstance(values, (list, tuple, set)):
        return out
    for raw in values:
        s = _safe_str(raw)
        if s:
            out.append(str(Path(s)))
    return out


def _normalize_title_text(title: str) -> str:
    cleaned = NameCleaner.clean(_safe_str(title))
    if cleaned:
        return cleaned
    cleaned = _safe_str(title)
    cleaned = cleaned.replace("_", " ").replace(".", " ").replace("-", " ")
    cleaned = " ".join(part for part in cleaned.split() if part)
    return cleaned.strip()


def _canonical_title_key(title: str, media_type: str, year: Optional[int]) -> str:
    raw = f"{_normalize_title_text(title).casefold()}|{_safe_str(media_type).casefold()}|{year or ''}"
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:20]


def _stable_title_id(source_path: str, title: str, media_type: str, year: Optional[int]) -> str:
    raw = f"{_normalize_path_key(source_path)}|{_canonical_title_key(title, media_type, year)}"
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _json_load(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore")
        if not raw.strip():
            return {}
        obj = json.loads(raw)
    except Exception:
        return None
    if isinstance(obj, dict):
        return obj
    return None


def _json_dump_atomic(target: Path, payload: Dict[str, Any], *, backup_dir: Optional[Path] = None, keep_backups: int = 12) -> None:
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if backup_dir is None:
        backup_dir = target.parent / ".omega_cache" / "library_backups"

    try:
        if target.exists() and target.is_file():
            backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            backup_path = backup_dir / f"{target.stem}.bak.{stamp}{target.suffix}"
            shutil.copy2(target, backup_path)
            _debug_log(f"[LIBRARY][BACKUP] path={backup_path}")

            backups = sorted(
                [p for p in backup_dir.glob(f"{target.stem}.bak.*{target.suffix}") if p.is_file()],
                key=lambda item: (_safe_backup_mtime_ns(item), item.name),
                reverse=True,
            )
            for stale in backups[int(max(1, keep_backups)) :]:
                try:
                    stale.unlink()
                except Exception:
                    pass
    except Exception:
        pass

    tmp = target.parent / f".{target.name}.{uuid.uuid4().hex}.tmp"
    raw = json.dumps(payload, indent=2, ensure_ascii=False)
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(raw)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except Exception:
                pass
        os.replace(str(tmp), str(target))
        _debug_log(f"[LIBRARY][SAVE] path={target}")
        try:
            dir_fd = os.open(str(target.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except Exception:
            pass
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass


def _safe_backup_mtime_ns(path: Path) -> int:
    try:
        return int(path.stat().st_mtime_ns)
    except Exception:
        return 0


@dataclass(frozen=True)
class LibraryBatchSummary:
    batch_id: str
    source_label: str
    candidate_count: int
    imported_count: int
    updated_count: int
    skipped_duplicate_count: int
    failed_count: int
    worker_count: int
    elapsed_s: float
    committed_count: int


@dataclass(frozen=True)
class LibraryHealthReport:
    ok: bool
    total_sources: int
    available_sources: int
    unavailable_sources: int
    total_titles: int
    ready_titles: int
    partial_titles: int
    failed_titles: int
    missing_metadata: int
    missing_art: int
    quarantined_count: int
    active_ingestion_status: str
    active_batch_id: str
    last_scan_at: int
    last_successful_commit_at: int
    latest_errors: Tuple[str, ...]
    notes: Tuple[str, ...] = ()


class LibraryRepository:
    """
    Durable JSON repository for Omega library sources and title snapshots.

    The repository is intentionally conservative:
    - atomic writes
    - timestamped backups
    - backup recovery on corrupt primary files
    - light schema validation and quarantine
    """

    def __init__(self, library_json_path: Path, *, backup_dir: Optional[Path] = None) -> None:
        self.library_json_path = Path(library_json_path)
        self.backup_dir = Path(backup_dir) if backup_dir is not None else None
        self.index_db_path = self.library_json_path.parent / ".omega_cache" / "library_index.sqlite3"
        self._search_index = LibrarySearchIndex(self.index_db_path)
        self._data: Dict[str, Any] = self._empty_payload()
        self._loaded_from_backup = False
        self._load_notes: List[str] = []
        self._ensure_dirs()
        self.load()

    @property
    def data(self) -> Dict[str, Any]:
        return self._data

    def _ensure_dirs(self) -> None:
        try:
            self.library_json_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        if self.backup_dir is not None:
            try:
                self.backup_dir.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass

    def _empty_payload(self) -> Dict[str, Any]:
        return {
            "version": 2,
            "sources": [],
            "titles": [],
            "shows": [],
            "movies": [],
            "updated_at": None,
            "last_scan_at": 0,
            "last_successful_commit_at": 0,
            "last_repair_at": 0,
            "latest_errors": [],
            "quarantined": [],
            "ingestion": {
                "active": False,
                "status": "idle",
                "batch_id": "",
                "reason": "",
                "source_label": "",
                "candidate_count": 0,
                "imported_count": 0,
                "updated_count": 0,
                "skipped_duplicate_count": 0,
                "failed_count": 0,
                "worker_count": 0,
                "started_at": 0,
                "finished_at": 0,
                "elapsed_s": 0.0,
                "error": "",
            },
        }

    def _normalize_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        out = self._empty_payload()
        obj = payload if isinstance(payload, dict) else {}
        out["version"] = max(2, _safe_int(obj.get("version", 2) or 2, 2))
        out["updated_at"] = obj.get("updated_at")
        out["last_scan_at"] = _safe_int(obj.get("last_scan_at", 0))
        out["last_successful_commit_at"] = _safe_int(obj.get("last_successful_commit_at", 0))
        out["last_repair_at"] = _safe_int(obj.get("last_repair_at", 0))
        out["latest_errors"] = self._normalize_error_list(obj.get("latest_errors"))
        out["quarantined"] = self._normalize_quarantine_list(obj.get("quarantined"))
        out["ingestion"] = self._normalize_ingestion(obj.get("ingestion"))
        out["sources"] = self._normalize_sources(obj.get("sources"))

        title_records = obj.get("titles")
        if not isinstance(title_records, list) or not title_records:
            title_records = []
            for legacy_key in ("shows", "movies"):
                legacy_records = obj.get(legacy_key)
                if isinstance(legacy_records, list):
                    title_records.extend(legacy_records)
        normalized_titles: List[Dict[str, Any]] = []
        quarantined: List[Dict[str, Any]] = list(out["quarantined"])
        seen_ids: set[str] = set()
        for raw_record in title_records if isinstance(title_records, list) else []:
            normalized, err = self._normalize_title_record(raw_record)
            if normalized is None:
                if err:
                    quarantined.append({
                        "record": raw_record,
                        "error": err,
                        "quarantined_at": _now_ts(),
                    })
                continue
            title_id = str(normalized.get("title_id", "") or "")
            if title_id and title_id in seen_ids:
                normalized["status"] = "partial"
                normalized.setdefault("warnings", [])
                normalized["warnings"] = list(dict.fromkeys(list(normalized.get("warnings", [])) + ["Duplicate title id during normalization."]))
            if title_id:
                seen_ids.add(title_id)
            normalized_titles.append(normalized)

        out["titles"] = normalized_titles
        out["shows"] = [record for record in normalized_titles if str(record.get("media_type", "")).casefold() != "movie"]
        out["movies"] = [record for record in normalized_titles if str(record.get("media_type", "")).casefold() == "movie"]
        out["quarantined"] = quarantined
        out["updated_at"] = _now_ts()
        return out

    def _normalize_ingestion(self, obj: object) -> Dict[str, Any]:
        base = self._empty_payload()["ingestion"]
        if not isinstance(obj, dict):
            return base
        base.update({
            "active": bool(obj.get("active", False)),
            "status": _safe_str(obj.get("status", "idle")) or "idle",
            "batch_id": _safe_str(obj.get("batch_id", "")),
            "reason": _safe_str(obj.get("reason", "")),
            "source_label": _safe_str(obj.get("source_label", "")),
            "candidate_count": _safe_int(obj.get("candidate_count", 0)),
            "imported_count": _safe_int(obj.get("imported_count", 0)),
            "updated_count": _safe_int(obj.get("updated_count", 0)),
            "skipped_duplicate_count": _safe_int(obj.get("skipped_duplicate_count", 0)),
            "failed_count": _safe_int(obj.get("failed_count", 0)),
            "worker_count": _safe_int(obj.get("worker_count", 0)),
            "started_at": _safe_int(obj.get("started_at", 0)),
            "finished_at": _safe_int(obj.get("finished_at", 0)),
            "elapsed_s": _safe_float(obj.get("elapsed_s", 0.0)),
            "error": _safe_str(obj.get("error", "")),
        })
        return base

    def _normalize_sources(self, raw_sources: object) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if not isinstance(raw_sources, list):
            if isinstance(raw_sources, dict) and "sources" in raw_sources:
                raw_sources = raw_sources.get("sources")
            else:
                return out

        seen: set[str] = set()
        for item in raw_sources:
            path = ""
            enabled = True
            label = ""
            added_at = 0
            status = "available"
            last_scanned_at = 0
            updated_at = 0
            error = ""
            source_id = ""

            if isinstance(item, str):
                path = _safe_str(item)
            elif isinstance(item, dict):
                path = _safe_str(item.get("path", ""))
                enabled = bool(item.get("enabled", True))
                label = _safe_str(item.get("label", ""))
                added_at = _safe_int(item.get("added_at", 0))
                status = _safe_str(item.get("status", "available")) or "available"
                last_scanned_at = _safe_int(item.get("last_scanned_at", 0))
                updated_at = _safe_int(item.get("updated_at", 0))
                error = _safe_str(item.get("error", ""))
                source_id = _safe_str(item.get("source_id", ""))
            if not path:
                continue

            key = _normalize_path_key(path)
            if not key or key in seen:
                continue
            seen.add(key)
            exists = False
            try:
                exists = Path(path).exists() and Path(path).is_dir()
            except Exception:
                exists = False
            out.append(
                {
                    "path": str(Path(path)),
                    "enabled": bool(enabled),
                    "label": label,
                    "added_at": int(added_at),
                    "status": status if exists else "unavailable",
                    "last_scanned_at": int(last_scanned_at),
                    "updated_at": int(updated_at),
                    "error": error if exists else (error or "Source folder unavailable."),
                    "source_id": source_id or hashlib.sha1(key.encode("utf-8", errors="ignore")).hexdigest()[:16],
                }
            )
        return out

    def _normalize_error_list(self, raw: object) -> List[str]:
        if not isinstance(raw, list):
            return []
        out = []
        for item in raw:
            text = _safe_str(item)
            if text and text not in out:
                out.append(text)
        return out[:20]

    def _normalize_quarantine_list(self, raw: object) -> List[Dict[str, Any]]:
        if not isinstance(raw, list):
            return []
        out: List[Dict[str, Any]] = []
        for item in raw:
            if isinstance(item, dict):
                out.append(dict(item))
        return out

    def _normalize_title_record(self, raw: object) -> Tuple[Optional[Dict[str, Any]], str]:
        if not isinstance(raw, dict):
            return None, f"Invalid title record type: {type(raw).__name__}"

        title = _safe_str(raw.get("display_title") or raw.get("title") or "")
        primary_dir = _safe_str(raw.get("primary_dir") or raw.get("path") or "")
        media_type = _safe_str(raw.get("media_type") or "tv").casefold()
        if media_type not in {"movie", "tv"}:
            media_type = "tv"
        year = raw.get("year")
        try:
            year_value = int(year) if year is not None and str(year).strip() else None
        except Exception:
            year_value = None

        if not title:
            return None, "Missing title"
        if not primary_dir:
            return None, "Missing primary_dir"

        source_path = _safe_str(raw.get("source_path") or primary_dir)
        content_key = _safe_str(raw.get("content_key") or _normalize_path_key(primary_dir) or primary_dir)
        title_id = _safe_str(raw.get("title_id") or "")
        if not title_id:
            title_id = _stable_title_id(source_path, title, media_type, year_value)

        canonical_key = _safe_str(raw.get("canonical_key") or "")
        if not canonical_key:
            canonical_key = _canonical_title_key(title, media_type, year_value)

        all_dirs = _coerce_path_list(raw.get("all_dirs") or [])
        if not all_dirs:
            all_dirs = [str(Path(primary_dir))]
        episode_paths = _coerce_path_list(raw.get("episode_paths") or [])

        poster_path = _safe_str(raw.get("poster_path") or "")
        backdrop_path = _safe_str(raw.get("backdrop_path") or "")
        play_path = _safe_str(raw.get("play_path") or "")
        if not play_path and media_type == "movie":
            play_path = primary_dir

        warnings = [str(x).strip() for x in (raw.get("warnings") or []) if str(x).strip()] if isinstance(raw.get("warnings"), list) else []
        errors = [str(x).strip() for x in (raw.get("errors") or []) if str(x).strip()] if isinstance(raw.get("errors"), list) else []
        duplicate_paths = _coerce_path_list(raw.get("duplicate_paths") or [])

        status = _safe_str(raw.get("status") or "")
        if status not in {"pending", "discovering", "metadata_pending", "art_pending", "ready", "partial", "failed"}:
            status = self._derive_status(
                title=title,
                media_type=media_type,
                tmdb_id=raw.get("tmdb_id"),
                poster_path=poster_path,
                backdrop_path=backdrop_path,
                warnings=warnings,
                errors=errors,
            )

        record = {
            "title_id": title_id,
            "canonical_key": canonical_key,
            "content_key": content_key,
            "source_path": source_path,
            "display_title": title,
            "title": title,
            "primary_dir": primary_dir,
            "media_type": media_type,
            "year": year_value,
            "group_mtime": _safe_float(raw.get("group_mtime", 0.0)),
            "all_dirs": all_dirs,
            "play_path": play_path,
            "poster_path": poster_path,
            "backdrop_path": backdrop_path,
            "classification_reason": _safe_str(raw.get("classification_reason") or raw.get("reason") or ""),
            "episode_paths": episode_paths,
            "genres": [str(x).strip() for x in (raw.get("genres") or []) if str(x).strip()] if isinstance(raw.get("genres"), list) else [],
            "overview": _safe_str(raw.get("overview") or ""),
            "rating": raw.get("rating"),
            "tmdb_id": raw.get("tmdb_id"),
            "tmdb_media_type": _safe_str(raw.get("tmdb_media_type") or ""),
            "status": status,
            "source_status": _safe_str(raw.get("source_status") or "available") or "available",
            "source_enabled": bool(raw.get("source_enabled", True)),
            "file_count": _safe_int(raw.get("file_count", len(all_dirs))),
            "episode_count": _safe_int(raw.get("episode_count", len(episode_paths))),
            "warnings": warnings,
            "errors": errors,
            "duplicate_paths": duplicate_paths,
            "duplicate_of": _safe_str(raw.get("duplicate_of") or ""),
            "created_at": _safe_int(raw.get("created_at", 0)),
            "updated_at": _safe_int(raw.get("updated_at", 0)),
            "last_scanned_at": _safe_int(raw.get("last_scanned_at", 0)),
            "metadata_updated_at": _safe_int(raw.get("metadata_updated_at", 0)),
            "art_updated_at": _safe_int(raw.get("art_updated_at", 0)),
            "metadata_source": _safe_str(raw.get("metadata_source") or ""),
            "art_source": _safe_str(raw.get("art_source") or ""),
        }
        return record, ""

    def _derive_status(
        self,
        *,
        title: str,
        media_type: str,
        tmdb_id: object,
        poster_path: str,
        backdrop_path: str,
        warnings: Sequence[str],
        errors: Sequence[str],
    ) -> str:
        if errors:
            return "failed"
        has_metadata = bool(tmdb_id)
        has_art = bool(poster_path or backdrop_path)
        if has_metadata and has_art and not warnings:
            return "ready"
        if not has_metadata and not has_art:
            return "metadata_pending"
        if not has_metadata:
            return "metadata_pending"
        if not has_art:
            return "art_pending"
        return "partial"

    def load(self) -> Dict[str, Any]:
        self._ensure_dirs()
        self._loaded_from_backup = False
        self._load_notes = []
        raw = _json_load(self.library_json_path)
        if raw is None:
            recovered = self.recover_latest_backup()
            if not recovered:
                self._data = self._empty_payload()
                self._load_notes.append("primary library file could not be read")
            self._data = self._normalize_payload(self._data)
            self._sync_search_index(reason="load-recover")
            if recovered:
                try:
                    self.save()
                except Exception:
                    pass
            _debug_log(
                f"[LIBRARY][LOAD] path={self.library_json_path} recovered={bool(recovered)} "
                f"titles={len(self._data.get('titles', []) or [])}"
            )
            return self._data

        self._data = self._normalize_payload(raw)
        self._sync_search_index(reason="load")
        _debug_log(
            f"[LIBRARY][LOAD] path={self.library_json_path} recovered=False "
            f"titles={len(self._data.get('titles', []) or [])}"
        )
        return self._data

    def recover_latest_backup(self) -> bool:
        backups = self._candidate_backups()
        for backup in backups:
            raw = _json_load(backup)
            if raw is None:
                continue
            self._data = self._normalize_payload(raw)
            self._loaded_from_backup = True
            self._load_notes.append(f"recovered from backup: {backup}")
            _debug_log(f"[LIBRARY][RECOVER] path={backup}")
            return True
        return False

    def _candidate_backups(self) -> List[Path]:
        candidates: List[Path] = []
        dirs: List[Path] = []
        if self.backup_dir is not None:
            dirs.append(self.backup_dir)
        dirs.append(self.library_json_path.parent / ".omega_cache" / "library_backups")
        for directory in dirs:
            if not directory.exists() or not directory.is_dir():
                continue
            try:
                candidates.extend([p for p in directory.glob(f"{self.library_json_path.stem}.bak.*{self.library_json_path.suffix}") if p.is_file()])
            except Exception:
                continue
        candidates.sort(key=lambda item: (_safe_backup_mtime_ns(item), item.name), reverse=True)
        return candidates

    def save(self) -> None:
        self._data = self._normalize_payload(self._data)
        _json_dump_atomic(self.library_json_path, self._data, backup_dir=self.backup_dir)

    def _sync_search_index(self, *, reason: str) -> None:
        try:
            self._search_index.rebuild(self.load_title_records(), self.source_records())
            _debug_log(
                f"[LIBRARY][INDEX] reason={reason} path={self.index_db_path} "
                f"titles={len(self.load_title_records())} sources={len(self.source_records())}"
            )
        except Exception as exc:
            self._append_error(f"[INDEX][ERROR] {type(exc).__name__}: {exc}")
            _debug_log(f"[LIBRARY][INDEX][WARN] reason={reason} error={type(exc).__name__}: {exc}")

    def index_health(self) -> Dict[str, Any]:
        try:
            return self._search_index.health()
        except Exception as exc:
            return {
                "ok": False,
                "index_path": str(self.index_db_path),
                "schema_version": 0,
                "fts_enabled": False,
                "title_count": 0,
                "source_count": 0,
                "last_rebuild_at": 0,
                "error": f"{type(exc).__name__}: {exc}",
            }

    def rebuild_search_index(self) -> bool:
        self._sync_search_index(reason="manual-rebuild")
        after = self.index_health()
        return bool(after.get("ok"))

    def search_titles(self, query: str, *, limit: int = 30) -> List[Dict[str, Any]]:
        try:
            return self._search_index.search(query, limit=limit)
        except Exception:
            return []

    def source_records(self) -> List[Dict[str, Any]]:
        sources = self._data.get("sources", [])
        if not isinstance(sources, list):
            return []
        out = []
        for item in sources:
            if isinstance(item, dict):
                out.append(dict(item))
        return out

    def set_source_records(self, records: Sequence[Dict[str, Any]]) -> None:
        self._data["sources"] = self._normalize_sources(list(records))
        self._data["updated_at"] = _now_ts()
        self.save()
        self._sync_search_index(reason="set-sources")

    def upsert_source_records(self, records: Sequence[Dict[str, Any]], *, enabled: Optional[bool] = None) -> Tuple[List[Path], List[Path], List[str]]:
        current = self.source_records()
        seen = {_normalize_path_key(item.get("path", "")) for item in current}
        added: List[Path] = []
        duplicates: List[Path] = []
        invalid: List[str] = []
        for raw_path in records:
            path = _safe_str(raw_path.get("path") if isinstance(raw_path, dict) else raw_path)
            if not path:
                invalid.append(path)
                continue
            normalized_key = _normalize_path_key(path)
            if not normalized_key:
                invalid.append(path)
                continue
            try:
                candidate_path = Path(path).expanduser()
                candidate_path = candidate_path.resolve()
            except Exception:
                candidate_path = Path(path).expanduser()
            if normalized_key in seen:
                duplicates.append(candidate_path)
                continue
            exists = False
            try:
                exists = candidate_path.exists() and candidate_path.is_dir()
            except Exception:
                exists = False
            if not exists:
                invalid.append(path)
                continue
            current.append(
                {
                    "path": str(candidate_path),
                    "enabled": bool(True if enabled is None else enabled),
                    "label": "",
                    "added_at": _now_ts(),
                    "status": "available",
                    "last_scanned_at": 0,
                    "updated_at": _now_ts(),
                    "error": "",
                    "source_id": hashlib.sha1(normalized_key.encode("utf-8", errors="ignore")).hexdigest()[:16],
                }
            )
            seen.add(normalized_key)
            added.append(candidate_path)
        if added:
            self.set_source_records(current)
        return added, duplicates, invalid

    def update_source_statuses(self) -> bool:
        changed = False
        sources = self.source_records()
        for src in sources:
            path = _safe_str(src.get("path", ""))
            exists = False
            try:
                exists = Path(path).exists() and Path(path).is_dir()
            except Exception:
                exists = False
            desired_status = "available" if exists else "unavailable"
            desired_error = "" if exists else "Source folder unavailable."
            if src.get("status") != desired_status:
                src["status"] = desired_status
                changed = True
            if src.get("error") != desired_error:
                src["error"] = desired_error
                changed = True
        if changed:
            self.set_source_records(sources)
        return changed

    def load_title_groups(self) -> List[ShowGroup]:
        titles = self._data.get("titles", [])
        if not isinstance(titles, list):
            return []
        out: List[ShowGroup] = []
        for raw in titles:
            if not isinstance(raw, dict):
                continue
            group = self._show_group_from_record(raw)
            if group is not None:
                out.append(group)
        return out

    def load_title_records(self) -> List[Dict[str, Any]]:
        titles = self._data.get("titles", [])
        if not isinstance(titles, list):
            return []
        out: List[Dict[str, Any]] = []
        for raw in titles:
            if isinstance(raw, dict):
                out.append(dict(raw))
        return out

    def _show_group_from_record(self, record: Dict[str, Any]) -> Optional[ShowGroup]:
        try:
            primary_dir = Path(_safe_str(record.get("primary_dir", "")))
            if not _safe_str(primary_dir):
                return None

            poster = _safe_str(record.get("poster_path", ""))
            backdrop = _safe_str(record.get("backdrop_path", ""))
            poster_path = Path(poster) if poster else None
            backdrop_path = Path(backdrop) if backdrop else None
            play_path = _safe_str(record.get("play_path", ""))
            play = Path(play_path) if play_path else None
            all_dirs = [Path(str(p)) for p in _coerce_path_list(record.get("all_dirs") or [])]
            if not all_dirs:
                all_dirs = [primary_dir]
            episode_paths = tuple(Path(str(p)) for p in _coerce_path_list(record.get("episode_paths") or []))
            genres = tuple(str(x).strip() for x in (record.get("genres") or []) if str(x).strip()) if isinstance(record.get("genres"), list) else ()
            rating = record.get("rating")
            try:
                rating_value = float(rating) if rating is not None else None
            except Exception:
                rating_value = None

            return ShowGroup(
                display_title=_safe_str(record.get("display_title") or record.get("title") or primary_dir.name),
                primary_dir=primary_dir,
                poster_path=poster_path,
                group_mtime=_safe_float(record.get("group_mtime", 0.0)),
                all_dirs=all_dirs,
                media_type=_safe_str(record.get("media_type", "tv")) or "tv",
                play_path=play,
                content_key=_safe_str(record.get("content_key") or _normalize_path_key(primary_dir)),
                year=record.get("year"),
                genres=genres,
                overview=_safe_str(record.get("overview") or ""),
                rating=rating_value,
                tmdb_id=record.get("tmdb_id"),
                tmdb_media_type=_safe_str(record.get("tmdb_media_type") or ""),
                backdrop_path=backdrop_path,
                classification_reason=_safe_str(record.get("classification_reason") or ""),
                episode_paths=episode_paths,
                title_id=_safe_str(record.get("title_id") or ""),
                status=_safe_str(record.get("status") or "ready"),
                source_path=_safe_str(record.get("source_path") or ""),
                source_status=_safe_str(record.get("source_status") or "available"),
                source_enabled=bool(record.get("source_enabled", True)),
                created_at=_safe_int(record.get("created_at", 0)),
                updated_at=_safe_int(record.get("updated_at", 0)),
                last_scanned_at=_safe_int(record.get("last_scanned_at", 0)),
                metadata_updated_at=_safe_int(record.get("metadata_updated_at", 0)),
                art_updated_at=_safe_int(record.get("art_updated_at", 0)),
                warnings=tuple(str(x).strip() for x in (record.get("warnings") or []) if str(x).strip()) if isinstance(record.get("warnings"), list) else (),
                errors=tuple(str(x).strip() for x in (record.get("errors") or []) if str(x).strip()) if isinstance(record.get("errors"), list) else (),
                duplicate_paths=tuple(Path(str(p)) for p in _coerce_path_list(record.get("duplicate_paths") or [])),
                duplicate_of=_safe_str(record.get("duplicate_of") or ""),
                metadata_source=_safe_str(record.get("metadata_source") or ""),
                art_source=_safe_str(record.get("art_source") or ""),
                file_count=_safe_int(record.get("file_count", len(all_dirs))),
                episode_count=_safe_int(record.get("episode_count", len(episode_paths))),
            )
        except Exception:
            return None

    def _record_from_show_group(self, sg: ShowGroup) -> Dict[str, Any]:
        primary_dir = Path(str(getattr(sg, "primary_dir", "")))
        source_path = _safe_str(getattr(sg, "source_path", "") or primary_dir)
        title = _safe_str(getattr(sg, "display_title", "") or getattr(sg, "title", "") or primary_dir.name or "Untitled")
        media_type = _safe_str(getattr(sg, "media_type", "") or "tv").casefold()
        if media_type not in {"movie", "tv"}:
            media_type = "tv"
        try:
            year = int(getattr(sg, "year", None)) if getattr(sg, "year", None) is not None else None
        except Exception:
            year = None
        title_id = _safe_str(getattr(sg, "title_id", "") or "")
        if not title_id:
            title_id = _stable_title_id(source_path, title, media_type, year)

        canonical_key = _canonical_title_key(title, media_type, year)
        content_key = _safe_str(getattr(sg, "content_key", "") or _normalize_path_key(primary_dir) or primary_dir)
        all_dirs = [str(Path(str(p))) for p in (getattr(sg, "all_dirs", []) or []) if p is not None]
        if not all_dirs:
            all_dirs = [str(primary_dir)]
        episode_paths = [str(Path(str(p))) for p in (getattr(sg, "episode_paths", ()) or ()) if p is not None]
        poster_path = getattr(sg, "poster_path", None)
        backdrop_path = getattr(sg, "backdrop_path", None)
        play_path = getattr(sg, "play_path", None)
        warnings = [str(x).strip() for x in (getattr(sg, "warnings", ()) or ()) if str(x).strip()]
        errors = [str(x).strip() for x in (getattr(sg, "errors", ()) or ()) if str(x).strip()]
        duplicate_paths = [str(Path(str(p))) for p in (getattr(sg, "duplicate_paths", ()) or ()) if p is not None]
        status = _safe_str(getattr(sg, "status", "") or "")
        if status not in {"pending", "discovering", "metadata_pending", "art_pending", "ready", "partial", "failed"}:
            status = self._derive_status(
                title=title,
                media_type=media_type,
                tmdb_id=getattr(sg, "tmdb_id", None),
                poster_path=str(poster_path) if poster_path is not None else "",
                backdrop_path=str(backdrop_path) if backdrop_path is not None else "",
                warnings=warnings,
                errors=errors,
            )

        record = {
            "title_id": title_id,
            "canonical_key": canonical_key,
            "content_key": content_key,
            "source_path": source_path,
            "display_title": title,
            "title": title,
            "primary_dir": str(primary_dir),
            "media_type": media_type,
            "year": year,
            "group_mtime": _safe_float(getattr(sg, "group_mtime", 0.0)),
            "all_dirs": all_dirs,
            "play_path": str(play_path) if play_path is not None else "",
            "poster_path": str(poster_path) if poster_path is not None else "",
            "backdrop_path": str(backdrop_path) if backdrop_path is not None else "",
            "classification_reason": _safe_str(getattr(sg, "classification_reason", "") or ""),
            "episode_paths": episode_paths,
            "genres": [str(x).strip() for x in (getattr(sg, "genres", ()) or ()) if str(x).strip()],
            "overview": _safe_str(getattr(sg, "overview", "") or ""),
            "rating": getattr(sg, "rating", None),
            "tmdb_id": getattr(sg, "tmdb_id", None),
            "tmdb_media_type": _safe_str(getattr(sg, "tmdb_media_type", "") or ""),
            "status": status,
            "source_status": _safe_str(getattr(sg, "source_status", "") or "available"),
            "source_enabled": bool(getattr(sg, "source_enabled", True)),
            "file_count": _safe_int(getattr(sg, "file_count", len(all_dirs))),
            "episode_count": _safe_int(getattr(sg, "episode_count", len(episode_paths))),
            "warnings": warnings,
            "errors": errors,
            "duplicate_paths": duplicate_paths,
            "duplicate_of": _safe_str(getattr(sg, "duplicate_of", "") or ""),
            "created_at": _safe_int(getattr(sg, "created_at", 0)),
            "updated_at": _safe_int(getattr(sg, "updated_at", 0)),
            "last_scanned_at": _safe_int(getattr(sg, "last_scanned_at", 0)),
            "metadata_updated_at": _safe_int(getattr(sg, "metadata_updated_at", 0)),
            "art_updated_at": _safe_int(getattr(sg, "art_updated_at", 0)),
            "metadata_source": _safe_str(getattr(sg, "metadata_source", "") or ""),
            "art_source": _safe_str(getattr(sg, "art_source", "") or ""),
        }
        return record

    def commit_title_groups(
        self,
        items: Sequence[ShowGroup],
        *,
        source_label: str,
        batch_id: str,
        worker_count: int,
    ) -> LibraryBatchSummary:
        start = time.perf_counter()
        self._data = self._normalize_payload(self._data)
        existing_records = self.load_title_records()
        existing_by_id: Dict[str, Dict[str, Any]] = {}
        canonical_primary: Dict[str, str] = {}
        for raw in existing_records:
            title_id = _safe_str(raw.get("title_id") or "")
            canonical_key = _safe_str(raw.get("canonical_key") or "")
            if title_id:
                existing_by_id[title_id] = dict(raw)
            if canonical_key and canonical_key not in canonical_primary and title_id:
                existing_by_id[title_id] = dict(raw)
                canonical_primary[canonical_key] = title_id

        imported_count = 0
        updated_count = 0
        skipped_duplicate_count = 0
        failed_count = 0
        now = _now_ts()

        for raw_group in list(items or []):
            try:
                group = raw_group
                record = self._record_from_show_group(group)
            except Exception as exc:
                failed_count += 1
                self._append_error(f"[INGEST][ERROR] {type(exc).__name__}: {exc}")
                continue

            title_id = _safe_str(record.get("title_id") or "")
            canonical_key = _safe_str(record.get("canonical_key") or "")
            title_name = _safe_str(record.get("display_title") or "")
            title_action = "imported"
            existing = existing_by_id.get(title_id)
            if existing is not None:
                merged, changed = self._merge_title_records(existing, record, now=now)
                existing_by_id[title_id] = merged
                if changed:
                    updated_count += 1
                _debug_log(
                    f"[INGEST][TITLE] batch_id={batch_id} title_id={title_id} title={title_name} "
                    f"action={'updated' if changed else 'kept'} status={_safe_str(merged.get('status') or '')}"
                )
                continue

            if canonical_key and canonical_key in canonical_primary:
                record["duplicate_of"] = canonical_primary[canonical_key]
                record["status"] = "partial"
                warnings = list(record.get("warnings") or [])
                if "Possible duplicate candidate." not in warnings:
                    warnings.append("Possible duplicate candidate.")
                record["warnings"] = warnings
                skipped_duplicate_count += 1
                title_action = "duplicate"

            record["created_at"] = now if not _safe_int(record.get("created_at", 0)) else _safe_int(record.get("created_at", 0))
            record["updated_at"] = now
            record["last_scanned_at"] = now
            if _safe_str(record.get("status") or "") == "":
                record["status"] = self._derive_status(
                    title=_safe_str(record.get("display_title") or ""),
                    media_type=_safe_str(record.get("media_type") or ""),
                    tmdb_id=record.get("tmdb_id"),
                    poster_path=_safe_str(record.get("poster_path") or ""),
                    backdrop_path=_safe_str(record.get("backdrop_path") or ""),
                    warnings=record.get("warnings") or [],
                    errors=record.get("errors") or [],
                )
            existing_by_id[title_id] = record
            if canonical_key and canonical_key not in canonical_primary:
                canonical_primary[canonical_key] = title_id
            imported_count += 1
            _debug_log(
                f"[INGEST][TITLE] batch_id={batch_id} title_id={title_id} title={title_name} "
                f"action={title_action} status={_safe_str(record.get('status') or '')}"
            )

        normalized_records = list(existing_by_id.values())
        normalized_records.sort(
            key=lambda rec: (
                _safe_str(rec.get("display_title") or "").casefold(),
                _safe_str(rec.get("primary_dir") or "").casefold(),
                _safe_str(rec.get("title_id") or "").casefold(),
            )
        )

        self._data["titles"] = normalized_records
        self._data["shows"] = [record for record in normalized_records if _safe_str(record.get("media_type") or "").casefold() != "movie"]
        self._data["movies"] = [record for record in normalized_records if _safe_str(record.get("media_type") or "").casefold() == "movie"]
        self._data["updated_at"] = now
        self._data["last_scan_at"] = now
        self._data["last_successful_commit_at"] = now
        self._data["ingestion"] = {
            "active": False,
            "status": "complete",
            "batch_id": _safe_str(batch_id),
            "reason": _safe_str(source_label),
            "source_label": _safe_str(source_label),
            "candidate_count": len(list(items or [])),
            "imported_count": imported_count,
            "updated_count": updated_count,
            "skipped_duplicate_count": skipped_duplicate_count,
            "failed_count": failed_count,
            "worker_count": _safe_int(worker_count),
            "started_at": _safe_int(self._data.get("ingestion", {}).get("started_at", 0) if isinstance(self._data.get("ingestion"), dict) else 0),
            "finished_at": now,
            "elapsed_s": max(0.0, time.perf_counter() - start),
            "error": "",
        }
        self.save()
        self._sync_search_index(reason="commit")
        return LibraryBatchSummary(
            batch_id=_safe_str(batch_id),
            source_label=_safe_str(source_label),
            candidate_count=len(list(items or [])),
            imported_count=imported_count,
            updated_count=updated_count,
            skipped_duplicate_count=skipped_duplicate_count,
            failed_count=failed_count,
            worker_count=_safe_int(worker_count),
            elapsed_s=max(0.0, time.perf_counter() - start),
            committed_count=len(normalized_records),
        )

    def _merge_title_records(self, existing: Dict[str, Any], incoming: Dict[str, Any], *, now: int) -> Tuple[Dict[str, Any], bool]:
        merged = dict(existing)
        changed = False

        preserve_nonempty = {
            "poster_path",
            "backdrop_path",
            "play_path",
            "tmdb_id",
            "tmdb_media_type",
            "overview",
            "rating",
            "source_path",
            "classification_reason",
            "content_key",
            "title_id",
            "canonical_key",
            "duplicate_of",
        }

        for key, value in incoming.items():
            if key in {"created_at"}:
                continue
            if key in {"updated_at", "last_scanned_at"}:
                continue
            if key in {"warnings", "errors", "duplicate_paths"}:
                existing_list = list(merged.get(key) or [])
                for item in list(value or []):
                    if item not in existing_list:
                        existing_list.append(item)
                        changed = True
                merged[key] = existing_list
                continue
            if key in {"all_dirs", "episode_paths", "genres"}:
                incoming_list = list(value or [])
                existing_list = list(merged.get(key) or [])
                if incoming_list:
                    for item in incoming_list:
                        if item not in existing_list:
                            existing_list.append(item)
                    if existing_list != list(merged.get(key) or []):
                        changed = True
                    merged[key] = existing_list
                continue
            if key in preserve_nonempty and not _safe_str(value).strip() and merged.get(key):
                continue
            if merged.get(key) != value:
                merged[key] = value
                changed = True

        merged["updated_at"] = now
        merged["last_scanned_at"] = now
        if _safe_int(merged.get("metadata_updated_at", 0)) <= 0 and _safe_int(incoming.get("metadata_updated_at", 0)) > 0:
            merged["metadata_updated_at"] = _safe_int(incoming.get("metadata_updated_at", 0))
        if _safe_int(merged.get("art_updated_at", 0)) <= 0 and _safe_int(incoming.get("art_updated_at", 0)) > 0:
            merged["art_updated_at"] = _safe_int(incoming.get("art_updated_at", 0))

        merged["status"] = self._derive_status(
            title=_safe_str(merged.get("display_title") or ""),
            media_type=_safe_str(merged.get("media_type") or ""),
            tmdb_id=merged.get("tmdb_id"),
            poster_path=_safe_str(merged.get("poster_path") or ""),
            backdrop_path=_safe_str(merged.get("backdrop_path") or ""),
            warnings=merged.get("warnings") or [],
            errors=merged.get("errors") or [],
        )
        return merged, changed

    def _append_error(self, message: str) -> None:
        text = _safe_str(message)
        if not text:
            return
        errors = self._data.setdefault("latest_errors", [])
        if not isinstance(errors, list):
            errors = []
            self._data["latest_errors"] = errors
        if text in errors:
            errors.remove(text)
        errors.insert(0, text)
        del errors[20:]

    def latest_errors(self) -> List[str]:
        errors = self._data.get("latest_errors", [])
        if not isinstance(errors, list):
            return []
        return [str(item) for item in errors if str(item).strip()]

    def record_ingestion_start(
        self,
        *,
        batch_id: str,
        source_label: str,
        worker_count: int,
        candidate_count: int = 0,
    ) -> None:
        now = _now_ts()
        self._data = self._normalize_payload(self._data)
        self._data["ingestion"] = {
            "active": True,
            "status": "running",
            "batch_id": _safe_str(batch_id),
            "reason": _safe_str(source_label),
            "source_label": _safe_str(source_label),
            "candidate_count": _safe_int(candidate_count),
            "imported_count": 0,
            "updated_count": 0,
            "skipped_duplicate_count": 0,
            "failed_count": 0,
            "worker_count": _safe_int(worker_count),
            "started_at": now,
            "finished_at": 0,
            "elapsed_s": 0.0,
            "error": "",
        }
        self._data["updated_at"] = now
        self.save()

    def record_ingestion_finish(self, *, batch_id: str, summary: Optional[LibraryBatchSummary] = None, error: str = "") -> None:
        now = _now_ts()
        ingestion = self._data.get("ingestion", {})
        if not isinstance(ingestion, dict):
            ingestion = {}
        started_at = _safe_int(ingestion.get("started_at", 0))
        elapsed = _safe_float(summary.elapsed_s if summary is not None else ingestion.get("elapsed_s", 0.0))
        if started_at > 0 and elapsed <= 0.0:
            elapsed = max(0.0, float(now - started_at))
        payload = {
            "active": False,
            "status": "failed" if _safe_str(error) else ("complete" if summary is not None else "idle"),
            "batch_id": _safe_str(batch_id),
            "reason": _safe_str(ingestion.get("reason", "")),
            "source_label": _safe_str(ingestion.get("source_label", "")),
            "candidate_count": _safe_int(summary.candidate_count if summary is not None else ingestion.get("candidate_count", 0)),
            "imported_count": _safe_int(summary.imported_count if summary is not None else ingestion.get("imported_count", 0)),
            "updated_count": _safe_int(summary.updated_count if summary is not None else ingestion.get("updated_count", 0)),
            "skipped_duplicate_count": _safe_int(summary.skipped_duplicate_count if summary is not None else ingestion.get("skipped_duplicate_count", 0)),
            "failed_count": _safe_int(summary.failed_count if summary is not None else ingestion.get("failed_count", 0)),
            "worker_count": _safe_int(summary.worker_count if summary is not None else ingestion.get("worker_count", 0)),
            "started_at": started_at,
            "finished_at": now,
            "elapsed_s": float(elapsed),
            "error": _safe_str(error),
        }
        self._data["ingestion"] = payload
        self._data["last_scan_at"] = now
        self._data["updated_at"] = now
        if not error:
            self._data["last_successful_commit_at"] = now
        if error:
            self._append_error(error)
        self.save()

    def health_check(self) -> LibraryHealthReport:
        self._data = self._normalize_payload(self._data)
        sources = self.source_records()
        titles = self.load_title_records()
        total_sources = len(sources)
        available_sources = 0
        unavailable_sources = 0
        for src in sources:
            exists = False
            try:
                exists = Path(_safe_str(src.get("path", ""))).exists() and Path(_safe_str(src.get("path", ""))).is_dir()
            except Exception:
                exists = False
            if exists and bool(src.get("enabled", True)) and _safe_str(src.get("status", "available")) != "unavailable":
                available_sources += 1
            else:
                unavailable_sources += 1

        ready_titles = sum(1 for rec in titles if _safe_str(rec.get("status", "")).casefold() == "ready")
        partial_titles = sum(1 for rec in titles if _safe_str(rec.get("status", "")).casefold() in {"partial", "metadata_pending", "art_pending", "discovering"})
        failed_titles = sum(1 for rec in titles if _safe_str(rec.get("status", "")).casefold() == "failed")
        missing_metadata = sum(1 for rec in titles if not rec.get("tmdb_id"))
        missing_art = sum(1 for rec in titles if not _safe_str(rec.get("poster_path", "")) and not _safe_str(rec.get("backdrop_path", "")))
        quarantined = self._data.get("quarantined", [])
        if not isinstance(quarantined, list):
            quarantined = []
        ingestion = self._data.get("ingestion", {})
        if not isinstance(ingestion, dict):
            ingestion = self._empty_payload()["ingestion"]
        notes = tuple(self._load_notes[:8])
        latest_errors = tuple(self.latest_errors()[:8])
        ok = True
        if self._loaded_from_backup:
            notes = ("Recovered from backup.",) + notes
        if failed_titles > 0 or unavailable_sources > 0:
            ok = False
        return LibraryHealthReport(
            ok=ok,
            total_sources=total_sources,
            available_sources=available_sources,
            unavailable_sources=unavailable_sources,
            total_titles=len(titles),
            ready_titles=ready_titles,
            partial_titles=partial_titles,
            failed_titles=failed_titles,
            missing_metadata=missing_metadata,
            missing_art=missing_art,
            quarantined_count=len(quarantined),
            active_ingestion_status=_safe_str(ingestion.get("status", "idle") or "idle"),
            active_batch_id=_safe_str(ingestion.get("batch_id", "") or ""),
            last_scan_at=_safe_int(self._data.get("last_scan_at", 0)),
            last_successful_commit_at=_safe_int(self._data.get("last_successful_commit_at", 0)),
            latest_errors=latest_errors,
            notes=notes,
        )

    def repair_index(self) -> Tuple[LibraryHealthReport, bool]:
        before = json.dumps(self._data, sort_keys=True, ensure_ascii=False)
        self._data = self._normalize_payload(self._data)
        self._data["last_repair_at"] = _now_ts()
        after = json.dumps(self._data, sort_keys=True, ensure_ascii=False)
        changed = before != after
        if changed:
            self.save()
        self._sync_search_index(reason="repair")
        return self.health_check(), changed
