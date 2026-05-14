from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple


SCHEMA_VERSION = 1


def _safe_int(raw: object, default: int = 0) -> int:
    try:
        return int(raw)
    except Exception:
        return int(default)


def _safe_str(raw: object) -> str:
    return str(raw or "").strip()


class LibrarySearchIndex:
    """
    Derived SQLite index for fast library diagnostics and search.

    JSON remains canonical. This index can always be rebuilt from JSON.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._fts_enabled = False
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=OFF;")
        return conn

    def _ensure_schema(self) -> None:
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS meta (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS titles (
                        title_id TEXT PRIMARY KEY,
                        display_title TEXT NOT NULL,
                        media_type TEXT NOT NULL,
                        year INTEGER,
                        source_path TEXT,
                        content_key TEXT,
                        status TEXT,
                        has_art INTEGER NOT NULL DEFAULT 0,
                        has_metadata INTEGER NOT NULL DEFAULT 0,
                        updated_at INTEGER NOT NULL DEFAULT 0,
                        search_text TEXT NOT NULL DEFAULT ''
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS sources (
                        source_id TEXT PRIMARY KEY,
                        path TEXT NOT NULL,
                        enabled INTEGER NOT NULL DEFAULT 1,
                        status TEXT NOT NULL DEFAULT 'available',
                        last_scanned_at INTEGER NOT NULL DEFAULT 0,
                        updated_at INTEGER NOT NULL DEFAULT 0
                    )
                    """
                )

                self._fts_enabled = False
                try:
                    conn.execute(
                        """
                        CREATE VIRTUAL TABLE IF NOT EXISTS titles_fts
                        USING fts5(
                            title_id UNINDEXED,
                            display_title,
                            search_text
                        )
                        """
                    )
                    self._fts_enabled = True
                except sqlite3.OperationalError:
                    self._fts_enabled = False

                conn.execute(
                    "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
                    (str(int(SCHEMA_VERSION)),),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO meta(key, value) VALUES ('fts_enabled', ?)",
                    ("1" if self._fts_enabled else "0",),
                )
                conn.commit()
        except sqlite3.DatabaseError:
            self._recover_from_corruption("ensure_schema")

    def _recover_from_corruption(self, reason: str) -> None:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        bad_path = self.db_path.with_suffix(f".corrupt-{stamp}.sqlite3")
        try:
            if self.db_path.exists():
                self.db_path.replace(bad_path)
        except Exception:
            try:
                self.db_path.unlink(missing_ok=True)
            except Exception:
                pass
        self._fts_enabled = False
        self._ensure_schema()

    def rebuild(self, titles: Sequence[Dict[str, Any]], sources: Sequence[Dict[str, Any]]) -> None:
        now = int(time.time())
        try:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("DELETE FROM titles")
                conn.execute("DELETE FROM sources")
                if self._fts_enabled:
                    conn.execute("DELETE FROM titles_fts")

                title_rows: List[Tuple[Any, ...]] = []
                fts_rows: List[Tuple[str, str, str]] = []
                for rec in titles or []:
                    title_id = _safe_str(rec.get("title_id"))
                    if not title_id:
                        continue
                    display_title = _safe_str(rec.get("display_title") or rec.get("title"))
                    media_type = _safe_str(rec.get("media_type") or "tv")
                    year = rec.get("year")
                    has_art = 1 if (_safe_str(rec.get("poster_path")) or _safe_str(rec.get("backdrop_path"))) else 0
                    has_metadata = 1 if rec.get("tmdb_id") else 0
                    updated_at = _safe_int(rec.get("updated_at", 0))
                    search_text = " ".join(
                        bit
                        for bit in [
                            display_title,
                            _safe_str(rec.get("overview")),
                            " ".join(str(x).strip() for x in (rec.get("genres") or []) if str(x).strip()),
                        ]
                        if bit
                    )
                    title_rows.append(
                        (
                            title_id,
                            display_title,
                            media_type,
                            year,
                            _safe_str(rec.get("source_path")),
                            _safe_str(rec.get("content_key")),
                            _safe_str(rec.get("status")),
                            has_art,
                            has_metadata,
                            updated_at,
                            search_text,
                        )
                    )
                    if self._fts_enabled:
                        fts_rows.append((title_id, display_title, search_text))

                if title_rows:
                    conn.executemany(
                        """
                        INSERT INTO titles(
                            title_id, display_title, media_type, year, source_path, content_key, status,
                            has_art, has_metadata, updated_at, search_text
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        title_rows,
                    )
                if fts_rows and self._fts_enabled:
                    conn.executemany(
                        "INSERT INTO titles_fts(title_id, display_title, search_text) VALUES (?, ?, ?)",
                        fts_rows,
                    )

                source_rows: List[Tuple[Any, ...]] = []
                for rec in sources or []:
                    source_path = _safe_str(rec.get("path"))
                    if not source_path:
                        continue
                    source_id = _safe_str(rec.get("source_id")) or source_path.casefold()
                    source_rows.append(
                        (
                            source_id,
                            source_path,
                            1 if bool(rec.get("enabled", True)) else 0,
                            _safe_str(rec.get("status") or "available"),
                            _safe_int(rec.get("last_scanned_at", 0)),
                            _safe_int(rec.get("updated_at", 0)),
                        )
                    )
                if source_rows:
                    conn.executemany(
                        """
                        INSERT INTO sources(source_id, path, enabled, status, last_scanned_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        source_rows,
                    )

                conn.execute(
                    "INSERT OR REPLACE INTO meta(key, value) VALUES ('last_rebuild_at', ?)",
                    (str(now),),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO meta(key, value) VALUES ('title_count', ?)",
                    (str(len(title_rows)),),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO meta(key, value) VALUES ('source_count', ?)",
                    (str(len(source_rows)),),
                )
                conn.commit()
        except sqlite3.DatabaseError:
            self._recover_from_corruption("rebuild")
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("DELETE FROM titles")
                conn.execute("DELETE FROM sources")
                if self._fts_enabled:
                    conn.execute("DELETE FROM titles_fts")
                conn.commit()
            # Retry once after recovery.
            self.rebuild(titles, sources)

    def search(self, query: str, *, limit: int = 30) -> List[Dict[str, Any]]:
        q = _safe_str(query)
        max_rows = max(1, min(200, int(limit)))
        try:
            with self._connect() as conn:
                if q:
                    if self._fts_enabled:
                        rows = conn.execute(
                            """
                            SELECT t.title_id, t.display_title, t.media_type, t.year, t.status, t.source_path,
                                   t.has_art, t.has_metadata, t.updated_at
                            FROM titles_fts f
                            JOIN titles t ON t.title_id = f.title_id
                            WHERE titles_fts MATCH ?
                            ORDER BY bm25(titles_fts), t.display_title COLLATE NOCASE
                            LIMIT ?
                            """,
                            (q, max_rows),
                        ).fetchall()
                    else:
                        like = f"%{q}%"
                        rows = conn.execute(
                            """
                            SELECT title_id, display_title, media_type, year, status, source_path,
                                   has_art, has_metadata, updated_at
                            FROM titles
                            WHERE display_title LIKE ? OR search_text LIKE ?
                            ORDER BY display_title COLLATE NOCASE
                            LIMIT ?
                            """,
                            (like, like, max_rows),
                        ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT title_id, display_title, media_type, year, status, source_path,
                               has_art, has_metadata, updated_at
                        FROM titles
                        ORDER BY updated_at DESC, display_title COLLATE NOCASE
                        LIMIT ?
                        """,
                        (max_rows,),
                    ).fetchall()
        except sqlite3.DatabaseError:
            self._recover_from_corruption("search")
            return []

        out: List[Dict[str, Any]] = []
        for row in rows:
            out.append(
                {
                    "title_id": _safe_str(row[0]),
                    "display_title": _safe_str(row[1]),
                    "media_type": _safe_str(row[2]),
                    "year": row[3],
                    "status": _safe_str(row[4]),
                    "source_path": _safe_str(row[5]),
                    "has_art": bool(row[6]),
                    "has_metadata": bool(row[7]),
                    "updated_at": _safe_int(row[8], 0),
                }
            )
        return out

    def health(self) -> Dict[str, Any]:
        snapshot = {
            "ok": True,
            "index_path": str(self.db_path),
            "schema_version": SCHEMA_VERSION,
            "fts_enabled": bool(self._fts_enabled),
            "title_count": 0,
            "source_count": 0,
            "last_rebuild_at": 0,
            "error": "",
        }
        try:
            with self._connect() as conn:
                title_count = conn.execute("SELECT COUNT(*) FROM titles").fetchone()
                source_count = conn.execute("SELECT COUNT(*) FROM sources").fetchone()
                meta_rows = conn.execute(
                    "SELECT key, value FROM meta WHERE key IN ('last_rebuild_at', 'schema_version', 'fts_enabled')"
                ).fetchall()
            meta = {str(k): str(v) for k, v in meta_rows}
            snapshot["title_count"] = _safe_int(title_count[0] if title_count else 0, 0)
            snapshot["source_count"] = _safe_int(source_count[0] if source_count else 0, 0)
            snapshot["last_rebuild_at"] = _safe_int(meta.get("last_rebuild_at", 0), 0)
            snapshot["schema_version"] = _safe_int(meta.get("schema_version", SCHEMA_VERSION), SCHEMA_VERSION)
            snapshot["fts_enabled"] = str(meta.get("fts_enabled", "0")) == "1"
        except sqlite3.DatabaseError as exc:
            snapshot["ok"] = False
            snapshot["error"] = f"{type(exc).__name__}: {exc}"
        return snapshot

