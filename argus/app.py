from __future__ import annotations

import logging
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles

from argus.services.heartbeat import get_alive_agents
from argus.services.memory.source_cache import SourceCache
from argus.services.orchestrator.lifespan import lifespan
from argus.services.orchestrator.routes import router as research_router
from argus.shared.config import settings

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]

logging.basicConfig(
    level=getattr(logging, settings.app_log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

_start_time = time.time()

security_scheme = HTTPBearer(auto_error=False)


async def verify_token(credentials: HTTPAuthorizationCredentials | None = Depends(security_scheme)) -> None:
    if not settings.api_token:
        return
    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing authorization header")
    if credentials.credentials != settings.api_token:
        raise HTTPException(status_code=403, detail="Invalid auth token")


app = FastAPI(
    title="Argus Research Agent",
    version="0.1.0",
    lifespan=lifespan,
    dependencies=[Depends(verify_token)] if settings.api_token else [],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(research_router)

static_dir = Path(__file__).parent / "ui" / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/health")
async def health() -> dict[str, object]:
    agents: dict[str, object] = {}
    try:
        import redis as redis_lib
        r = redis_lib.from_url(settings.redis_url, socket_connect_timeout=2)
        agents = get_alive_agents(r)
        r.close()
    except Exception:
        agents = {}

    stale = {aid: info for aid, info in agents.items() if not info.get("alive", False)}
    if stale:
        for agent_id in stale:
            logging.getLogger(__name__).warning("Stale agent heartbeat", extra={"agent_id": agent_id})

    return {
        "status": "degraded" if stale else "ok",
        "app": "argus",
        "version": "0.1.0",
        "uptime_seconds": time.time() - _start_time,
        "agents_alive": len(agents) - len(stale),
        "agents_stale": len(stale),
        "agents": agents,
    }


@app.get("/cache/stats")
async def cache_stats() -> dict[str, object]:
    try:
        cache = SourceCache()
        stats = cache.get_stats()
        return {"status": "ok", **stats}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}
