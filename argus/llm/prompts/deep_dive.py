from __future__ import annotations

from argus.shared.config import settings


def extract_batch(sources: list[dict[str, str]], query: str = "") -> str:
    max_chars = settings.deep_dive_max_content_chars
    lines: list[str] = [
        "Extract factual claims from the following sources. "
        "For each claim, identify: the statement, the entity it refers to, "
        "and a confidence level (high/medium/low). "
        "Return the results as a JSON list of objects with keys: "
        "statement, entity_name, attribute, confidence.",
        "",
    ]
    if query:
        lines.insert(2, f"Research context: {query}")
        lines.insert(3, "")
    for i, src in enumerate(sources, start=1):
        lines.append(f"--- Source {i} ---")
        lines.append(f"URL: {src.get('url', 'unknown')}")
        lines.append(f"Title: {src.get('title', '')}")
        lines.append(f"Content:\n{src.get('content', '')[:max_chars]}")
        lines.append("")
    return "\n".join(lines)


def extract_single(src: dict[str, str], query: str = "") -> str:
    max_chars = settings.deep_dive_max_content_chars
    ctx = f"Research context: {query}\n\n" if query else ""
    return (
        f"{ctx}Extract factual claims from this source.\n"
        f"URL: {src['url']}\n"
        f"Content:\n{src['content'][:max_chars]}\n\n"
        f"Return a JSON list of objects with keys: statement, entity_name, attribute."
    )
