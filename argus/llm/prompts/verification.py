from __future__ import annotations

from typing import Any


def check_conflict(claim_a: dict[str, Any], claim_b: dict[str, Any], query_hint: str = "") -> str:
    query_context = f"\nResearch context: {query_hint}\n" if query_hint else ""
    return (
        f"Determine if the following two claims are contradictory, "
        f"supportive, or unrelated. Return a JSON object with keys: "
        f"relationship (contradictory/supportive/unrelated), reason."
        f"{query_context}"
        f"Claim A: {claim_a.get('statement', '')}\n"
        f"Source A: {claim_a.get('source_urls', [])}\n\n"
        f"Claim B: {claim_b.get('statement', '')}\n"
        f"Source B: {claim_b.get('source_urls', [])}"
    )
