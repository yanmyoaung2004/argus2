from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from typing import Any

import redis as redis_lib

from argus.services.agents.base import BudgetError
from argus.services.agents.deep_dive import DeepDiveAgent
from argus.services.agents.scout import ScoutAgent
from argus.services.agents.synthesis import SynthesisAgent
from argus.services.agents.verification import VerificationAgent
from argus.services.dlq.consumer import DLQConsumer
from argus.services.heartbeat import HeartbeatWriter
from argus.services.tools.cost_tracker import BudgetExceededError
from argus.shared.config import settings
from argus.shared.models import AgentType, TaskStep, TaskStepStatus

logger = logging.getLogger(__name__)

AGENT_MAP: dict[AgentType, type] = {
    AgentType.SCOUT: ScoutAgent,
    AgentType.DEEP_DIVE: DeepDiveAgent,
    AgentType.VERIFICATION: VerificationAgent,
    AgentType.SYNTHESIS: SynthesisAgent,
}


class AgentRunner:
    CONSUMER_GROUP = settings.redis_consumer_group

    def __init__(
        self,
        agent_type: AgentType,
        redis_client: redis_lib.Redis | None = None,
        concurrency: int = 1,
    ) -> None:
        self.agent_type = agent_type
        self.STREAM = f"tasks:{agent_type.value}"
        self._redis = redis_client
        self._concurrency = concurrency
        self._running = False
        self._dlq = DLQConsumer(redis_client=redis_client)
        self._heartbeat = HeartbeatWriter(agent_id=agent_type.value, redis_client=redis_client)
        self._loop = asyncio.new_event_loop()
        agent_class = AGENT_MAP.get(agent_type)
        if agent_class is None:
            raise ValueError(f"Unknown agent type: {agent_type}")
        self._agent: Any = agent_class()

    def _get_redis(self) -> redis_lib.Redis | None:
        if self._redis is None:
            try:
                self._redis = redis_lib.from_url(settings.redis_url, socket_connect_timeout=2)
            except Exception:
                return None
        return self._redis

    def _ensure_group(self) -> None:
        r = self._get_redis()
        if r is None:
            return
        try:
            r.xgroup_create(self.STREAM, self.CONSUMER_GROUP, id="0", mkstream=True)
        except redis_lib.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                logger.warning("Consumer group error", extra={"error": str(exc)})

    def start(self) -> None:
        self._ensure_group()
        self._running = True
        self._heartbeat.start()
        consumer_name = f"{self.agent_type.value}-worker-{int(time.time())}"
        logger.info(
            "Agent runner starting",
            extra={
                "agent": self.agent_type.value,
                "consumer": consumer_name,
                "concurrency": self._concurrency,
            },
        )
        self._consume_loop(consumer_name)

    def stop(self) -> None:
        self._running = False
        self._heartbeat.stop()
        self._loop.close()

    def _consume_loop(self, consumer_name: str) -> None:
        retry_delay = 1.0
        while self._running:
            r = self._get_redis()
            if r is None:
                logger.warning(
                    "No Redis for agent runner, retrying",
                    extra={"agent": self.agent_type.value, "retry_delay": retry_delay},
                )
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 30.0)
                continue
            retry_delay = 1.0

            processed = self._process_once(consumer_name, r)
            if not processed:
                time.sleep(0.1)

    def _process_once(self, consumer_name: str, r: Any = None) -> bool:
        if r is None:
            r = self._get_redis()
            if r is None:
                return False

        try:
            raw = r.xreadgroup(
                self.CONSUMER_GROUP,
                consumer_name,
                {self.STREAM: ">"},
                count=self._concurrency,
                block=2000,
            )
            if raw is None:
                return False
        except Exception:
            return False

        found = False
        for entry in raw:
            if not isinstance(entry, (list, tuple)) or len(entry) < 2:
                continue
            messages = entry[1]
            for msg_entry in messages:
                if not isinstance(msg_entry, (list, tuple)) or len(msg_entry) < 2:
                    continue
                msg_id, msg_data = msg_entry
                if not isinstance(msg_data, dict):
                    continue
                self._process_message(msg_id, msg_data, consumer_name)
                found = True
        return found

    def _msg_matches_agent(self, msg_data: dict[bytes, bytes]) -> bool:
        try:
            return msg_data.get(b"agent", b"").decode("utf-8") == self.agent_type.value
        except UnicodeDecodeError:
            return False

    def _parse_msg(self, msg_data: dict[bytes, bytes]) -> dict[str, Any] | None:
        try:
            return {
                "idempotency_key": msg_data.get(b"idempotency_key", b"").decode("utf-8"),
                "task_id": msg_data.get(b"task_id", b"").decode("utf-8"),
                "step_id": int(msg_data.get(b"step_id", b"0").decode("utf-8")),
                "type": msg_data.get(b"type", b"").decode("utf-8"),
                "goal": msg_data.get(b"goal", b"").decode("utf-8"),
                "query": msg_data.get(b"query", b"").decode("utf-8"),
                "depends_on": json.loads(
                    msg_data.get(b"depends_on", b"[]").decode("utf-8")
                ),
            }
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
            logger.warning("Failed to parse task message", extra={"error": str(exc)})
            return None

    def _process_message(
        self, msg_id: bytes, msg_data: dict[bytes, bytes], consumer_name: str
    ) -> None:
        r = self._get_redis()
        if r is None:
            return

        if not self._msg_matches_agent(msg_data):
            self._ack_message(msg_id, consumer_name)
            return

        parsed = self._parse_msg(msg_data)
        if parsed is None:
            self._ack_message(msg_id, consumer_name)
            return

        step = TaskStep(
            id=parsed["step_id"],
            type=parsed["type"],
            goal=parsed["goal"],
            agent=self.agent_type,
            status=TaskStepStatus.RUNNING,
            depends_on=parsed.get("depends_on", []),
            result={},
            task_id=parsed.get("task_id", ""),
            query=parsed.get("query", ""),
        )

        try:
            facts = self._loop.run_until_complete(self._agent.run(step))
            self._publish_facts(facts)
            self._emit_progress(parsed["task_id"], step.id, "step_complete", {
                "facts_count": len(facts),
            })
            self._ack_message(msg_id, consumer_name)
        except BudgetError as exc:
            logger.warning(
                "Agent budget limit reached",
                extra={"agent": self.agent_type.value, "step_id": step.id, "error": str(exc)},
            )
            self._dlq.push_to_dlq(parsed, f"BudgetError: {exc}")
            self._emit_progress(parsed["task_id"], step.id, "budget_exceeded", {
                "error": str(exc),
            })
            self._ack_message(msg_id, consumer_name)
        except BudgetExceededError as exc:
            logger.warning(
                "Agent budget exceeded",
                extra={"agent": self.agent_type.value, "step_id": step.id, "error": str(exc)},
            )
            self._dlq.push_to_dlq(parsed, f"BudgetExceededError: {exc}")
            self._emit_progress(parsed["task_id"], step.id, "budget_exceeded", {
                "error": str(exc),
            })
            self._ack_message(msg_id, consumer_name)
        except Exception as exc:
            logger.error(
                "Agent execution failed",
                extra={"agent": self.agent_type.value, "step_id": step.id, "error": str(exc)},
            )
            self._dlq.push_to_dlq(parsed, str(exc))

    def _publish_facts(self, facts: list[Any]) -> None:
        r = self._get_redis()
        if r is None:
            return
        for fact_batch in facts:
            try:
                raw = fact_batch.model_dump() if hasattr(fact_batch, "model_dump") else fact_batch
                data = json.dumps(raw, default=str)
                r.xadd(
                    "facts",
                    {"data": data},
                    maxlen=settings.redis_stream_maxlen,
                )
            except Exception:
                logger.warning("Failed to publish fact batch", exc_info=True)

    def _emit_progress(
        self, task_id: str, step_id: int, event_type: str, data: dict[str, Any]
    ) -> None:
        r = self._get_redis()
        if r is None:
            return
        try:
            event_data = {
                "type": event_type,
                "step_id": step_id,
                "data": json.dumps(data),
            }
            r.xadd(
                f"progress:{task_id}",
                event_data,
                maxlen=settings.redis_stream_maxlen,
            )

            if event_type == "step_complete":
                with contextlib.suppress(Exception):
                    r.publish(f"task_events:{task_id}", json.dumps({"step_id": step_id}))
        except Exception as exc:
            logger.warning("Failed to emit progress", extra={"error": str(exc)})

    def _ack_message(self, msg_id: bytes, _consumer_name: str) -> None:
        r = self._get_redis()
        if r is None:
            return
        with contextlib.suppress(Exception):
            r.xack(self.STREAM, self.CONSUMER_GROUP, msg_id)
