from __future__ import annotations

import json
import logging
from typing import Any

from argus.llm.router import CostAwareRouter
from argus.services.agents._parse import extract_json_array
from argus.services.agents.base import BaseAgent
from argus.services.memory.source_cache import SourceCache
from argus.services.tools.parser import DocumentParser
from argus.services.tools.scraper import WebScraper
from argus.shared.models import AgentType, Claim, Fact, Source, TaskStep

logger = logging.getLogger(__name__)

def _build_extraction_prompt(sources: list[dict[str, str]], query: str = "") -> str:
    from argus.llm.prompts.deep_dive import extract_batch
    return extract_batch(sources, query=query)


class DeepDiveAgent(BaseAgent):
    def __init__(
        self,
        router: Any = None,
        idempotency: Any = None,
        cost_tracker: Any = None,
    ) -> None:
        super().__init__(
            AgentType.DEEP_DIVE,
            router=router,
            idempotency=idempotency,
            cost_tracker=cost_tracker,
        )
        self._scraper = WebScraper()
        self._parser = DocumentParser()
        self._batch_router: CostAwareRouter | None = None
        self._source_cache = SourceCache()

    def _get_router(self) -> CostAwareRouter:
        if self._batch_router is None:
            self._batch_router = CostAwareRouter()
        return self._batch_router

    async def run(self, step: TaskStep) -> list[Fact]:
        logger.info("DeepDiveAgent running", extra={"step_id": step.id, "goal": step.goal})

        task_id = step.task_id
        urls = self._get_source_urls_for_task(task_id)
        if not urls:
            urls = self._wait_for_sources(task_id, step.id)
            if not urls:
                logger.info("No sources to deep-dive after waiting", extra={"step_id": step.id})
                return []

        sources_data: list[dict[str, str]] = []
        for url in urls:
            try:
                cached = self._source_cache.get(url)
                if cached is not None:
                    sources_data.append({
                        "url": url,
                        "title": url,
                        "content": cached,
                    })
                    logger.info("Source cache hit", extra={"url": url})
                    continue

                response = self._scraper.scrape(url)
                if response.content and response.content.markdown.strip():
                    self._source_cache.set(
                        url,
                        response.content.markdown,
                        keep=True,
                    )
                    sources_data.append({
                        "url": url,
                        "title": response.content.metadata.get("title", url),
                        "content": response.content.markdown,
                    })
            except Exception as exc:
                logger.warning("Scrape failed", extra={"url": url, "error": str(exc)})

        if not sources_data:
            return []

        all_claims: list[Claim] = []
        all_sources: list[Source] = []

        query = getattr(step, "query", "")
        from argus.shared.config import settings as _s
        batch_size = _s.deep_dive_batch_size
        for i in range(0, len(sources_data), batch_size):
            batch = sources_data[i:i + batch_size]
            claims, sources = self._extract_batch(batch, str(step.id), query=query)
            all_claims.extend(claims)
            all_sources.extend(sources)

        logger.info(
            "DeepDiveAgent complete",
            extra={"step_id": step.id, "claims": len(all_claims), "sources": len(all_sources)},
        )

        return self._emit_facts(step, [*all_claims, *all_sources])

    def _wait_for_sources(self, task_id: str, _step_id: int) -> list[str]:
        import time

        import redis as redis_lib

        from argus.shared.config import settings

        try:
            r = redis_lib.from_url(settings.redis_url, socket_connect_timeout=2)
        except Exception:
            time.sleep(5)
            return self._get_source_urls_for_task(task_id)

        deadline = time.time() + settings.agent_wait_seconds
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
                urls = self._get_source_urls_for_task(task_id)
                if urls:
                    return urls
            return []
        finally:
            r.close()

    def _get_source_urls_for_task(self, task_id: str) -> list[str]:
        import sqlite3
        try:
            from argus.shared.config import settings
            conn = sqlite3.connect(settings.sqlite_path)
            rows = conn.execute(
                "SELECT url FROM sources WHERE task_id = ? ORDER BY rowid",
                (task_id,),
            ).fetchall()
            conn.close()
            return [r[0] for r in rows]
        except sqlite3.Error as exc:
            logger.warning("Failed to query sources for deep-dive", extra={"error": str(exc)})
            return []

    def _extract_batch(
        self,
        batch: list[dict[str, str]],
        task_id: str,
        query: str = "",
    ) -> tuple[list[Claim], list[Source]]:
        prompt = _build_extraction_prompt(batch, query=query)
        sources_list: list[Source] = []

        for src in batch:
            sources_list.append(Source(
                url=src["url"],
                title=src.get("title", ""),
                credibility_score=0.5,
            ))

        try:
            self._check_budget(estimated_cost=0.02)
            response_text, provider, cost = self._get_router().complete(
                task_type="deep_dive",
                prompt=prompt,
            )
            self._record_cost(cost, category="llm")
        except RuntimeError:
            logger.warning("Batch extraction failed, falling back to single-source")
            return self._extract_single(batch, task_id, query=query)

        try:
            raw_claims: list[dict[str, Any]] = extract_json_array(response_text)
            if isinstance(raw_claims, dict):
                raw_claims = raw_claims.get("claims", [raw_claims])
            claims = [
                Claim(
                    statement=c.get("statement", ""),
                    confidence={"high": 0.9, "medium": 0.6, "low": 0.3}.get(
                        c.get("confidence", "medium"), 0.5
                    ),
                    source_urls=[src["url"] for src in batch],
                    entity_name=c.get("entity_name"),
                    attribute=c.get("attribute"),
                )
                for c in raw_claims
                if c.get("statement")
            ]
            return claims, sources_list
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            logger.warning("Failed to parse batch extraction", extra={"error": str(exc)})
            return self._extract_single(batch, task_id, query=query)

    def _extract_single(
        self,
        batch: list[dict[str, str]],
        _task_id: str,
        query: str = "",
    ) -> tuple[list[Claim], list[Source]]:
        all_claims: list[Claim] = []
        all_sources: list[Source] = []

        for src in batch:
            all_sources.append(Source(
                url=src["url"],
                title=src.get("title", ""),
                credibility_score=0.5,
            ))

            from argus.llm.prompts.deep_dive import extract_single as _single
            single_prompt = _single(src, query=query)

            try:
                text, provider, cost = self._get_router().complete(
                    task_type="deep_dive",
                    prompt=single_prompt,
                )
                self._record_cost(cost, category="llm")

                raw = extract_json_array(text)
                if isinstance(raw, dict):
                    raw = raw.get("claims", [raw])
                for c in raw:
                    if c.get("statement"):
                        all_claims.append(Claim(
                            statement=c["statement"],
                            confidence=0.5,
                            source_urls=[src["url"]],
                            entity_name=c.get("entity_name"),
                            attribute=c.get("attribute"),
                        ))
            except (RuntimeError, json.JSONDecodeError, TypeError):
                logger.warning("Single extraction failed", extra={"url": src["url"]})

        return all_claims, all_sources
