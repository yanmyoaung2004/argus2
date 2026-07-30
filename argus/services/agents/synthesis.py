from __future__ import annotations

import json
import logging
import sqlite3
import time
from difflib import SequenceMatcher
from typing import Any

import redis as redis_lib

from argus.services.agents.base import BaseAgent
from argus.services.knowledge_graph.schema import init_db
from argus.shared.config import settings
from argus.shared.models import AgentType, Entity, Fact, TaskStep

logger = logging.getLogger(__name__)


class SynthesisAgent(BaseAgent):
    def __init__(
        self,
        router: Any = None,
        idempotency: Any = None,
        cost_tracker: Any = None,
        db_path: str | None = None,
        redis_client: redis_lib.Redis | None = None,
    ) -> None:
        super().__init__(
            AgentType.SYNTHESIS,
            router=router,
            idempotency=idempotency,
            cost_tracker=cost_tracker,
        )
        self._db_path = db_path or settings.sqlite_path
        self._redis = redis_client
        self._cost_tracker = cost_tracker
        self._running = False
        self._edge_check_counter = 0
        self._entity_buffer: list[tuple[Entity, str]] = []
        self._batch_depth = 0

    def _get_redis(self) -> redis_lib.Redis | None:
        if self._redis is None:
            try:
                self._redis = redis_lib.from_url(settings.redis_url, socket_connect_timeout=2)
            except Exception:
                return None
        return self._redis

    def _get_db(self) -> sqlite3.Connection:
        return init_db(self._db_path)

    async def run(self, step: TaskStep) -> list[Fact]:
        logger.info("SynthesisAgent running", extra={"step_id": step.id, "goal": step.goal})

        task_id = step.task_id
        query = getattr(step, "query", "")

        conn = self._get_db()
        try:
            entities = conn.execute(
                "SELECT name, type, description, confidence FROM entities WHERE task_id = ?",
                (task_id,),
            ).fetchall()

            claim_rows = conn.execute(
                "SELECT statement, confidence, entity_name, attribute "
                "FROM claims WHERE task_id = ? ORDER BY confidence DESC",
                (task_id,),
            ).fetchall()
        finally:
            conn.close()

        if not entities and not claim_rows:
            logger.info("No data to synthesize", extra={"task_id": task_id})
            return []

        synthesis = self._generate_synthesis(query, entities, claim_rows)
        if synthesis is None:
            return []

        fact_data = {
            "type": "synthesis",
            "task_id": task_id,
            "content": synthesis,
            "entity_count": len(entities),
            "claim_count": len(claim_rows),
        }

        return self._emit_facts(step, [fact_data])

    def _generate_synthesis(
        self,
        query: str,
        entities: list[Any],
        claims: list[Any],
    ) -> str | None:
        from argus.llm.prompts.synthesis import generate_synthesis as _synthesis
        prompt = _synthesis(query, entities, claims)

        try:
            self._check_budget(estimated_cost=0.02)
            text, provider, cost = self._router.complete(
                task_type="synthesis",
                prompt=prompt,
            )
            self._record_cost(cost, category="llm")
            return text.strip()
        except (RuntimeError, Exception) as exc:
            logger.warning("Synthesis generation failed", extra={"error": str(exc)})
            return None

    def start(self) -> None:
        self._running = True
        self._consume_loop()

    def stop(self) -> None:
        self._running = False

    def _load_cursor(self) -> str:
        try:
            conn = self._get_db()
            row = conn.execute(
                "SELECT last_id FROM stream_cursors WHERE stream_name = 'facts'"
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
                "INSERT OR REPLACE INTO stream_cursors (stream_name, last_id) VALUES ('facts', ?)",
                (last_id,),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

    def _consume_loop(self) -> None:
        r = self._get_redis()
        if r is None:
            logger.error("No Redis available for synthesis agent")
            return

        last_id = self._load_cursor()
        cursor_save_counter = 0
        while self._running:
            try:
                raw = r.xread({"facts": last_id}, count=10, block=2000)
            except Exception:
                time.sleep(1)
                continue

            if raw:
                self._batch_depth += 1
                try:
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
                                self._process_fact(msg_data)
                finally:
                    self._batch_depth -= 1
                    if self._entity_buffer:
                        self._flush_entity_buffer()

            cursor_save_counter += 1
            if cursor_save_counter >= 50:
                self._save_cursor(last_id)
                cursor_save_counter = 0

            self._edge_check_counter += 1
            if self._edge_check_counter >= 50:
                self._edge_check_counter = 0
                conn = self._get_db()
                try:
                    self._ensure_related_edges(conn)
                finally:
                    conn.close()

    def _process_fact(self, msg_data: dict[bytes, bytes]) -> None:
        try:
            raw_data = msg_data.get(b"data", b"{}")
            data = json.loads(raw_data) if isinstance(raw_data, (bytes, str)) else {}
            facts = data.get("facts", [data]) if isinstance(data, dict) else []
            for fact in facts:
                if isinstance(fact, dict):
                    self._process_fact_item(fact)
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning("Invalid fact in synthesis", extra={"error": str(exc)})

    def _process_fact_item(self, fact: dict[str, Any]) -> None:
        fact_type = fact.get("type", fact.get("__type__", ""))
        if not fact_type and "name" in fact:
            fact_type = "entity"
        if fact_type != "entity":
            return

        entity = Entity(
            name=fact.get("name", "unknown"),
            type=fact.get("type", "unknown"),
            description=fact.get("description"),
            confidence=fact.get("confidence", 0.5),
            attributes=fact.get("attributes", {}),
        )
        task_id = fact.get("task_id", "unknown")

        if self._batch_depth > 0:
            self._entity_buffer.append((entity, task_id))
        else:
            self._flush_single(entity, task_id)

    def _process_entity(self, conn: sqlite3.Connection, entity: Entity, task_id: str) -> None:
        match = self._find_match(conn, entity)
        if match is None:
            self._insert_entity(conn, entity, task_id)
        elif match["similarity"] >= settings.merge_threshold:
            self._merge_entity(conn, match["id"], entity, task_id)
        elif match["similarity"] >= settings.llm_merge_threshold:
            should_merge = self._ask_llm(entity.name, match["name"])
            if should_merge:
                self._merge_entity(conn, match["id"], entity, task_id)
            else:
                self._insert_entity(conn, entity, task_id)
        else:
            self._insert_entity(conn, entity, task_id)

    def _flush_single(self, entity: Entity, task_id: str) -> None:
        conn = self._get_db()
        try:
            self._process_entity(conn, entity, task_id)
        finally:
            conn.close()

    def _flush_entity_buffer(self) -> None:
        if not self._entity_buffer:
            return
        batch = self._entity_buffer[:]
        self._entity_buffer = []
        conn = self._get_db()
        try:
            for entity, task_id in batch:
                self._process_entity(conn, entity, task_id)
        finally:
            conn.close()

    def _find_match(self, conn: sqlite3.Connection, entity: Entity) -> dict[str, Any] | None:
        name_lower = entity.name.lower()
        prefix = name_lower[:4]

        candidates = conn.execute(
            "SELECT id, name FROM entities WHERE LOWER(name) LIKE ? ORDER BY id LIMIT 200",
            (f"{prefix}%",),
        ).fetchall()

        if not candidates:
            candidates = conn.execute(
                "SELECT id, name FROM entities ORDER BY id LIMIT 1000"
            ).fetchall()

        best: dict[str, Any] | None = None
        best_score = 0.0

        for row in candidates:
            score = SequenceMatcher(None, name_lower, row[1].lower()).ratio()
            if score > best_score and score >= settings.llm_merge_threshold:
                best_score = score
                best = {"id": row[0], "name": row[1], "similarity": score}

        return best

    def _merge_entity(self, conn: sqlite3.Connection, target_id: int, entity: Entity, task_id: str) -> None:
        existing = conn.execute(
            "SELECT name, type, description, confidence, attributes FROM entities WHERE id = ?",
            (target_id,),
        ).fetchone()
        if existing is None:
            return

        existing_attrs: dict[str, Any] = {}
        try:
            existing_attrs = json.loads(existing[4]) if existing[4] else {}
        except (json.JSONDecodeError, TypeError):
            existing_attrs = {}

        merged_attrs = {**existing_attrs, **entity.attributes}
        merged_confidence = max(existing[3], entity.confidence)
        merged_description = entity.description or existing[2]

        conn.execute(
            "UPDATE entities SET type = CASE WHEN ? != 'unknown' THEN ? ELSE ? END, "
            "description = ?, confidence = ?, "
            "attributes = ?, updated_at = datetime('now') WHERE id = ?",
            (
                entity.type, entity.type, existing[1],
                merged_description,
                merged_confidence,
                json.dumps(merged_attrs),
                target_id,
            ),
        )
        conn.commit()
        logger.info(
            "Merged entity",
            extra={"target_id": target_id, "source_name": entity.name, "task_id": task_id},
        )

    def _insert_entity(self, conn: sqlite3.Connection, entity: Entity, task_id: str) -> None:
        conn.execute(
            "INSERT INTO entities (name, type, description, confidence, attributes, task_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                entity.name,
                entity.type,
                entity.description,
                entity.confidence,
                json.dumps(entity.attributes),
                task_id,
            ),
        )
        conn.commit()

    def _ask_llm(self, name_a: str, name_b: str) -> bool:
        score = SequenceMatcher(None, name_a.lower(), name_b.lower()).ratio()
        if score >= settings.merge_threshold:
            return True
        try:
            from argus.llm.prompts.synthesis import ask_merge as _merge_prompt
            prompt = _merge_prompt(name_a, name_b)
            text, provider, cost = self._router.complete(
                task_type="synthesis",
                prompt=prompt,
            )
            if self._cost_tracker is not None:
                self._cost_tracker.record_cost(cost, category="llm")
            return text.strip().lower().startswith("yes")
        except (RuntimeError, Exception):
            return score >= (settings.merge_threshold + settings.llm_merge_threshold) / 2

    def _ensure_related_edges(self, conn: sqlite3.Connection) -> None:
        cursor = conn.execute(
            """SELECT c1.entity_id AS a, c2.entity_id AS b, COUNT(*) AS cooccur
               FROM claims c1
               JOIN claims c2 ON c1.task_id = c2.task_id AND c1.id < c2.id
               WHERE c1.entity_id IS NOT NULL AND c2.entity_id IS NOT NULL
                 AND c1.entity_id != c2.entity_id
               GROUP BY c1.entity_id, c2.entity_id
               HAVING cooccur >= ?""",
            (settings.edge_cooccur_threshold,),
        )
        added = 0
        for row in cursor.fetchall():
            a_id, b_id, cooccur = row
            existing = conn.execute(
                "SELECT id FROM edges WHERE source_id = ? AND target_id = ? AND relation_type = 'RELATED_TO'",
                (a_id, b_id),
            ).fetchone()
            if existing is None:
                weight = min(cooccur / 10.0, 1.0)
                conn.execute(
                    "INSERT INTO edges (source_id, target_id, relation_type, weight, task_id) "
                    "VALUES (?, ?, 'RELATED_TO', ?, (SELECT task_id FROM entities WHERE id = ?))",
                    (a_id, b_id, weight, a_id),
                )
                added += 1
        if added:
            conn.commit()
            logger.info("Added RELATED_TO edges", extra={"count": added})
