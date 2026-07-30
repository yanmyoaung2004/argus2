from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from argus.services.orchestrator.sse import SSEStreamer


@pytest.fixture
def streamer() -> SSEStreamer:
    return SSEStreamer(task_id="test-task")


class TestSSEStreamer:
    def test_init(self, streamer: SSEStreamer) -> None:
        assert streamer.task_id == "test-task"
        assert streamer._redis is None

    def test_get_redis_creates_connection(self, streamer: SSEStreamer) -> None:
        r = streamer._get_redis()
        assert r is not None

    def test_stream_with_mock_redis(self) -> None:
        mock_redis = MagicMock()
        mock_redis.xread.return_value = [
            [
                b"progress:test-task",
                [
                    (
                        b"1-0",
                        {b"type": b"step_complete", b"data": b'{"step_id": 1}'},
                    ),
                ],
            ]
        ]
        streamer = SSEStreamer(task_id="test-task", redis_client=mock_redis)
        assert streamer._redis is mock_redis
