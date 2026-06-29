from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from typing import Any


class SourceCache:
    def __init__(self, db_path: str | None = None, ttl: int = 604800) -> None:
        from argus.shared.config import settings as _s
        self._db_path = db_path or _s.sqlite_path
        self._ttl = ttl or _s.source_cache_ttl
        self._local: threading.local = threading.local()
        self._hits = 0
        self._misses = 0
        self._stats_lock = threading.Lock()

    def _get_db(self) -> Any:  # noqa: ANN401
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is not None:
            return conn
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS source_cache (
                url_hash TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                markdown TEXT NOT NULL,
                content_type TEXT DEFAULT '',
                fetched_at REAL NOT NULL,
                keep INTEGER NOT NULL DEFAULT 0
            )"""
        )
        conn.commit()
        self._local.conn = conn
        return conn

    def _hash_url(self, url: str) -> str:
        return hashlib.sha256(url.encode()).hexdigest()

    def get(self, url: str) -> str | None:
        conn: sqlite3.Connection = self._get_db()
        url_hash = self._hash_url(url)
        cursor = conn.execute(
            "SELECT markdown, fetched_at, keep FROM source_cache WHERE url_hash = ?",
            (url_hash,),
        )
        row = cursor.fetchone()
        if row is None:
            self._track_miss()
            return None

        markdown: Any = row[0]
        fetched_at: Any = row[1]
        keep: Any = row[2]
        if not keep and time.time() - fetched_at > self._ttl:
            conn.execute("DELETE FROM source_cache WHERE url_hash = ?", (url_hash,))
            conn.commit()
            self._track_miss()
            return None

        self._track_hit()
        return str(markdown) if markdown is not None else None

    def set(self, url: str, markdown: str, content_type: str = "", keep: bool = False) -> None:
        conn: sqlite3.Connection = self._get_db()
        url_hash = self._hash_url(url)
        conn.execute(
            "INSERT OR REPLACE INTO source_cache "
            "(url_hash, url, markdown, content_type, fetched_at, keep) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (url_hash, url, markdown, content_type, time.time(), 1 if keep else 0),
        )
        conn.commit()

    def mark_keep(self, url: str) -> bool:
        conn: sqlite3.Connection = self._get_db()
        url_hash = self._hash_url(url)
        cursor = conn.execute(
            "UPDATE source_cache SET keep = 1 WHERE url_hash = ?", (url_hash,)
        )
        conn.commit()
        return cursor.rowcount > 0

    def clear_expired(self) -> int:
        conn: sqlite3.Connection = self._get_db()
        cutoff = time.time() - self._ttl
        cursor = conn.execute(
            "DELETE FROM source_cache WHERE keep = 0 AND fetched_at < ?", (cutoff,)
        )
        conn.commit()
        return cursor.rowcount

    def get_stats(self) -> dict[str, Any]:
        conn: sqlite3.Connection = self._get_db()
        total = conn.execute("SELECT COUNT(*) FROM source_cache").fetchone()
        kept = conn.execute("SELECT COUNT(*) FROM source_cache WHERE keep = 1").fetchone()
        expired = conn.execute(
            "SELECT COUNT(*) FROM source_cache WHERE keep = 0 AND fetched_at < ?",
            (time.time() - self._ttl,),
        ).fetchone()
        oldest = conn.execute(
            "SELECT MIN(fetched_at) FROM source_cache"
        ).fetchone()
        newest = conn.execute(
            "SELECT MAX(fetched_at) FROM source_cache"
        ).fetchone()
        total_size = conn.execute(
            "SELECT SUM(LENGTH(markdown)) FROM source_cache"
        ).fetchone()
        with self._stats_lock:
            hits = self._hits
            misses = self._misses
        total_requests = hits + misses
        hit_rate = hits / total_requests if total_requests > 0 else 0.0

        return {
            "total_entries": total[0] if total else 0,
            "kept_entries": kept[0] if kept else 0,
            "expirable_entries": (total[0] or 0) - (kept[0] or 0),
            "expired_pending_deletion": expired[0] if expired else 0,
            "oldest_entry_timestamp": oldest[0] if oldest and oldest[0] else 0.0,
            "newest_entry_timestamp": newest[0] if newest and newest[0] else 0.0,
            "total_size_bytes": total_size[0] if total_size and total_size[0] else 0,
            "hit_rate": hit_rate,
            "hits": hits,
            "misses": misses,
            "ttl_seconds": self._ttl,
        }

    def _track_hit(self) -> None:
        with self._stats_lock:
            self._hits += 1

    def _track_miss(self) -> None:
        with self._stats_lock:
            self._misses += 1
