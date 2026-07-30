from __future__ import annotations

from uuid import UUID

from argus.shared.models import (
    AgentType,
    Claim,
    ConfidenceLevel,
    ConflictEdge,
    Entity,
    Fact,
    LLMProviderType,
    ResearchPlan,
    ResearchStatus,
    ResearchTask,
    Source,
    TaskStep,
    TaskStepStatus,
    TaskType,
)


class TestEnums:
    def test_agent_type_values(self) -> None:
        assert AgentType.SCOUT == "scout"
        assert AgentType.DEEP_DIVE == "deep_dive"
        assert AgentType.VERIFICATION == "verification"
        assert AgentType.SYNTHESIS == "synthesis"

    def test_task_type_values(self) -> None:
        assert TaskType.DISCOVER == "discover"
        assert TaskType.SYNTHESIZE == "synthesize"

    def test_research_status_values(self) -> None:
        assert ResearchStatus.PENDING == "pending"
        assert ResearchStatus.DONE == "done"
        assert ResearchStatus.FAILED == "failed"

    def test_llm_provider_type_values(self) -> None:
        assert LLMProviderType.OLLAMA == "ollama"
        assert LLMProviderType.GROQ == "groq"
        assert LLMProviderType.OPENAI == "openai"

    def test_confidence_level(self) -> None:
        assert ConfidenceLevel.HIGH == "high"
        assert ConfidenceLevel.LOW == "low"


class TestEntity:
    def test_defaults(self) -> None:
        e = Entity(name="Test", type="company")
        assert e.name == "Test"
        assert e.type == "company"
        assert e.description is None
        assert e.confidence == 0.5
        assert e.attributes == {}


class TestClaim:
    def test_defaults(self) -> None:
        c = Claim(statement="test claim")
        assert c.statement == "test claim"
        assert c.confidence == 0.5
        assert c.source_urls == []


class TestSource:
    def test_defaults(self) -> None:
        s = Source(url="https://a.com")
        assert s.url == "https://a.com"
        assert s.title is None


class TestConflictEdge:
    def test_defaults(self) -> None:
        e = ConflictEdge(claim_a="claim1", claim_b="claim2", relationship="contradictory", reason="conflict")
        assert e.relationship == "contradictory"
        assert e.confidence_delta == 0.0
        assert e.reason == "conflict"


class TestTaskStep:
    def test_minimal(self) -> None:
        s = TaskStep(id=1, type="discover", goal="test", agent="scout", task_id="t1")
        assert s.id == 1
        assert s.status == TaskStepStatus.PENDING

    def test_with_depends_on(self) -> None:
        s = TaskStep(id=2, type="extract", goal="extract", agent="deep_dive", depends_on=[1], task_id="t1")
        assert s.depends_on == [1]


class TestResearchPlan:
    def test_defaults(self) -> None:
        step = TaskStep(id=1, type="discover", goal="test", agent="scout", task_id="t1")
        plan = ResearchPlan(steps=[step])
        assert len(plan.steps) == 1
        assert plan.estimated_sources == 0


class TestResearchTask:
    def test_defaults(self) -> None:
        task = ResearchTask(query="test query")
        assert isinstance(task.task_id, UUID)
        assert task.query == "test query"
        assert task.status == ResearchStatus.PENDING
        assert task.max_sources == 50

    def test_with_plan(self) -> None:
        step = TaskStep(id=1, type="discover", goal="test", agent="scout", task_id="t1")
        plan = ResearchPlan(steps=[step])
        task = ResearchTask(query="q", plan=plan)
        assert task.plan is not None
        assert len(task.plan.steps) == 1


class TestFact:
    def test_defaults(self) -> None:
        f = Fact(
            idempotency_key="ik-1",
            task_id="t1",
            step_id=1,
            agent=AgentType.SCOUT,
            facts=[Entity(name="E1", type="company")],
        )
        assert f.task_id == "t1"
        assert f.agent == AgentType.SCOUT
        assert len(f.facts) == 1
        assert isinstance(f.facts[0], Entity)
