from __future__ import annotations

from argus.llm.profile import (
    StageAssignment,
    StageProfile,
    ALL_STAGES,
    STAGE_LABELS,
)


class TestStageAssignment:
    def test_defaults(self) -> None:
        a = StageAssignment(task_type="scout", provider_type="groq")
        assert a.task_type == "scout"
        assert a.provider_type == "groq"
        assert a.model == ""

    def test_with_model(self) -> None:
        a = StageAssignment(task_type="deep_dive", provider_type="ollama", model="llama3")
        assert a.model == "llama3"


class TestStageProfile:
    def test_empty_by_default(self) -> None:
        p = StageProfile()
        assert p.assignments == []

    def test_by_task_type_returns_none_when_empty(self) -> None:
        p = StageProfile()
        assert p.by_task_type("scout") is None

    def test_upsert_adds_new(self) -> None:
        p = StageProfile()
        p.upsert("scout", "groq", "llama-3.1-8b")
        assert len(p.assignments) == 1
        assert p.assignments[0].task_type == "scout"
        assert p.assignments[0].provider_type == "groq"

    def test_upsert_updates_existing(self) -> None:
        p = StageProfile()
        p.upsert("scout", "groq")
        p.upsert("scout", "ollama", "llama3")
        assert len(p.assignments) == 1
        assert p.assignments[0].provider_type == "ollama"
        assert p.assignments[0].model == "llama3"

    def test_by_task_type_returns_assignment(self) -> None:
        p = StageProfile()
        p.upsert("scout", "groq")
        a = p.by_task_type("scout")
        assert a is not None
        assert a.provider_type == "groq"

    def test_remove_deletes_assignment(self) -> None:
        p = StageProfile()
        p.upsert("scout", "groq")
        p.upsert("deep_dive", "ollama")
        p.remove("scout")
        assert len(p.assignments) == 1
        assert p.assignments[0].task_type == "deep_dive"

    def test_remove_non_existent_does_nothing(self) -> None:
        p = StageProfile()
        p.upsert("scout", "groq")
        p.remove("nonexistent")
        assert len(p.assignments) == 1


class TestConstants:
    def test_all_stages_has_expected(self) -> None:
        assert "planning" in ALL_STAGES
        assert "scout" in ALL_STAGES
        assert "deep_dive" in ALL_STAGES
        assert "verification" in ALL_STAGES
        assert "synthesis" in ALL_STAGES
        assert "conflict_resolution" in ALL_STAGES

    def test_stage_labels_has_all_stages(self) -> None:
        for stage in ALL_STAGES:
            assert stage in STAGE_LABELS
