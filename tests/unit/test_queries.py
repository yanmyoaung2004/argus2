from __future__ import annotations

import sqlite3

import pytest

from argus.services.knowledge_graph.queries import (
    find_conflicts,
    get_claims_for_entity,
    get_entity,
    get_provenance_chain,
    search_claims,
)
from argus.services.knowledge_graph.schema import init_db


@pytest.fixture
def db() -> sqlite3.Connection:
    conn = init_db(":memory:")
    conn.execute("INSERT INTO entities (id, name, type, task_id) VALUES (1, 'E1', 'company', 't1')")
    conn.execute("INSERT INTO entities (id, name, type, task_id) VALUES (2, 'E2', 'person', 't1')")
    conn.execute(
        "INSERT INTO claims (id, statement, entity_id, attribute, confidence, task_id) VALUES "
        "(10, 'Claim 1', 1, 'attr1', 0.9, 't1'),"
        "(11, 'Claim 2', 1, 'attr2', 0.7, 't1'),"
        "(12, 'Claim 3', 2, 'attr1', 0.5, 't1')"
    )
    conn.execute("INSERT INTO sources (id, url, title, task_id) VALUES (100, 'https://a.com', 'Source A', 't1')")
    conn.commit()
    return conn


class TestGetEntity:
    def test_returns_entity(self, db: sqlite3.Connection) -> None:
        row = get_entity(db, 1)
        assert row is not None
        assert row["name"] == "E1"

    def test_returns_none_for_missing(self, db: sqlite3.Connection) -> None:
        assert get_entity(db, 999) is None


class TestGetClaimsForEntity:
    def test_returns_claims(self, db: sqlite3.Connection) -> None:
        claims = get_claims_for_entity(db, 1)
        assert len(claims) == 2

    def test_ordered_by_confidence_desc(self, db: sqlite3.Connection) -> None:
        claims = get_claims_for_entity(db, 1)
        assert claims[0]["confidence"] >= claims[1]["confidence"]

    def test_no_claims_returns_empty(self, db: sqlite3.Connection) -> None:
        assert get_claims_for_entity(db, 999) == []


class TestGetProvenanceChain:
    def test_returns_chain(self, db: sqlite3.Connection) -> None:
        chain = get_provenance_chain(db, 10)
        assert len(chain) > 0

    def test_includes_entity(self, db: sqlite3.Connection) -> None:
        chain = get_provenance_chain(db, 10)
        assert any("E1" in str(r) for r in chain)


class TestFindConflicts:
    def test_detects_conflicts(self, db: sqlite3.Connection) -> None:
        conflicts = find_conflicts(db, "t1")
        assert isinstance(conflicts, list)

    def test_returns_empty_without_conflicts(self, db: sqlite3.Connection) -> None:
        conflicts = find_conflicts(db, "empty-task")
        assert conflicts == []


class TestSearchClaims:
    def test_fts_search_finds_claims(self, db: sqlite3.Connection) -> None:
        results = search_claims(db, "Claim")
        assert len(results) >= 1

    def test_fts_search_empty_for_no_match(self, db: sqlite3.Connection) -> None:
        results = search_claims(db, "zzzznotfound")
        assert results == []
