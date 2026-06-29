from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from typing import Any

import redis as redis_lib

from argus.services.knowledge_graph.schema import init_db
from argus.shared.config import settings

logger = logging.getLogger(__name__)


class KGWriter:
    FLUSH_INTERVAL = 0.05
    BATCH_SIZE = 100

    def __init__(
        self,
        db_path: str | None = None,
        redis_client: redis_lib.Redis | None = None,
    ) -> None:
        self._db_path = db_path or settings.sqlite_path
        self._redis = redis_client
        self._lock = threading.Lock()
        self._buffer: list[dict[str, Any]] = []
        self._running = False

    def _get_redis(self) -> redis_lib.Redis | None:
        if self._redis is None:
            try:
                self._redis = redis_lib.from_url(settings.redis_url, socket_connect_timeout=2)
            except Exception:
                return None
        return self._redis

    def _get_db(self) -> sqlite3.Connection:
        return init_db(self._db_path)

    def start(self) -> None:
        self._running = True
        self._consume_loop()

    def stop(self) -> None:
        self._running = False
        self.flush()

    def _consume_loop(self) -> None:
        r = self._get_redis()
        if r is None:
            logger.error("No Redis available for KG writer, facts will not be consumed")
            return

        last_id = "0"
        last_flush = time.monotonic()
        while self._running:
            try:
                raw = r.xread({"facts": last_id}, count=10, block=2000)
            except Exception:
                time.sleep(1)
                continue

            for entry in raw:
                if not isinstance(entry, (list, tuple)) or len(entry) < 2:
                    continue
                messages = entry[1]
                for msg_entry in messages:
                    if not isinstance(msg_entry, (list, tuple)) or len(msg_entry) < 2:
                        continue
                    msg_id, msg_data = msg_entry
                    last_id = msg_id
                    if isinstance(msg_data, dict):
                        self._process_message(msg_data)

            if self._buffer:
                elapsed = time.monotonic() - last_flush
                if len(self._buffer) >= self.BATCH_SIZE or elapsed >= 2.0:
                    self.flush()
                    last_flush = time.monotonic()

    def _process_message(self, msg_data: dict[bytes, bytes]) -> None:
        try:
            raw_data: Any = msg_data.get(b"data", b"{}")
            data = json.loads(raw_data) if isinstance(raw_data, (bytes, str)) else raw_data

            ik: str = data.get("idempotency_key", "")
            if ik:
                conn = self._get_db()
                try:
                    existing = conn.execute(
                        "SELECT 1 FROM processed_keys WHERE key_hash = ?",
                        (ik,),
                    ).fetchone()
                    if existing is not None:
                        return
                    conn.execute(
                        "INSERT OR IGNORE INTO processed_keys (key_hash, created_at) VALUES (?, ?)",
                        (ik, time.time()),
                    )
                    conn.commit()
                finally:
                    conn.close()

            task_id: str = data.get("task_id", "unknown")
            facts_list: list[dict[str, Any]] = (
                data.get("facts", [data]) if isinstance(data, dict) else []
            )
            for fact in facts_list:
                fact["task_id"] = fact.get("task_id", task_id)
                with self._lock:
                    self._buffer.append(fact)
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning("Invalid fact message", extra={"error": str(exc)})

    def flush(self) -> None:
        if not self._buffer:
            return

        with self._lock:
            batch = self._buffer[:]
            self._buffer = []

        try:
            conn = self._get_db()
            cursor = conn.cursor()

            inserted = 0
            for fact in batch:
                fact_type: Any = fact.get("type", fact.get("__type__", ""))
                if fact_type not in ("entity", "claim", "source"):
                    if "statement" in fact:
                        fact_type = "claim"
                    elif "url" in fact:
                        fact_type = "source"
                    elif "name" in fact:
                        fact_type = "entity"

                task_id: str = fact.get("task_id", "unknown")
                if fact_type == "entity":
                    cursor.execute(
                        "INSERT INTO entities "
                        "(name, type, description, confidence, attributes, task_id) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            fact.get("name", "unknown"),
                            fact.get("type", "unknown"),
                            fact.get("description"),
                            fact.get("confidence", 0.5),
                            json.dumps(fact.get("attributes", {})),
                            task_id,
                        ),
                    )
                    inserted += 1
                elif fact_type == "claim":
                    cursor.execute(
                        "INSERT INTO claims "
                        "(statement, confidence, entity_id, attribute, source_urls, task_id) "
                        "VALUES (?, ?, (SELECT id FROM entities WHERE name = ? LIMIT 1), ?, ?, ?)",
                        (
                            fact.get("statement", ""),
                            fact.get("confidence", 0.5),
                            fact.get("entity_name"),
                            fact.get("attribute"),
                            json.dumps(fact.get("source_urls", [])),
                            task_id,
                        ),
                    )
                    inserted += 1
                elif fact_type == "source":
                    cursor.execute(
                        "INSERT INTO sources "
                        "(url, title, content_hash, credibility_score, task_id) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (
                            fact.get("url", ""),
                            fact.get("title"),
                            fact.get("content_hash"),
                            fact.get("credibility_score", 0.5),
                            task_id,
                        ),
                    )
                    inserted += 1

            conn.commit()
            conn.close()
            if inserted:
                logger.info("KG writer flushed", extra={"inserted": inserted, "task_id": task_id})
        except sqlite3.Error as exc:
            logger.error("KG write failed", extra={"error": str(exc), "batch_size": len(batch)})
            self._buffer.extend(batch)
