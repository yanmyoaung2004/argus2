from __future__ import annotations

import json
import logging
from typing import Any

from argus.llm.router import CostAwareRouter
from argus.shared.models import AgentType, ResearchPlan, TaskStep, TaskStepStatus, TaskType

logger = logging.getLogger(__name__)


class LLMPlanner:
    def __init__(self, router: CostAwareRouter | None = None) -> None:
        self._router = router or CostAwareRouter()

    def decompose(self, query: str) -> ResearchPlan:
        from argus.llm.prompts.planner import DECOMPOSE_SYSTEM, decompose_query

        try:
            response_text, provider, cost = self._router.complete(
                task_type="planning",
                prompt=decompose_query(query),
                system_prompt=DECOMPOSE_SYSTEM,
            )
        except RuntimeError:
            logger.warning("LLM planning failed, falling back to simple plan")
            return self._fallback_plan(query)

        try:
            parsed: dict[str, Any] = json.loads(response_text)
            steps_raw: list[dict[str, Any]] = parsed.get("steps", [])
            if not steps_raw:
                return self._fallback_plan(query)

            steps: list[TaskStep] = []
            for i, s in enumerate(steps_raw, start=1):
                task_type = TaskType(s.get("type", "discover"))
                agent_map = {
                    TaskType.DISCOVER: AgentType.SCOUT,
                    TaskType.EXTRACT: AgentType.DEEP_DIVE,
                    TaskType.VERIFY: AgentType.VERIFICATION,
                    TaskType.SYNTHESIZE: AgentType.SYNTHESIS,
                }
                steps.append(TaskStep(
                    id=i,
                    type=task_type,
                    goal=s.get("goal", "Research step"),
                    agent=agent_map.get(task_type, AgentType.SCOUT),
                    status=TaskStepStatus.PENDING,
                    depends_on=s.get("depends_on", [i - 1] if i > 1 else []),
                ))

            return ResearchPlan(
                steps=steps,
                estimated_sources=parsed.get("estimated_sources", len(steps) * 10),
                estimated_time_minutes=parsed.get("estimated_time_minutes", len(steps) * 5),
            )
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
            logger.warning("LLM plan parse failed", extra={"error": str(exc)})
            return self._fallback_plan(query)

    @staticmethod
    def _fallback_plan(query: str) -> ResearchPlan:
        query_preview = query[:60]
        steps = [
            TaskStep(
                id=1, type=TaskType.DISCOVER,
                goal=f"Research {query_preview}",
                agent=AgentType.SCOUT,
                status=TaskStepStatus.PENDING,
                depends_on=[],
            ),
            TaskStep(
                id=2, type=TaskType.VERIFY,
                goal=f"Verify claims about {query_preview}",
                agent=AgentType.VERIFICATION,
                status=TaskStepStatus.PENDING,
                depends_on=[1],
            ),
        ]
        return ResearchPlan(steps=steps, estimated_sources=20, estimated_time_minutes=10)
