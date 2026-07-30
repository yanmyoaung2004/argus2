from __future__ import annotations

import json
import logging
from typing import Any

from argus.services.agents._parse import extract_json_array
from argus.services.agents.base import BaseAgent
from argus.services.tools.search import WebSearch
from argus.shared.models import AgentType, Entity, Fact, Source, TaskStep

logger = logging.getLogger(__name__)


class ScoutAgent(BaseAgent):
    def __init__(
        self,
        router: Any = None,
        idempotency: Any = None,
        cost_tracker: Any = None,
    ) -> None:
        super().__init__(
            AgentType.SCOUT,
            router=router,
            idempotency=idempotency,
            cost_tracker=cost_tracker,
        )
        self._searcher = WebSearch()

    async def run(self, step: TaskStep) -> list[Fact]:
        logger.info("ScoutAgent running", extra={"step_id": step.id, "goal": step.goal})

        search_query = step.goal.replace("Research ", "").strip()
        query = getattr(step, "query", "") or search_query
        from argus.shared.config import settings as _s
        search_response = self._searcher.search(search_query, max_results=_s.scout_max_results)

        if not search_response.results:
            logger.info("No search results found", extra={"step_id": step.id})
            return []

        entities: list[Entity] = []
        sources: list[Source] = []

        analyzed = self._analyze_results(search_response.results, query)

        if analyzed:
            for item in analyzed:
                source = Source(
                    url=item.get("url", ""),
                    title=item.get("title", ""),
                    credibility_score=0.5,
                )
                sources.append(source)

                for ent in item.get("extracted_entities", []):
                    entity = Entity(
                        name=ent.get("name", item.get("title", "unknown"))[:80],
                        type=ent.get("type", "unknown"),
                        description=ent.get("description", "")[:200],
                        attributes={
                            "url": item.get("url", ""),
                            "relevance": item.get("relevance", "medium"),
                        },
                    )
                    url_lower = item.get("url", "").lower()
                    if any(d in url_lower for d in ["wikipedia.org", "britannica.com"]):
                        entity.attributes["authoritative"] = True
                    entities.append(entity)
        else:
            for result in search_response.results:
                source = Source(
                    url=result.url,
                    title=result.title,
                    credibility_score=0.5,
                )
                sources.append(source)

                name = result.title
                if " - " in name:
                    name = name.split(" - ")[0].strip()
                entity_type = "organization" if any(
                    t in result.url for t in [".com", ".org", ".io"]
                ) else "unknown"
                entity = Entity(
                    name=name[:80],
                    type=entity_type,
                    description=result.snippet[:200],
                    attributes={"url": result.url, "snippet": result.snippet},
                )
                url_lower = result.url.lower()
                if any(domain in url_lower for domain in ["wikipedia.org", "britannica.com"]):
                    entity.attributes["authoritative"] = True
                entities.append(entity)

        logger.info("ScoutAgent complete", extra={
            "step_id": step.id, "sources": len(sources), "entities": len(entities),
            "llm_analyzed": bool(analyzed),
        })

        return self._emit_facts(step, [*entities, *sources])

    def _analyze_results(
        self,
        results: list[Any],
        query: str,
    ) -> list[dict[str, Any]]:
        if not self._router:
            return []

        from argus.llm.prompts.scout import analyze_results as _prompt
        prompt = _prompt(query, results)

        try:
            self._check_budget(estimated_cost=0.01)
            text, provider, cost = self._router.complete(
                task_type="scout",
                prompt=prompt,
            )
            self._record_cost(cost, category="llm")

            result: list[dict[str, Any]] = extract_json_array(text)
            return [
                item for item in result
                if item.get("relevance", "low") in ("high", "medium")
                and item.get("url")
            ]
        except (RuntimeError, json.JSONDecodeError, TypeError) as exc:
            logger.warning(
                "Scout LLM analysis failed, using raw results", extra={"error": str(exc)}
            )
            return []
