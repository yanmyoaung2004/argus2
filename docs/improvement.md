# Argus Improvement Plan

Analysis based on code review across ~6,750 LOC, 64 source files, and 24 test files.

## P0 — Critical Bugs (will fail at runtime)

| # | File | Issue | Fix |
|---|------|-------|-----|
| 1 | `argus/services/tools/search.py:9` | `from ddgs import DDGS` — package `ddgs` does not exist | Change to `from duckduckgo_search import DDGS` |
| 2 | `argus/app.py:88` | `POST /feedback/{source_id}` — path param conflicts with body field `source_id` | Remove path param; use body only |
| 3 | `argus/orchestrator/agent_runner.py:183` | `asyncio.run()` in sync thread creates new event loop per message; leaks loops | Use a dedicated event loop per thread or restructure with `asyncio.run_coroutine_threadsafe` |
| 4 | `argus/services/heartbeat.py` | `HeartbeatWriter` exists but never instantiated | Wire into `AgentRunner` threads |
| 5 | `argus/services/dlq/consumer.py` | `DLQConsumer.start()` never called | Wire into `AgentRunner` or `__main__.py` |

## P1 — Architectural Weaknesses

### Busy-wait polling
`deep_dive.py:72-84` and `verification.py:38-51` poll SQLite with `time.sleep(5)` for up to 5 attempts (~135s blocked). Replace with Redis pub/sub notification when scout results arrive, or use blocking `xread` with timeout on the progress stream.

### Duplicate models
Two `ResearchRequest` and `ResearchResponse` classes exist — one in `shared/models.py` and one in `orchestrator/models.py`. Consolidate into `shared/models.py` and import everywhere.

### Agent reads SQLite directly
`deep_dive.py:137-150` reads scout source URLs directly from SQLite, bypassing the KG Writer. This creates a circular dependency (scout writes → KG Writer inserts → deep_dive reads). Route through Redis or add a dedicated query stream.

### SSE streamer never exits
`sse.py:33` has a `while True` loop with no completion detection. Add a heartbeat/timeout mechanism and listen for a research-complete signal on the progress stream.

### `_get_redis()` repeated 14×
Same `redis.from_url()` connection logic copy-pasted across 10+ classes. Extract into a shared factory or use dependency injection.

### structlog installed, stdlib logging used
`shared/logging.py` sets up `structlog` but all modules use `logging.getLogger(__name__)`. Either remove structlog or convert all modules.

## P2 — Incomplete Wiring

| Component | Status | Action |
|-----------|--------|--------|
| Prompt compressor | Implemented in `llm/compressor.py` but never called in `llm/router.py` | Wire compression before LLM calls |
| Checkpoint resume | `CheckpointManager` exists but no agent calls it | Integrate into agent `run()` methods |
| LLM cache (semantic) | `llm_cache.py` uses SHA256 exact match, docs claim semantic | Implement sqlite-vec similarity or downgrade docs |
| Vector embeddings | `_mock_embedding()` returns deterministic hash | Replace with real embeddings (e.g., `sentence-transformers`) or document as stub |
| FTS5 entity sync | `claims_fts` table created but no trigger for `entity_name` changes | Add `AFTER UPDATE` trigger |

## P3 — Code Quality & Consistency

- **`except Exception: continue`** in `search.py` silently swallows all search provider failures. Log and track failures per provider.
- **`except Exception: pass`** in `agent_runner.py:233-234`. Remove bare passes.
- **Inline imports of `_parse.py`** — `from argus.services.agents._parse import extract_json_array` done inside functions. Move to top-level.
- **`BudgetExceededError` never caught** — if the budget enforcer fires inside an agent, it propagates to the generic `except Exception` in `AgentRunner`. Catch explicitly and emit a progress event.
- **`CostTracker` retry on Redis reads** — `get_total_cost()` and `record_cost()` have `@retry` decorators. Redis reads/writes should not need retry logic.
- **`# type: ignore`** in 3+ places for `uuid7` import. Vendor a stub or use `Any`.

## P4 — Test Coverage Gaps

| Missing Tests | Impact |
|---------------|--------|
| `scout.py` (LLM-powered scout) | No coverage at all |
| `planner/` (rules + LLM planner) | Core decomposition logic untested |
| `routes.py` (FastAPI endpoints) | API surface untested |
| `manager.py` (ResearchManager lifecycle) | Pipeline orchestration untested |
| `sse.py` (SSE streaming) | Real-time streaming untested |
| `kg_writer.py` (batch insert + dedup) | KG persistence untested |
| End-to-end scout→deep_dive→verify→synthesize | Integration gap |

## P5 — Performance

- **Thread-per-agent** starts 4-6 threads at boot, each with infinite polling. Fine for single-user, but consider `asyncio` + single event loop.
- **Synchronous I/O everywhere** — `httpx.Client()`, `sqlite3.connect()`. All I/O blocks threads. Consider `aiosqlite` and `httpx.AsyncClient` if latency becomes an issue.
- **`list()` on `xread`** materializes entire Redis stream into memory before iteration. Iterate directly.
- **No connection pooling for SQLite** — each `_get_db()` call opens a new connection. In 5+ concurrent agent threads, this creates contention.

## P6 — Nice to Have

- Remove CORS `allow_origins=["*"]` or make it configurable
- Add agent heartbeat monitoring to health endpoint
- Make `_parse.py` JSON extraction handle markdown code fences (` ```json `)
- Add semantic LLM cache using sqlite-vec real embeddings
- Integration test for the full research pipeline
- Support configurable max sources/time per task via API
