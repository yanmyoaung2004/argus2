# Argus — Autonomous Research Agent

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/docker-ready-blue.svg)](https://www.docker.com/)

**Thinks in graphs, cites everything, shows its work.**

Argus is an event-driven, multi-agent research system. Submit a question; it plans a strategy, dispatches specialized agents via Redis Streams, builds a knowledge graph in SQLite, and produces an interactive HTML report with provenance — all for under $0.50 per query.

---

## System Architecture

Argus separates orchestration from execution through three core layers.

### 1. The Dispatcher (Orchestrator)

The central coordinator manages the research lifecycle:

- **Planner** — classifies queries (competitive analysis, tech comparison, academic survey) and produces a step DAG
- **Resource Arbitration** — pushes plan steps to agent-specific Redis Streams with bounded consumer groups
- **Lifespan Management** — idle timeout detection, graceful shutdown, task status tracking

### 2. The Agent Pool (Execution)

Specialized agents consume from their assigned stream and emit structured facts:

| Agent | Responsibility | Consumes From |
|-------|---------------|---------------|
| Scout | Web search → entities + sources | `tasks:scout` |
| Deep-Dive | Page scrape → claim extraction | `tasks:deep_dive` |
| Verification | Conflict detection across claims | `tasks:verification` |
| Synthesis | Entity resolution + relationship edges | `tasks:synthesis` |

All agents share a common base with budget enforcement, circuit breaker, and idempotency guarantees.

### 3. The Knowledge Layer (Persistence)

A write-through pipeline that materializes agent output:

```
Agent → Redis `facts` stream → KG Writer (batch consumer) → SQLite
```

- **Knowledge Graph** — entities, claims, sources, edges with recursive CTE support
- **Vector Index** — sqlite-vec HNSW for ANN similarity search (384-dim embeddings)
- **Full-Text Search** — SQLite FTS5 over entity names and claim text
- **Confidence Scoring** — `base(0.5) + source_boost + credibility_boost + recency_boost - conflict_penalty`

---

## Operational Workflow

1. **Submit** — query enters via CLI or HTTP POST
2. **Plan** — the planner classifies, decomposes, and pushes steps to Redis streams
3. **Execute** — agents consume steps in parallel, publish facts and progress events
4. **Persist** — KG Writer batches facts and writes to SQLite on a 50ms/100-fact cadence
5. **Detect Completion** — the research manager polls progress streams; when all steps report done, it finalizes the task
6. **Report** — Markdown and interactive HTML (D3.js force-directed graph) are generated and saved to `~/.argus/reports/`

All external calls (LLM, search, scrape) pass through retry + circuit breaker layers. The cost tracker enforces a hard cap of $0.50/task with warnings at 60%.

---

## Quick Start

### Prerequisites

- Python 3.11+
- Redis 7+ (or Docker)
- [Ollama](https://ollama.com) (free, local LLM) — optional but recommended
- A Groq API key (free tier) — optional

### 1. Clone & install

```bash
git clone <repo-url> && cd argus
python -m venv .venv
.venv\Scripts\activate      # Windows
pip install -e ".[dev]"
```

### 2. Start Redis

Using Docker (recommended):

```bash
docker run -d --name argus-redis -p 6379:6379 redis:7-alpine
```

Or via Docker Compose:

```bash
docker compose -f infra/docker-compose.yml up redis -d
```

### 3. (Optional) Start Ollama

```bash
ollama pull llama3.2:3b
ollama serve
```

### 4. Configure — CLI Onboarding (recommended)

Run the interactive setup wizard to configure LLM providers, API keys, models, and search tools:

```bash
python -m argus onboard
```

The wizard walks you through:
- **LLM providers**: Groq, Ollama, OpenRouter, OpenAI-compatible, Anthropic, Google AI Studio, DeepSeek, Together AI, LiteLLM
- **Search providers**: DuckDuckGo, SerpAPI, Firecrawl, Tavily
- API key entry (masked) with **instant validation**
- Model selection from live API data
- Provider priority ordering (which to try first)
- Optional `.env` file update

Keys are tested immediately — invalid keys are rejected and you can retry.

### 5. (Alternative) Manual `.env` setup

Copy `.env.example` to `.env` and edit:

```bash
copy .env.example .env        # Windows
```

At minimum, set a Groq API key for the free LLM tier:

```
ARGUS_GROQ_API_KEY=gsk_...
```

All variables have safe defaults — only API keys for paid providers are required.

### 6. Run the server

**Important:** Start the app with the following command so that agent workers (scout, deep-dive, verification, synthesis, KG writer) run alongside the web server:

```bash
python -m argus
```

For development with hot-reload, run the web server and workers separately (two terminals):

```bash
# Terminal 1: worker processes
python -m argus --workers-only

# Terminal 2: web server with reload
uvicorn argus.app:app --reload --port 8001
```

Open http://localhost:8000/docs for the interactive Swagger UI.

---

## Usage

### Run a research query via CLI

Submit research directly from the command line. The server must be running (`python -m argus`):

```bash
# Defaults: 50 max sources, 30 min time limit
python -m argus research "What are the latest advances in LLM agents?"

# Custom limits
python -m argus research "AI coding tools comparison" --max-sources 33 --time-limit 333
```

What happens:
1. Submits the research query to the running server
2. Watches progress live via SSE (each agent step)
3. Fetches the interactive HTML report when done
4. Saves to `report_{slug}_{task_id}.html`
5. Opens the report in your browser

### List tasks & check status

```bash
# List all research tasks
python -m argus list

# Show detailed status of a specific task
python -m argus status <task_id>
```

### Stage profile configuration

Override default routing per task type:

```bash
python -m argus profile          # Interactive assignment
python -m argus profile-list     # Show current assignments
python -m argus profile-clear    # Clear all assignments
```

### Search provider configuration

Configure fallback priority and settings:

```bash
python -m argus search           # Interactive config
python -m argus search-list      # Show current config
```

### Run a research query via API

```bash
curl -X POST http://localhost:8000/research \
  -H "Content-Type: application/json" \
  -d '{"query": "What are the latest advances in LLM agents?"}'
```

Response:

```json
{"task_id": "0192a1b0-...", "status": "planning", "message": "Research task created: 0192a1b0-..."}
```

### Watch progress via SSE

Using the CLI watcher:

```bash
python -m argus.ui.watcher 0192a1b0-...
```

Or open in a browser: `http://localhost:8000/static/watcher.html` and enter the task ID.

### Get the report

Markdown:

```bash
curl http://localhost:8000/research/0192a1b0-.../report
```

Interactive HTML (D3.js graph):

```bash
curl http://localhost:8000/research/0192a1b0-.../html
```

Open the HTML in a browser for the full interactive view with:
- Force-directed knowledge graph (entities + claims + sources)
- Expandable claim cards with confidence scores
- Source credibility breakdown
- Cost report

Reports are also auto-saved to `~/.argus/reports/` upon task completion.

### Provide feedback

Improve source credibility for future research:

```bash
curl -X POST http://localhost:8000/research/feedback/1 \
  -H "Content-Type: application/json" \
  -d '{"is_correct": true}'
```

### Check system health

```bash
curl http://localhost:8000/health
```

Returns agent heartbeat status, uptime, stale agent detection.

### Cache stats

```bash
curl http://localhost:8000/cache/stats
```

Returns hit rate, total entries, kept entries, size, and expiry info.

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/research` | Create a new research task |
| GET | `/research` | List all research tasks |
| GET | `/research/{task_id}` | Get task status + step progress |
| GET | `/research/{task_id}/status` | SSE stream of research progress |
| GET | `/research/{task_id}/report` | Markdown report |
| GET | `/research/{task_id}/html` | Interactive HTML report with D3.js graph |
| POST | `/research/feedback/{source_id}` | Submit source credibility feedback |
| GET | `/health` | System health + agent heartbeats |
| GET | `/cache/stats` | Source cache statistics |

---

## Cost-Aware LLM Routing

Every call routes through a task-type-aware selector with ordered fallback:

| Task Type | Primary | Fallback Chain |
|-----------|---------|---------------|
| Planning | Ollama | Groq → OpenRouter → OpenAI → Anthropic → Google AI Studio → DeepSeek → Together AI → LiteLLM |
| Scout | Groq | Ollama → OpenRouter → OpenAI → Google AI Studio → DeepSeek → Together AI |
| Deep-Dive | Ollama | Groq → OpenRouter → OpenAI → Anthropic → Google AI Studio → DeepSeek → Together AI → LiteLLM |
| Verification | Groq | Ollama → OpenRouter → OpenAI → Anthropic → Google AI Studio → DeepSeek |
| Synthesis | Ollama | Groq → OpenRouter → OpenAI → Google AI Studio → DeepSeek → Together AI → LiteLLM |
| Conflict Resolution | Groq | OpenRouter → OpenAI → Anthropic → Google AI Studio → DeepSeek → OpenAI-Compatible |

Stage profiles (`~/.argus/stage_profiles.json`) can override these defaults per task type. If set, the assigned provider+model is tried first before the default fallback chain.

Prompt compression (30-50% reduction) is automatically applied for Ollama and Groq calls. LLM responses are cached by SHA256 prompt hash and reused across tasks.

---

## Cost

Argus is designed to run for **under $0.50 per research query**:

| Service | Cost | When used |
|---------|------|-----------|
| Ollama (local) | Free | Default LLM |
| DuckDuckGo | Free | Default search |
| httpx + BeautifulSoup | Free | Default scrape |
| Groq free tier | Free | Scout, verification tasks |
| SQLite + sqlite-vec | Free | Knowledge graph + vector store |
| SerpAPI | ~$0.01/query | Fallback if DDG fails |
| OpenRouter | ~$0.0001-0.01/call | Paid LLM fallback |
| Firecrawl | ~$0.003/page | Tertiary scrape fallback |
| Tavily | ~$0.005/search | Last-resort search fallback |

The cost tracker enforces the hard cap at runtime, raises `BudgetExceededError` before overshoot, and logs a warning at 60%. Both LLM calls and source scrapes are cached to eliminate redundant spending.

---

## Testing

```bash
# Run all tests
pytest

# With coverage
pytest --cov=argus

# Run specific test file
pytest tests/unit/test_compressor.py -v

# Run integration tests
pytest tests/integration/ -v

# Lint & type check
ruff check .
mypy .
```

Current test count: **211 tests** across unit, integration, and evaluation suites.

---

## Deployment

### Docker Compose (recommended)

```bash
# Set required API keys
export ARGUS_GROQ_API_KEY=gsk_...

# Start all services
docker compose -f infra/docker-compose.yml up --build

# Or run in background
docker compose -f infra/docker-compose.yml up --build -d
```

The app is available at `http://localhost:8000`.

### Manual Configuration

All configuration is via environment variables with prefix `ARGUS_`. Key settings:

| Variable | Default | Description |
|----------|---------|-------------|
| `ARGUS_REDIS_URL` | `redis://localhost:6379/0` | Redis connection |
| `ARGUS_OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama endpoint |
| `ARGUS_GROQ_API_KEY` | — | Groq API key |
| `ARGUS_SERPAPI_API_KEY` | — | SerpAPI search key |
| `ARGUS_FIRECRAWL_API_KEY` | — | Firecrawl API key |
| `ARGUS_TAVILY_API_KEY` | — | Tavily search key |
| `ARGUS_BUDGET_PER_RESEARCH` | `0.50` | Hard cost cap per query |
| `ARGUS_AGENT_CONCURRENCY` | `2` | Parallel agent workers |

See `.env.example` for the full list.

---

## Docs

- [`docs/manual.md`](docs/manual.md) — Full user manual (setup, config, usage, troubleshooting)
- [`docs/solution.md`](docs/solution.md) — Problem space, how Argus solves it, cost analysis, comparisons
- [`docs/architecture.md`](docs/architecture.md) — Full system architecture
- [`docs/graph_schema.md`](docs/graph_schema.md) — Knowledge graph schema
- [`docs/agent_protocols.md`](docs/agent_protocols.md) — Redis stream protocols
- [`docs/performance.md`](docs/performance.md) — Performance tuning
- [`project.md`](project.md) — High-level design doc
- [`PLAN.md`](PLAN.md) — Implementation plan
