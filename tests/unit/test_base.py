from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from argus.services.agents.base import BaseAgent, BudgetError
from argus.shared.models import AgentType, Fact, LLMProviderType, TaskStep


class FakeAgent(BaseAgent):
    async def run(self, step: TaskStep) -> list[Fact]:
        return []


@pytest.fixture
def step() -> TaskStep:
    return TaskStep(
        id=1, type="discover", goal="test", agent=AgentType.SCOUT,
        status="running", task_id="task-1", query="test query",
    )


class TestBaseAgent:
    def test_init_defaults(self) -> None:
        agent = FakeAgent(AgentType.SCOUT)
        assert agent.agent_type == AgentType.SCOUT
        assert agent._router is not None
        assert agent._idempotency is None
        assert agent._cost_tracker is None

    def test_init_with_deps(self) -> None:
        router = MagicMock()
        idem = MagicMock()
        tracker = MagicMock()
        agent = FakeAgent(AgentType.DEEP_DIVE, router=router, idempotency=idem, cost_tracker=tracker)
        assert agent._router is router
        assert agent._idempotency is idem
        assert agent._cost_tracker is tracker

    def test_check_budget_no_tracker(self) -> None:
        agent = FakeAgent(AgentType.SCOUT)
        agent._check_budget(10.0)
        assert True

    def test_check_budget_approved(self) -> None:
        tracker = MagicMock()
        tracker.approve_call.return_value = True
        agent = FakeAgent(AgentType.SCOUT, cost_tracker=tracker)
        agent._check_budget(0.01)
        tracker.approve_call.assert_called_once_with(0.01)
        tracker.check_budget.assert_called_once()

    def test_check_budget_rejected(self) -> None:
        tracker = MagicMock()
        tracker.approve_call.return_value = False
        tracker._budget_limit = 0.50
        agent = FakeAgent(AgentType.SCOUT, cost_tracker=tracker)
        with pytest.raises(BudgetError):
            agent._check_budget(0.02)

    def test_record_cost_no_tracker(self) -> None:
        agent = FakeAgent(AgentType.SCOUT)
        agent._record_cost(0.01)
        assert True

    def test_record_cost_with_tracker(self) -> None:
        tracker = MagicMock()
        agent = FakeAgent(AgentType.SCOUT, cost_tracker=tracker)
        agent._record_cost(0.01, category="llm")
        tracker.record_cost.assert_called_once_with(0.01, category="llm")
        tracker.check_budget.assert_called_once()

    def test_emit_facts_returns_fact_list(self, step: TaskStep) -> None:
        agent = FakeAgent(AgentType.SCOUT)
        facts = [{"type": "entity", "name": "Test"}]
        result = agent._emit_facts(step, facts)
        assert len(result) == 1
        assert isinstance(result[0], Fact)
        assert result[0].task_id == "task-1"
        assert result[0].step_id == 1
        assert result[0].agent == AgentType.SCOUT
        from argus.shared.models import Entity
        assert isinstance(result[0].facts[0], Entity)
        assert result[0].facts[0].name == "Test"

    def test_emit_facts_with_idempotency_skips_duplicate(self, step: TaskStep) -> None:
        idem = MagicMock()
        idem.is_processed.return_value = True
        agent = FakeAgent(AgentType.SCOUT, idempotency=idem)
        result = agent._emit_facts(step, [{"type": "entity"}])
        assert result == []

    def test_check_circuit_breaker(self) -> None:
        agent = FakeAgent(AgentType.SCOUT)
        result = agent._check_circuit_breaker(LLMProviderType.OLLAMA)
        assert isinstance(result, bool)
