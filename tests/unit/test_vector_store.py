from __future__ import annotations

import sqlite3

import pytest

from argus.services.memory.vector_store import (
    EMBEDDING_DIM,
    _mock_embedding,
    ensure_all_tables,
    ensure_vec_table,
    upsert_entity_embedding,
    find_similar_entities,
    reindex_entity_embeddings,
    load_vec,
)


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    load_vec(c)
    ensure_all_tables(c)
    return c


class TestVectorStoreInit:
    def test_embedding_dim(self) -> None:
        assert EMBEDDING_DIM == 384

    def test_load_vec_creates_functions(self, conn: sqlite3.Connection) -> None:
        row = conn.execute("SELECT vec_version()").fetchone()
        assert row is not None

    def test_ensure_vec_table_creates(self, conn: sqlite3.Connection) -> None:
        conn.execute("SELECT COUNT(*) FROM vec_entities").fetchone()
        assert True


class TestMockEmbedding:
    def test_returns_list_of_correct_length(self) -> None:
        emb = _mock_embedding("test")
        assert len(emb) == EMBEDDING_DIM

    def test_consistent_for_same_input(self) -> None:
        e1 = _mock_embedding("hello world")
        e2 = _mock_embedding("hello world")
        assert e1 == e2

    def test_different_for_different_input(self) -> None:
        e1 = _mock_embedding("hello")
        e2 = _mock_embedding("world")
        assert e1 != e2


class TestUpsertEntityEmbedding:
    def test_upsert_and_find(self, conn: sqlite3.Connection) -> None:
        emb = _mock_embedding("entity1")
        upsert_entity_embedding(conn, 1, emb)
        results = find_similar_entities(conn, emb, k=5)
        assert len(results) == 1
        assert results[0]["entity_id"] == 1

    def test_find_similar_no_results(self, conn: sqlite3.Connection) -> None:
        emb = _mock_embedding("nonexistent")
        results = find_similar_entities(conn, emb, k=5)
        assert results == []

    def test_upsert_then_delete_then_reinsert(self, conn: sqlite3.Connection) -> None:
        emb = _mock_embedding("test")
        upsert_entity_embedding(conn, 1, emb)
        results1 = find_similar_entities(conn, emb, k=5)
        assert len(results1) == 1
        conn.execute("DELETE FROM vec_entities WHERE rowid = 1")
        conn.commit()
        results2 = find_similar_entities(conn, emb, k=5)
        assert len(results2) == 0


class TestReindexEntityEmbeddings:
    def test_returns_zero_when_no_entities(self, conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE IF NOT EXISTS entities (id INTEGER PRIMARY KEY, name TEXT, description TEXT, confidence REAL, task_id TEXT)")
        conn.commit()
        count = reindex_entity_embeddings(conn)
        assert count == 0

    def test_reindexes_all_entities(self, conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE IF NOT EXISTS entities (id INTEGER PRIMARY KEY, name TEXT, description TEXT, confidence REAL, task_id TEXT)")
        conn.execute("INSERT INTO entities (id, name, description) VALUES (1, 'E1', 'desc1')")
        conn.execute("INSERT INTO entities (id, name, description) VALUES (2, 'E2', 'desc2')")
        conn.commit()
        count = reindex_entity_embeddings(conn)
        assert count == 2
