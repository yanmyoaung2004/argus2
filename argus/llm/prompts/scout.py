from __future__ import annotations

from argus.services.tools.search import SearchResult


def analyze_results(query: str, results: list[SearchResult]) -> str:
    formatted = []
    for i, r in enumerate(results, start=1):
        formatted.append(f"{i}. URL: {r.url}\n   Title: {r.title}\n   Snippet: {r.snippet}")
    return (
        f"You are a research scout analyzing search results for the query: \"{query}\"\n\n"
        f"For each search result below, determine if it's relevant to the research query. "
        f"Return a JSON array of objects with keys:\n"
        f"- url: the URL\n"
        f"- title: the title\n"
        f"- relevance: \"high\" / \"medium\" / \"low\"\n"
        f"- extracted_entities: array of objects with keys name, type, description\n\n"
        f"Search results:\n" + "\n".join(formatted)
    )
