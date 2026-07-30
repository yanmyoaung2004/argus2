from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from argus.services.orchestrator.manager import ResearchManager
from argus.shared.models import ResearchPlan, ResearchStatus, TaskStep


def make_plan() -> ResearchPlan:
    return ResearchPlan(steps=[
        TaskStep(id=1, type="discover", agent="scout", goal="Research topic", task_id="t"),
        TaskStep(id=2, type="synthesize", agent="synthesis", goal="Synthesize findings", task_id="t"),
    ])


class FakePlanner:
    def decompose(self, query: str) -> ResearchPlan:
        return make_plan()


@pytest.fixture
def manager() -> ResearchManager:
    return ResearchManager(planner=FakePlanner())


@pytest.fixture
def manager_with_redis() -> ResearchManager:
    redis = MagicMock()
    redis.xadd.return_value = b"mock-id"
    return ResearchManager(redis_client=redis, planner=FakePlanner())


class TestResearchManagerInit:
    def test_initial_state(self, manager: ResearchManager) -> None:
        assert manager._tasks == {}
        assert manager._shutdown is False

    def test_background_thread_running(self, manager: ResearchManager) -> None:
        assert manager._completion_thread.is_alive()


class TestCreateTask:
    @pytest.mark.asyncio
    async def test_creates_task_with_plan(self, manager_with_redis: ResearchManager) -> None:
        task = await manager_with_redis.create_task("test query")
        assert task.query == "test query"
        assert task.plan is not None
        assert len(task.plan.steps) == 2
        assert task.status == ResearchStatus.RUNNING

    @pytest.mark.asyncio
    async def test_task_added_to_dict(self, manager_with_redis: ResearchManager) -> None:
        task = await manager_with_redis.create_task("test")
        assert str(task.task_id) in manager_with_redis._tasks

    @pytest.mark.asyncio
    async def test_task_fails_on_planner_error(self, manager: ResearchManager) -> None:
        bad_planner = MagicMock()
        bad_planner.decompose.side_effect = ValueError("Planner failed")
        manager._planner = bad_planner
        task = await manager.create_task("test")
        assert task.status == ResearchStatus.FAILED
        assert "Planner failed" in (task.error_message or "")


class TestListTasks:
    @pytest.mark.asyncio
    async def test_empty_when_no_tasks(self, manager: ResearchManager) -> None:
        assert manager.list_tasks() == []

    @pytest.mark.asyncio
    async def test_returns_task_summaries(self, manager_with_redis: ResearchManager) -> None:
        await manager_with_redis.create_task("test query")
        tasks = manager_with_redis.list_tasks()
        assert len(tasks) == 1
        assert tasks[0]["query"] == "test query"
        assert "task_id" in tasks[0]
        assert "status" in tasks[0]


class TestGetTaskStatus:
    @pytest.mark.asyncio
    async def test_returns_none_for_unknown(self, manager: ResearchManager) -> None:
        assert manager.get_task_status("nonexistent") is None

    @pytest.mark.asyncio
    async def test_returns_task_details(self, manager_with_redis: ResearchManager) -> None:
        task = await manager_with_redis.create_task("test")
        status = manager_with_redis.get_task_status(str(task.task_id))
        assert status is not None
        assert status["query"] == "test"


class TestCompleteTask:
    @pytest.mark.asyncio
    async def test_completes_running_task(self, manager: ResearchManager) -> None:
        from uuid import uuid4
        tid = str(uuid4())
        from argus.shared.models import ResearchTask
        task = ResearchTask(task_id=tid, query="test")
        manager._tasks[tid] = task
        manager._tasks[tid].status = ResearchStatus.RUNNING
        manager._tasks[tid].plan = make_plan()
        manager.complete_task(tid)
        assert manager._tasks[tid].status == ResearchStatus.DONE

    def test_skip_completed_task(self, manager: ResearchManager) -> None:
        from uuid import uuid4

        from argus.shared.models import ResearchTask
        tid = str(uuid4())
        task = ResearchTask(task_id=tid, query="test")
        task.status = ResearchStatus.DONE
        manager._tasks[tid] = task
        manager.complete_task(tid)
        assert manager._tasks[tid].status == ResearchStatus.DONE


class TestFailTask:
    def test_fails_running_task(self, manager: ResearchManager) -> None:
        from uuid import uuid4

        from argus.shared.models import ResearchTask
        tid = str(uuid4())
        task = ResearchTask(task_id=tid, query="test")
        task.status = ResearchStatus.RUNNING
        manager._tasks[tid] = task
        manager.fail_task(tid, "something went wrong")
        assert manager._tasks[tid].status == ResearchStatus.FAILED
        assert manager._tasks[tid].error_message == "something went wrong"


class TestCheckTimeouts:
    @pytest.mark.asyncio
    async def test_no_expired_timeouts(self, manager: ResearchManager) -> None:
        await manager.check_timeouts()
        assert True

    def test_shutdown_skips_check(self, manager: ResearchManager) -> None:
        manager._shutdown = True
        import asyncio
        asyncio.run(manager.check_timeouts())
        assert True


class TestShutdown:
    @pytest.mark.asyncio
    async def test_marks_shutdown(self, manager: ResearchManager) -> None:
        await manager.shutdown()
        assert manager._shutdown is True

    @pytest.mark.asyncio
    async def test_clears_timeouts(self, manager: ResearchManager) -> None:
        await manager.shutdown()
        assert manager._timeouts == {}
