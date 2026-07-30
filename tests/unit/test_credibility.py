from __future__ import annotations

import sqlite3

import pytest

from argus.services.knowledge_graph.schema import init_db
from argus.services.tools.credibility import SourceCredibilityScorer


@pytest.fixture
def scorer() -> SourceCredibilityScorer:
    return SourceCredibilityScorer()


@pytest.fixture
def db() -> sqlite3.Connection:
    conn = init_db(":memory:")
    conn.execute(
        "INSERT INTO sources (id, url, title, credibility_score, task_id) VALUES "
        "(1, 'https://a.com', 'Source A', 0.7, 'task-1'),"
        "(2, 'https://b.com', 'Source B', 0.5, 'task-1')"
    )
    conn.execute(
        "INSERT INTO entities (id, name, type, task_id) VALUES (1, 'TestEnt', 'company', 'task-1')"
    )
    conn.execute(
        "INSERT INTO claims (id, statement, confidence, entity_id, source_urls, task_id) VALUES "
        "(1, 'Claim A', 0.9, 1, '[\"https://a.com\"]', 'task-1'),"
        "(2, 'Claim B', 0.4, 1, '[\"https://b.com\"]', 'task-1')"
    )
    conn.execute(
        "INSERT INTO claim_sources (claim_id, source_url, task_id) VALUES "
        "(1, 'https://a.com', 'task-1'),"
        "(2, 'https://b.com', 'task-1')"
    )
    conn.commit()
    return conn


class TestScoreDomain:
    def test_authoritative_domain(self, scorer: SourceCredibilityScorer) -> None:
        assert scorer.score_domain("https://en.wikipedia.org/wiki/AI") == 0.9

    def test_default_domain(self, scorer: SourceCredibilityScorer) -> None:
        assert scorer.score_domain("https://example.com") == 0.5

    def test_subdomain_authoritative(self, scorer: SourceCredibilityScorer) -> None:
        assert scorer.score_domain("https://news.bbc.com/article") == 0.9


class TestCalculate:
    def test_basic_calculation(self, scorer: SourceCredibilityScorer) -> None:
        score = scorer.calculate("https://example.com")
        assert score == 0.5

    def test_citation_boost(self, scorer: SourceCredibilityScorer) -> None:
        score = scorer.calculate("https://example.com", citation_count=3)
        assert score == 0.65

    def test_conflict_penalty(self, scorer: SourceCredibilityScorer) -> None:
        score = scorer.calculate("https://example.com", conflict_count=2)
        assert score == 0.4

    def test_clamped_max(self, scorer: SourceCredibilityScorer) -> None:
        score = scorer.calculate("https://reuters.com", citation_count=100)
        assert score <= 1.0

    def test_clamped_min(self, scorer: SourceCredibilityScorer) -> None:
        score = scorer.calculate("https://example.com", conflict_count=100)
        assert score >= 0.0


class TestApplyResearchFeedback:
    def test_boost_high_confidence_source(self, scorer: SourceCredibilityScorer, db: sqlite3.Connection) -> None:
        scorer.apply_research_feedback(db, "task-1")
        row = db.execute("SELECT credibility_score FROM sources WHERE id = 1").fetchone()
        assert row is not None
        assert row[0] == pytest.approx(0.75, rel=1e-2)

    def test_penalty_low_confidence_source(self, scorer: SourceCredibilityScorer, db: sqlite3.Connection) -> None:
        scorer.apply_research_feedback(db, "task-1")
        row = db.execute("SELECT credibility_score FROM sources WHERE id = 2").fetchone()
        assert row is not None
        assert row[0] == 0.5  # no conflict detected, no update

    def test_no_changes_for_empty_task(self, scorer: SourceCredibilityScorer, db: sqlite3.Connection) -> None:
        updated = scorer.apply_research_feedback(db, "nonexistent")
        assert updated == 0


class TestApplyUserFeedback:
    def test_positive_feedback_increases_score(self, scorer: SourceCredibilityScorer, db: sqlite3.Connection) -> None:
        new = scorer.apply_user_feedback(db, 1, True)
        row = db.execute("SELECT credibility_score FROM sources WHERE id = 1").fetchone()
        assert row is not None
        assert row[0] == new
        assert new == pytest.approx(0.85, rel=1e-2)

    def test_negative_feedback_decreases_score(self, scorer: SourceCredibilityScorer, db: sqlite3.Connection) -> None:
        new = scorer.apply_user_feedback(db, 1, False)
        assert new == pytest.approx(0.55, rel=1e-2)

    def test_nonexistent_source_returns_zero(self, scorer: SourceCredibilityScorer, db: sqlite3.Connection) -> None:
        assert scorer.apply_user_feedback(db, 999, True) == 0.0
