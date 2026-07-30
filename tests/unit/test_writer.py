from __future__ import annotations

import json
from pathlib import Path

import pytest

from argus.services.knowledge_graph.writer import KGWriter


@pytest.fixture
def writer(tmp_path: Path) -> KGWriter:
    db = str(tmp_path / "test.db")
    w = KGWriter(db_path=db)
    yield w


class TestKGWriterInit:
    def test_initial_state(self, writer: KGWriter) -> None:
        assert writer._buffer == []
        assert writer._running is False

    def test_load_cursor_returns_zero_when_empty(self, writer: KGWriter) -> None:
        assert writer._load_cursor("test-stream") == "0"

    def test_save_and_load_cursor(self, writer: KGWriter) -> None:
        writer._save_cursor("test-stream", "12345-0")
        assert writer._load_cursor("test-stream") == "12345-0"

    def test_overwrite_cursor(self, writer: KGWriter) -> None:
        writer._save_cursor("test-stream", "12345-0")
        writer._save_cursor("test-stream", "67890-0")
        assert writer._load_cursor("test-stream") == "67890-0"

    def test_cursors_isolated_per_stream(self, writer: KGWriter) -> None:
        writer._save_cursor("stream-a", "aaa-0")
        writer._save_cursor("stream-b", "bbb-0")
        assert writer._load_cursor("stream-a") == "aaa-0"
        assert writer._load_cursor("stream-b") == "bbb-0"


class TestKGWriterFlush:
    def test_flush_empty_buffer_does_nothing(self, writer: KGWriter) -> None:
        writer.flush()
        assert True

    def test_flush_entity_fact(self, writer: KGWriter) -> None:
        writer._buffer.append({
            "type": "entity", "name": "TestCorp", "type_name": "company",
            "description": "A test company", "confidence": 0.8,
            "attributes": {"founded": 2020}, "task_id": "task-1",
        })
        writer.flush()
        conn = writer._get_db()
        row = conn.execute("SELECT name FROM entities").fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "TestCorp"

    def test_flush_claim_fact(self, writer: KGWriter) -> None:
        conn = writer._get_db()
        conn.execute("INSERT INTO entities (id, name, type, task_id) VALUES (1, 'TestCorp', 'company', 'task-1')")
        conn.commit()
        conn.close()
        writer._buffer.append({
            "type": "claim", "statement": "TestCorp raised $10M",
            "entity_name": "TestCorp", "attribute": "funding",
            "confidence": 0.9, "source_urls": ["https://example.com"],
            "task_id": "task-1",
        })
        writer.flush()
        conn = writer._get_db()
        row = conn.execute("SELECT statement FROM claims").fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "TestCorp raised $10M"

    def test_flush_claim_creates_claim_sources(self, writer: KGWriter) -> None:
        conn = writer._get_db()
        conn.execute("INSERT INTO entities (id, name, type, task_id) VALUES (1, 'E', 'type', 't')")
        conn.commit()
        conn.close()
        writer._buffer.append({
            "type": "claim", "statement": "C1", "entity_name": "E",
            "source_urls": ["https://a.com", "https://b.com"], "task_id": "t",
        })
        writer.flush()
        conn = writer._get_db()
        rows = conn.execute("SELECT source_url FROM claim_sources ORDER BY source_url").fetchall()
        conn.close()
        assert len(rows) == 2

    def test_flush_source_fact(self, writer: KGWriter) -> None:
        writer._buffer.append({
            "type": "source", "url": "https://example.com/article",
            "title": "Test Article", "content_hash": "abc123",
            "credibility_score": 0.8, "task_id": "task-1",
        })
        writer.flush()
        conn = writer._get_db()
        row = conn.execute("SELECT url FROM sources").fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "https://example.com/article"

    def test_flush_auto_type_detection(self, writer: KGWriter) -> None:
        conn = writer._get_db()
        conn.execute("INSERT INTO entities (id, name, type, task_id) VALUES (1, 'E1', 'type', 't')")
        conn.commit()
        conn.close()
        writer._buffer.append({"statement": "Auto", "entity_name": "E1", "task_id": "t"})
        writer.flush()
        conn = writer._get_db()
        row = conn.execute("SELECT COUNT(*) FROM claims").fetchone()
        conn.close()
        assert row is not None
        assert row[0] == 1

    def test_flush_multiple_facts(self, writer: KGWriter) -> None:
        conn = writer._get_db()
        conn.execute("INSERT INTO entities (id, name, type, task_id) VALUES (1, 'E1', 'type', 't')")
        conn.commit()
        conn.close()
        writer._buffer.append({"type": "entity", "name": "E2", "task_id": "t"})
        writer._buffer.append({"type": "claim", "statement": "C1", "entity_name": "E1", "task_id": "t"})
        writer._buffer.append({"type": "source", "url": "https://u.com", "task_id": "t"})
        writer.flush()
        conn = writer._get_db()
        assert conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 1
        conn.close()


class TestKGWriterProcessMessage:
    def test_process_json_data(self, writer: KGWriter) -> None:
        msg = {b"data": json.dumps({"task_id": "t1", "facts": [{"name": "E1", "task_id": "t1"}]}).encode()}
        writer._process_message(msg)
        assert len(writer._buffer) == 1

    def test_process_skip_invalid_json(self, writer: KGWriter) -> None:
        msg = {b"data": b"{invalid json}"}
        writer._process_message(msg)
        assert len(writer._buffer) == 0

    def test_process_empty_facts_list(self, writer: KGWriter) -> None:
        msg = {b"data": json.dumps({"facts": [], "task_id": "t1"}).encode()}
        writer._process_message(msg)
        assert len(writer._buffer) == 0
