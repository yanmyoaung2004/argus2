from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import redis as redis_lib

from argus.services.orchestrator.planner import LLMPlanner
from argus.services.orchestrator.timeout import IdleTimeoutMonitor
from argus.shared.config import settings
from argus.shared.idempotency import generate_idempotency_key
from argus.shared.models import ResearchPlan, ResearchStatus, ResearchTask

logger = logging.getLogger(__name__)


class ResearchManager:
    def __init__(
        self,
        redis_client: redis_lib.Redis | None = None,
        planner: Any = None,
    ) -> None:
        self._redis = redis_client
        self._planner = planner or LLMPlanner()
        self._lock = threading.Lock()
        self._tasks: dict[str, ResearchTask] = {}
        self._timeouts: dict[str, IdleTimeoutMonitor] = {}
        self._completed_steps: dict[str, set[int]] = {}
        self._shutdown = False
        self._completion_thread = threading.Thread(target=self._poll_completions, daemon=True)
        self._completion_thread.start()

    def _get_redis(self) -> redis_lib.Redis | None:
        if self._redis is None:
            try:
                self._redis = redis_lib.from_url(settings.redis_url, socket_connect_timeout=2)
            except Exception:
                return None
        return self._redis

    async def create_task(
        self,
        query: str,
        max_sources: int = 50,
        max_duration_minutes: int = 30,
    ) -> ResearchTask:
        task = ResearchTask(
            task_id=uuid4(),
            query=query,
            max_sources=max_sources,
            max_duration_minutes=max_duration_minutes,
            status=ResearchStatus.PLANNING,
        )
        task_id_str = str(task.task_id)
        with self._lock:
            self._tasks[task_id_str] = task

        try:
            plan = self._planner.decompose(query)
            task.plan = plan
            task.status = ResearchStatus.RUNNING
            self._push_plan(task_id_str, plan)
            self._timeouts[task_id_str] = IdleTimeoutMonitor(
                task_id=task_id_str,
                idle_timeout_minutes=settings.research_idle_timeout_minutes,
                max_duration_minutes=task.max_duration_minutes,
            )
            logger.info(
                "Research planned and queued",
                extra={"task_id": task_id_str, "steps": len(plan.steps)},
            )
        except Exception as exc:
            task.status = ResearchStatus.FAILED
            task.error_message = str(exc)
            logger.error("Planning failed", extra={"task_id": task_id_str, "error": str(exc)})

        return task

    def _push_plan(self, task_id: str, plan: ResearchPlan) -> None:
        r = self._get_redis()
        if r is None:
            logger.warning("No Redis available, skipping plan push", extra={"task_id": task_id})
            return

        with self._lock:
            task = self._tasks.get(task_id)
        query = task.query if task else ""
        for step in plan.steps:
            message = {
                "idempotency_key": generate_idempotency_key(),
                "task_id": task_id,
                "step_id": step.id,
                "type": step.type.value,
                "agent": step.agent.value,
                "goal": step.goal,
                "query": query,
                "depends_on": json.dumps(step.depends_on),
            }
            stream = f"tasks:{step.agent.value}"
            r.xadd(stream, message, maxlen=settings.redis_stream_maxlen)  # type: ignore[arg-type]

    def _poll_completions(self) -> None:
        default_wait = 3.0
        wait = getattr(settings, "research_idle_timeout_minutes", default_wait)
        while not self._shutdown:
            time.sleep(min(wait * 60, 30.0))
            with self._lock:
                task_ids = list(self._tasks.keys())
            for task_id in task_ids:
                with self._lock:
                    task = self._tasks.get(task_id)
                if task is None or task.status != ResearchStatus.RUNNING or task.plan is None:
                    continue
                if self._all_steps_done(task_id, task.plan):
                    logger.info("All steps complete, finalizing task", extra={"task_id": task_id})
                    self.complete_task(task_id)

    def _all_steps_done(self, task_id: str, plan: ResearchPlan) -> bool:
        r = self._get_redis()
        if r is None:
            return False
        try:
            events = r.xrange(f"progress:{task_id}", count=100)
        except Exception:
            return False
        completed = set()
        for _msg_id, msg_data in events:
            if msg_data.get(b"type") == b"step_complete" and b"step_id" in msg_data:
                completed.add(int(msg_data[b"step_id"]))
        plan_step_ids = {s.id for s in plan.steps}
        return plan_step_ids.issubset(completed) and len(plan_step_ids) > 0

    def _save_report(self, task_id: str) -> None:
        try:
            from argus.ui.report_generator import MarkdownReportGenerator
            gen = MarkdownReportGenerator()
            report = gen.generate(task_id)
            if not report:
                logger.warning("No report content generated", extra={"task_id": task_id})
                return
            out_dir = Path.home() / ".argus" / "reports"
            out_dir.mkdir(parents=True, exist_ok=True)
            with self._lock:
                task = self._tasks.get(task_id)
            raw = task.query if task else "research"
            safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in raw)
            slug = safe[:40].strip().replace(" ", "_")
            path = out_dir / f"report_{slug}_{task_id[:8]}.md"
            path.write_text(report, encoding="utf-8")
            logger.info("Report saved", extra={"task_id": task_id, "path": str(path)})
        except Exception as exc:
            logger.error("Failed to save report", extra={"task_id": task_id, "error": str(exc)})

    def mark_progress(self, task_id: str) -> None:
        monitor = self._timeouts.get(task_id)
        if monitor is not None:
            monitor.mark_activity()

    def complete_task(self, task_id: str) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is not None and task.status not in (ResearchStatus.DONE, ResearchStatus.FAILED):
                task.status = ResearchStatus.DONE
                from datetime import datetime, timezone
                task.completed_at = datetime.now(timezone.utc)
                logger.info("Research completed", extra={"task_id": task_id})
            monitor = self._timeouts.pop(task_id, None)
        if monitor is not None:
            monitor.stop()
        self._save_report(task_id)

    def fail_task(self, task_id: str, error: str) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is not None and task.status != ResearchStatus.DONE:
                task.status = ResearchStatus.FAILED
                task.error_message = error
                logger.error("Research failed", extra={"task_id": task_id, "error": error})
            monitor = self._timeouts.pop(task_id, None)
        if monitor is not None:
            monitor.stop()

    async def check_timeouts(self) -> None:
        if self._shutdown:
            return
        with self._lock:
            expired_ids = [
                tid for tid, mon in self._timeouts.items()
                if mon.is_expired()
            ]
        for tid in expired_ids:
            msg = f"Idle timeout exceeded ({settings.research_idle_timeout_minutes} min)"
            self.fail_task(tid, msg)

    async def shutdown(self) -> None:
        self._shutdown = True
        logger.info("Research manager shutting down")
        with self._lock:
            for task_id in list(self._timeouts.keys()):
                item = self._timeouts.get(task_id)
                if item is not None:
                    item.stop()
            self._timeouts.clear()

    def list_tasks(self) -> list[dict[str, Any]]:
        with self._lock:
            tasks_snapshot = list(self._tasks.values())
        return [
            {
                "task_id": str(t.task_id),
                "query": t.query[:80],
                "status": t.status.value,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "completed_at": t.completed_at.isoformat() if t.completed_at else None,
                "total_cost": t.total_cost,
                "error_message": t.error_message,
            }
            for t in tasks_snapshot
        ]

    def get_task_status(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            task = self._tasks.get(task_id)
        if task is None:
            return None
        return {
            "task_id": str(task.task_id),
            "query": task.query,
            "status": task.status.value,
            "max_sources": task.max_sources,
            "max_duration_minutes": task.max_duration_minutes,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            "total_cost": task.total_cost,
            "error_message": task.error_message,
            "plan": task.plan.model_dump(mode="json") if task.plan else None,
        }

    async def get_report(self, task_id: str) -> str | None:
        with self._lock:
            task = self._tasks.get(task_id)
        if task is None:
            return None
        from argus.ui.report_generator import MarkdownReportGenerator
        gen = MarkdownReportGenerator()
        return gen.generate(task_id)

    async def get_html_report(self, task_id: str) -> str | None:
        with self._lock:
            task = self._tasks.get(task_id)
        if task is None:
            return None
        from argus.ui.report_generator import HTMLReportGenerator
        gen = HTMLReportGenerator()
        return gen.generate(task_id)

    async def apply_feedback(self, source_id: int, is_correct: bool) -> float:
        import sqlite3

        from argus.services.tools.credibility import SourceCredibilityScorer

        conn = sqlite3.connect(settings.sqlite_path)
        try:
            scorer = SourceCredibilityScorer()
            return scorer.apply_user_feedback(conn, source_id, is_correct)
        finally:
            conn.close()
