# Argus Improvement Plan v1

Status of the original `improvement.md` after completion of all P0–P5 items.

---

## Completed in Round 1

| Priority | Item | Status |
|----------|------|--------|
| P0.1 | `from ddgs import DDGS` import fix (package renamed) | Done |
| P0.2 | `/feedback/{source_id}` route param conflict | Done |
| P0.3 | `asyncio.run()` leak in `agent_runner.py` → persistent loop | Done |
| P0.4 | `HeartbeatWriter` wired into `AgentRunner` | Done |
| P0.5 | `DLQConsumer.start()` wired into `__main__.py` | Done |
| P1.1 | Busy-wait polling → blocking `xread` in deep_dive + verification | Done |
| P1.2 | Duplicate `ResearchRequest`/`ResearchResponse` models consolidated | Done |
| P2.1 | Prompt compressor wired into router | Done |
| P3.1 | `except Exception: pass` → logged | Done |
| P3.2 | Inline `_parse` imports moved to top-level | Done |
| P3.3 | `BudgetError`/`BudgetExceededError` caught explicitly in agent_runner | Done |
| P4 | CORS origins configurable via env var | Done |
| P5 | `list()` wrapping on `xread` removed | Done |
| — | Verification JOIN query fixed (`entity_name` doesn't exist on claims table) | Done |
| — | `datetime.utcnow()` → `datetime.now(timezone.utc)` | Done |
| — | `close()` restored on `IdempotencyChecker` | Done |

---

## Remaining — What Can Still Be Improved

### Q1 — Unfinished Integration

| # | Item | Detail |
|---|------|--------|
| 1 | **`CheckpointManager` never wired** | Class exists, tests pass, but no agent or runner calls it. Add checkpoint save/restore to agent `run()` methods so interrupted research can resume. |
| 2 | **`KGWriter` missing idempotency dedup** | `KGWriter._process_message` doesn't check the `idempotency_key` on messages. Should skip already-processed facts to guarantee exactly-once writes. |
| 3 | **SSE streamer has no exit condition** | `sse.py:stream()` loops `while True` with no completion signal from the progress stream. Add a heartbeat/timeout and exit when a `research_complete` event arrives. |
| 4 | **`HeartbeatWriter` not visible in `/health`** | `/health` endpoint calls `get_alive_agents()` but that only shows stale agents. Should integrate active heartbeat data from all agent runners. |
| 5 | **Prompt compressor only for Ollama/Groq** | `COMPRESSIBLE_PROVIDERS` in `compressor.py` only targets Ollama/Groq. Extend to all providers or make configurable. |
| 6 | **`playwright` added but scraper never calls it** | `scraper.py` references Playwright but falls through to httpx+BS4 first. Wire Playwright as a JS-rendering fallback when httpx returns no content. |

### Q2 — Architecture

| # | Item | Detail |
|---|------|--------|
| 7 | **`_get_redis()` repeated 14×** | Same `redis.from_url(settings.redis_url, socket_connect_timeout=2)` pattern duplicated across 10+ classes. Extract to a shared `RedisFactory` or dependency-injected client. |
| 8 | **Agent reads SQLite directly** | `DeepDiveAgent._get_source_urls_for_task()` queries SQLite directly, bypassing the KG Writer pattern. Should route through Redis or a dedicated query stream. |
| 9 | **No async I/O** | All HTTP, Redis, and SQLite calls are synchronous (httpx.Client, sqlite3.connect, etc.). Each blocks a thread. Consider `httpx.AsyncClient`, `aiosqlite`, and `redis.asyncio` for a single-event-loop architecture. |
| 10 | **Thread-per-agent with sleep polling** | Even with `xread` improvements, `_consume_loop` still calls `time.sleep(0.1)` in the no-messages path. Switch to fully async event loop with `asyncio` in `__main__.py`. |
| 11 | **No Redis alternative** | Everything depends on Redis (streams, cache, heartbeat, cost tracking). No fallback to SQLite-polling or in-process queue. Add a Redis-less mode for development/testing. |

### Q3 — Vector Search & LLM Cache

| # | Item | Detail |
|---|------|--------|
| 12 | **Semantic LLM cache** | `llm_cache.py` uses SHA256 exact-match against the full prompt text. Implement sqlite-vec similarity search so semantically similar prompts return cached responses. |
| 13 | **Real vector embeddings** | `_mock_embedding()` in `vector_store.py` returns deterministic hash-based vectors. Replace with a real embedding model (e.g. `sentence-transformers` or Ollama embeddings API) or document as stub. |
| 14 | **`load_vec()` never called** | sqlite-vec extension is loaded but `load_vec()` is never invoked. The FTS5 + vector hybrid search is documented but unimplemented. |

### Q4 — Data Integrity

| # | Item | Detail |
|---|------|--------|
| 15 | **FTS5 trigger for entity_name updates** | `claims_fts` has `AFTER INSERT` trigger but no `AFTER UPDATE` trigger. When an entity name changes, the FTS index becomes stale. |
| 16 | **`getattr(self, attr, default)` patterns** | `verification.py:_check_conflict` uses `getattr(self, "_query", "")` instead of a typed instance attribute. `synthesis.py:_process_fact_item` uses `fact.get("type", fact.get("__type__", ""))`. These are fragile — should use explicit attributes. |
| 17 | **`_parse.py` JSON extraction fragile** | `extract_json_array` and `extract_json_object` use simple bracket matching. If LLM output contains nested brackets or markdown fences, parsing fails. Use regex or a more robust extraction. |

### Q5 — Testing Gaps

| # | Item | Detail |
|---|------|--------|
| 18 | **No tests for scout.py** | The LLM-powered scout has zero test coverage. Add unit tests for `_analyze_results()` and the fallback path. |
| 19 | **No tests for planner/** | Neither `RuleBasedPlanner` nor `LLMPlanner` have tests. Core research decomposition logic is untested. |
| 20 | **No tests for routes.py** | FastAPI endpoints (research, report, feedback) have no test coverage. Add httpx-based integration tests. |
| 21 | **No tests for manager.py** | ResearchManager lifecycle (create, complete, fail, timeout) is untested. |
| 22 | **No tests for kg_writer.py** | Fact buffer, batch insert, dedup, and error recovery have no tests. |
| 23 | **No end-to-end pipeline tests** | Scout → deep_dive → verification → synthesis flow is never tested as a whole. |

### Q6 — Performance

| # | Item | Detail |
|---|------|--------|
| 24 | **`KGWriter` materializes xread into list** | `list(r.xread(...))` at `writer.py:62` loads the entire stream batch into memory. Iterate the generator directly. |
| 25 | **`SynthesisAgent._process_fact_item` opens/closes DB per entity** | Each fact from the `facts` stream opens a new SQLite connection, runs queries, and closes. Batch entity processing would reduce overhead. |
| 26 | **No connection pooling for SQLite** | Every `_get_db()` / `_get_conn()` call opens a fresh connection. With 5+ agent threads, this creates unnecessary contention. Use `sqlite3.connect()` with `cached_statements` or a pool. |
| 27 | **`CostTracker` retry on Redis reads** | `get_total_cost()` and `record_cost()` have `@retry` from tenacity for simple Redis GET/SET operations. Remove retry — these should be fast and reliable. |

### Q7 — Security

| # | Item | Detail |
|---|------|--------|
| 28 | **API keys in `providers.json` plaintext** | `~/.argus/providers.json` stores API keys in plaintext. Use keyring or encrypted storage. |
| 29 | **No API authentication** | FastAPI server has no auth. Fine for local single-user, but document this limitation and add a configurable API key for remote access. |
| 30 | **`User-Agent` spoofing in scraper** | `scraper.py` mimics Chrome browser. Polite scraping but violates some ToS. Add a config option for user-agent. |

### Q8 — Developer Experience

| # | Item | Detail |
|---|------|--------|
| 31 | **structlog installed but unused** | `shared/logging.py` sets up structlog but all modules use stdlib `logging`. Either remove structlog or migrate all modules. |
| 32 | **`# type: ignore` scattered** | 8+ `# type: ignore` comments across the codebase for uuid7, xadd type variance, etc. Vendor stubs or fix the root causes. |
| 33 | **No Redis mock in tests** | Integration tests use `unittest.mock.MagicMock` for Redis. A proper `FakeRedis` class (like `test_full_research_parallel.py` has) should be standardized in conftest. |
| 34 | **Docker Compose only for Redis** | `compose.yml` only runs Redis. Add the app service or at minimum a `docker-compose.override.yml` example. |
