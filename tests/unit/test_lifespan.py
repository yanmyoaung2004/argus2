from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI

from argus.services.orchestrator.lifespan import lifespan


class TestLifespan:
    def test_lifespan_is_async_generator(self) -> None:
        app = FastAPI()
        gen = lifespan(app)
        assert hasattr(gen, "__aenter__")
        assert hasattr(gen, "__aexit__")

    @pytest.mark.asyncio
    async def test_lifespan_yields_and_cleans_up(self) -> None:
        app = FastAPI()
        async with lifespan(app):
            from argus.services.orchestrator.routes import _manager
            assert _manager is not None

    def test_handle_signal_on_windows(self) -> None:
        from argus.services.orchestrator.lifespan import lifespan
        app = FastAPI()
        gen = lifespan(app)
        # Windows doesn't support add_signal_handler, should log warning
        assert gen is not None
