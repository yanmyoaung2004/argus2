from __future__ import annotations

from typing import Any

from argus.shared.config import settings


def generate_synthesis(query: str, entities: list[Any], claims: list[Any]) -> str:
    ctx = f" for the query: {query}" if query else ""
    entity_block = "\n".join(
        f"- {e[0]} ({e[1]}): {e[2] or 'no description'}" for e in entities[:settings.synthesis_max_entities]
    ) if entities else "None found"
    claim_block = "\n".join(
        f"- [{c[1]:.0%} confidence] {c[0]} (entity: {c[2]}, attribute: {c[3]})"
        for c in claims[:settings.synthesis_max_claims]
    ) if claims else "None found"
    return (
        f"Synthesize the research findings{ctx}.\n\n"
        f"Entities found:\n{entity_block}\n\n"
        f"Claims extracted:\n{claim_block}\n\n"
        f"Provide a concise synthesis covering:\n"
        f"1. Key entities and their roles\n"
        f"2. Main findings and facts\n"
        f"3. Any contradictions or uncertainties\n"
        f"4. Overall conclusion\n\n"
        f"Return your synthesis as plain text with markdown formatting."
    )


def ask_merge(name_a: str, name_b: str) -> str:
    return (
        f"Do these two entity names refer to the same real-world entity?\n"
        f"Entity A: '{name_a}'\nEntity B: '{name_b}'\n"
        f"Answer ONLY with 'yes' or 'no'."
    )
