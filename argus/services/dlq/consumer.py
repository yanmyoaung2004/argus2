from __future__ import annotations

import json
import logging
import sqlite3
import time
from typing import Any

import redis as redis_lib
from tenacity import retry, stop_after_attempt, wait_exponential

from argus.services.knowledge_graph.schema import init_db
from argus.shared.config import settings

logger = logging.getLogger(__name__)

MAX_REQUEUES = 3
REQUEUE_DELAYS = [5, 30, 120]


class DLQConsumer:
    STREAM = "dlq"
    MAX_MESSAGES_PER_READ = 10
    ALERT_THRESHOLD = 100

    def __init__(
        self,
        redis_client: redis_lib.Redis | None = None,
        db_path: str | None = None,
    ) -> None:
        self._redis = redis_client
        self._db_path = db_path or settings.sqlite_path
        self._running = False

    def _get_db(self) -> sqlite3.Connection:
        return init_db(self._db_path)

    def _load_cursor(self) -> str:
        try:
            conn = self._get_db()
            row = conn.execute(
                "SELECT last_id FROM stream_cursors WHERE stream_name = 'dlq'"
            ).fetchone()
            conn.close()
            if row:
                return row[0]
        except Exception:
            pass
        return "0"

    def _save_cursor(self, last_id: str) -> None:
        try:
            conn = self._get_db()
            conn.execute(
                "INSERT OR REPLACE INTO stream_cursors (stream_name, last_id) VALUES ('dlq', ?)",
                (last_id,),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

    def _get_redis(self) -> redis_lib.Redis | None:
        if self._redis is None:
            try:
                self._redis = redis_lib.from_url(settings.redis_url, socket_connect_timeout=2)
            except Exception:
                return None
        return self._redis

    def start(self) -> None:
        self._running = True
        self._consume_loop()

    def stop(self) -> None:
        self._running = False

    def push_to_dlq(self, message: dict[str, Any], reason: str) -> str | None:
        r = self._get_redis()
        if r is None:
            logger.warning("No Redis, cannot push to DLQ")
            return None
        try:
            entry = {
                "original_message": json.dumps(message),
                "reason": reason,
                "failed_at": str(time.time()),
                "requeue_count": "0",
            }
            msg_id = r.xadd(self.STREAM, entry, maxlen=settings.redis_stream_maxlen)  # type: ignore[arg-type]
            dlq_len = r.xlen(self.STREAM)
            if dlq_len > self.ALERT_THRESHOLD:
                logger.warning(
                    "DLQ length exceeds threshold",
                    extra={"dlq_length": dlq_len, "threshold": self.ALERT_THRESHOLD},
                )
            return str(msg_id) if msg_id else None
        except Exception as exc:
            logger.error("Failed to push to DLQ", extra={"error": str(exc)})
            return None

    def _consume_loop(self) -> None:
        r = self._get_redis()
        if r is None:
            logger.error("No Redis available for DLQ consumer")
            return

        last_id = self._load_cursor()
        cursor_save_counter = 0
        while self._running:
            try:
                raw: list[Any] = list(
                r.xread({self.STREAM: last_id}, count=self.MAX_MESSAGES_PER_READ, block=5000)
            )
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
                    self._process_dead_message(msg_id, msg_data)

            cursor_save_counter += 1
            if cursor_save_counter >= 20:
                self._save_cursor(last_id)
                cursor_save_counter = 0

    def _process_dead_message(self, msg_id: bytes, msg_data: dict[bytes, bytes]) -> None:
        r = self._get_redis()
        if r is None:
            return

        try:
            raw_reason = msg_data.get(b"reason", b"").decode("utf-8")
            raw_message = msg_data.get(b"original_message", b"{}").decode("utf-8")
            raw_requeue = msg_data.get(b"requeue_count", b"0").decode("utf-8")
        except (UnicodeDecodeError, ValueError):
            logger.warning("Malformed DLQ message", extra={"msg_id": str(msg_id)})
            return

        requeue_count = int(raw_requeue) if raw_requeue.isdigit() else 0

        try:
            original_message: dict[str, Any] = json.loads(raw_message)
        except json.JSONDecodeError:
            logger.warning("Cannot parse original message in DLQ", extra={"msg_id": str(msg_id)})
            return

        if requeue_count < MAX_REQUEUES and requeue_count < len(REQUEUE_DELAYS):
            delay = REQUEUE_DELAYS[requeue_count]
            target_stream = msg_data.get(b"target_stream", b"tasks").decode("utf-8")
            logger.info(
                "Re-queuing dead message",
                extra={
                    "msg_id": str(msg_id),
                    "requeue": requeue_count + 1,
                    "target": target_stream,
                    "delay_seconds": delay,
                },
            )
            time.sleep(delay)
            try:
                r.xadd(target_stream, original_message, maxlen=settings.redis_stream_maxlen)  # type: ignore[arg-type]
            except Exception as exc:
                logger.error("Failed to re-queue message", extra={"error": str(exc)})
        else:
            logger.warning(
                "Dead message archived (max requeues reached)",
                extra={
                    "msg_id": str(msg_id),
                    "requeue_count": requeue_count,
                    "reason": raw_reason,
                },
            )
            self._archive_message(msg_id)

    @retry(
        stop=stop_after_attempt(settings.llm_retry_max_attempts),
        wait=wait_exponential(
            multiplier=settings.llm_retry_min_wait_seconds,
            max=settings.llm_retry_max_wait_seconds,
        ),
    )
    def _archive_message(self, msg_id: bytes) -> None:
        r = self._get_redis()
        if r is None:
            return
        try:
            r.xdel(self.STREAM, msg_id)
        except Exception as exc:
            logger.error("Failed to archive DLQ message", extra={"error": str(exc)})
