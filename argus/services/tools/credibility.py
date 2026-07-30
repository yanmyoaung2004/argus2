from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from argus.shared.config import settings

AUTHORITATIVE_DOMAINS: set[str] = {
    d.strip() for d in settings.authoritative_domains.split(",") if d.strip()
} or {
    "wikipedia.org", "britannica.com", "reuters.com", "ap.org",
    "bbc.com", "bbc.co.uk", "nature.com", "science.org",
    "nih.gov", "who.int", "un.org", "worldbank.org",
    "scholar.google.com", "arxiv.org", "ieee.org", "acm.org",
}


@dataclass
class SourceCredibilityScorer:
    domain_weights: dict[str, float] = field(
        default_factory=lambda: dict.fromkeys(AUTHORITATIVE_DOMAINS, 0.9)
    )
    default_weight: float = 0.5
    boost_per_citation: float = 0.05
    penalty_per_conflict: float = -0.05
    boost_post_research: float = 0.05
    penalty_post_research: float = -0.05
    user_feedback_boost: float = 0.15
    user_feedback_penalty: float = -0.15
    max_score: float = 1.0
    min_score: float = 0.0

    def score_domain(self, url: str) -> float:
        url_lower = url.lower()
        for domain, weight in self.domain_weights.items():
            if domain in url_lower:
                return weight
        return self.default_weight

    def update_on_citation(self, current_score: float) -> float:
        return min(self.max_score, current_score + self.boost_per_citation)

    def update_on_conflict(self, current_score: float) -> float:
        return max(self.min_score, current_score + self.penalty_per_conflict)

    def calculate(self, url: str, citation_count: int = 0, conflict_count: int = 0) -> float:
        score = self.score_domain(url)
        score += citation_count * self.boost_per_citation
        score += conflict_count * self.penalty_per_conflict
        return max(self.min_score, min(self.max_score, score))

    def apply_research_feedback(
        self, conn: sqlite3.Connection, task_id: str,
    ) -> int:
        rows = conn.execute(
            """SELECT DISTINCT s.id, s.url, s.credibility_score
               FROM sources s
               WHERE s.task_id = ?""",
            (task_id,),
        ).fetchall()

        updated = 0
        for source_id, url, current_score in rows:
            conflict_count = conn.execute(
                """SELECT COUNT(*) FROM claims c
                   JOIN claims c2 ON c.entity_id = c2.entity_id
                                 AND c.attribute = c2.attribute
                                 AND c.id != c2.id
                   JOIN claim_sources cs ON cs.claim_id = c.id
                   WHERE cs.task_id = ? AND cs.source_url = ?""",
                (task_id, url),
            ).fetchone()
            has_conflicts = (conflict_count[0] if conflict_count else 0) > 0

            boost_count = conn.execute(
                """SELECT COUNT(*) FROM claims c
                   JOIN claim_sources cs ON cs.claim_id = c.id
                   WHERE cs.task_id = ? AND cs.source_url = ? AND c.confidence >= 0.8""",
                (task_id, url),
            ).fetchone()
            has_high_confidence = (boost_count[0] if boost_count else 0) > 0

            new_score = current_score
            if has_high_confidence:
                new_score = self.update_on_citation(current_score)
            if has_conflicts:
                new_score = self.update_on_conflict(new_score)

            if abs(new_score - current_score) > 0.001:
                conn.execute(
                    "UPDATE sources SET credibility_score = ? WHERE id = ?",
                    (new_score, source_id),
                )
                updated += 1

        if updated:
            conn.commit()
        return updated

    def apply_user_feedback(
        self, conn: sqlite3.Connection, source_id: int, is_correct: bool,
    ) -> float:
        row = conn.execute(
            "SELECT credibility_score FROM sources WHERE id = ?",
            (source_id,),
        ).fetchone()
        if row is None or row[0] is None:
            return 0.0

        current = float(row[0])
        delta = self.user_feedback_boost if is_correct else self.user_feedback_penalty
        new_score = max(self.min_score, min(self.max_score, current + delta))
        conn.execute(
            "UPDATE sources SET credibility_score = ? WHERE id = ?",
            (new_score, source_id),
        )
        conn.commit()
        return new_score
