from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

from argus.services.agents._parse import extract_json_object
from argus.services.agents.base import BaseAgent
from argus.shared.models import AgentType, Fact, TaskStep

logger = logging.getLogger(__name__)

MAX_CLAIMS_PER_ENTITY = 10


class VerificationAgent(BaseAgent):
    def __init__(
        self,
        router: Any = None,
        idempotency: Any = None,
        cost_tracker: Any = None,
    ) -> None:
        super().__init__(
            AgentType.VERIFICATION,
            router=router,
            idempotency=idempotency,
            cost_tracker=cost_tracker,
        )

    async def run(self, step: TaskStep) -> list[Fact]:
        logger.info("VerificationAgent running", extra={"step_id": step.id, "goal": step.goal})

        self._query: str = step.query or ""

        claims = self._get_claims_for_task(step.task_id)
        if not claims:
            claims = self._wait_for_claims(task_id=step.task_id, _step_id=step.id)
            if not claims:
                logger.info("No claims to verify after waiting", extra={"step_id": step.id})
                return []

        grouped: dict[str, list[dict[str, Any]]] = {}
        for claim in claims:
            entity_name = claim.get("entity_name", "unknown")
            if entity_name not in grouped:
                grouped[entity_name] = []
            grouped[entity_name].append(claim)

        conflict_facts: list[dict[str, Any]] = []

        for _entity_name, entity_claims in grouped.items():
            if len(entity_claims) < 2:
                continue

            if len(entity_claims) > MAX_CLAIMS_PER_ENTITY:
                logger.warning(
                    "Truncating entity claims for conflict check",
                    extra={
                        "entity": _entity_name,
                        "total": len(entity_claims),
                        "cap": MAX_CLAIMS_PER_ENTITY,
                    },
                )
                entity_claims = entity_claims[:MAX_CLAIMS_PER_ENTITY]

            for i in range(len(entity_claims)):
                for j in range(i + 1, len(entity_claims)):
                    a = entity_claims[i]
                    b = entity_claims[j]

                    if a.get("attribute") != b.get("attribute"):
                        continue

                    self._check_budget(estimated_cost=0.01)
                    result = self._check_conflict(a, b)
                    if result is not None:
                        conflict_facts.append(result)

        if not conflict_facts:
            return []

        return self._emit_facts(step, conflict_facts)

    def _wait_for_claims(self, task_id: str, _step_id: int) -> list[dict[str, Any]]:
        import time

        import redis as redis_lib

        from argus.shared.config import settings

        try:
            r = redis_lib.from_url(settings.redis_url, socket_connect_timeout=2)
        except Exception:
            time.sleep(5)
            return self._get_claims_for_task(task_id)

        from argus.shared.config import settings as _s
        deadline = time.time() + _s.agent_wait_seconds
        last_id = "0"
        stream = f"progress:{task_id}"
        try:
            while time.time() < deadline:
                remaining = int((deadline - time.time()) * 1000)
                if remaining <= 0:
                    break
                try:
                    raw = r.xread({stream: last_id}, count=10, block=min(remaining, 5000))
                except Exception:
                    time.sleep(1)
                    continue
                if raw:
                    for entry in raw:
                        if not isinstance(entry, (list, tuple)) or len(entry) < 2:
                            continue
                        for msg_entry in entry[1]:
                            if isinstance(msg_entry, (list, tuple)) and len(msg_entry) >= 2:
                                last_id = msg_entry[0]
                claims = self._get_claims_for_task(task_id)
                if claims:
                    return claims
            return []
        finally:
            r.close()

    def _get_claims_for_task(self, task_id: str) -> list[dict[str, Any]]:
        try:
            from argus.shared.config import settings
            conn = sqlite3.connect(settings.sqlite_path)
            rows = conn.execute(
                "SELECT c.statement, c.confidence, c.source_urls, "
                "COALESCE(e.name, 'unknown') AS entity_name, c.attribute "
                "FROM claims c LEFT JOIN entities e ON c.entity_id = e.id "
                "WHERE c.task_id = ? ORDER BY c.rowid",
                (task_id,),
            ).fetchall()
            conn.close()
            results: list[dict[str, Any]] = []
            for row in rows:
                source_urls_raw = row[2]
                source_urls: list[str] = []
                if isinstance(source_urls_raw, str):
                    try:
                        source_urls = json.loads(source_urls_raw)
                    except (json.JSONDecodeError, TypeError):
                        source_urls = []
                results.append({
                    "statement": row[0],
                    "confidence": row[1],
                    "source_urls": source_urls,
                    "entity_name": row[3],
                    "attribute": row[4],
                })
            return results
        except sqlite3.Error as exc:
            logger.warning("Failed to query claims for verification", extra={"error": str(exc)})
            return []

    def _check_conflict(
        self,
        claim_a: dict[str, Any],
        claim_b: dict[str, Any],
    ) -> dict[str, Any] | None:
        query_hint = self._query
        query_context = f"\nResearch context: {query_hint}\n" if query_hint else ""
        prompt = (
            f"Determine if the following two claims are contradictory, "
            f"supportive, or unrelated. Return a JSON object with keys: "
            f"relationship (contradictory/supportive/unrelated), reason."
            f"{query_context}"
            f"Claim A: {claim_a.get('statement', '')}\n"
            f"Source A: {claim_a.get('source_urls', [])}\n\n"
            f"Claim B: {claim_b.get('statement', '')}\n"
            f"Source B: {claim_b.get('source_urls', [])}"
        )

        try:
            text, provider, cost = self._router.complete(
                task_type="verification",
                prompt=prompt,
            )
            self._record_cost(cost, category="llm")

            result: dict[str, Any] = extract_json_object(text)
            relationship = result.get("relationship", "unrelated")
            reason = result.get("reason", "")

            return {
                "claim_a": claim_a.get("statement", ""),
                "claim_b": claim_b.get("statement", ""),
                "relationship": relationship,
                "reason": reason,
                "confidence_delta": -0.2 if relationship == "contradictory" else 0.1,
            }
        except (RuntimeError, json.JSONDecodeError, TypeError) as exc:
            logger.warning("Conflict check failed", extra={"error": str(exc)})
            return None
