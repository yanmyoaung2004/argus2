from __future__ import annotations

from argus.services.tools.search import SearchResult, SearchResponse, SearchMetadata


class TestSearchDataClasses:
    def test_search_result(self) -> None:
        r = SearchResult(url="https://a.com", title="Title A", snippet="Snippet A")
        assert r.url == "https://a.com"
        assert r.title == "Title A"
        assert r.snippet == "Snippet A"

    def test_search_response_defaults(self) -> None:
        r = SearchResponse()
        assert r.results == []
        assert r.metadata is None

    def test_search_response_with_results(self) -> None:
        results = [
            SearchResult(url="https://a.com", title="A", snippet="a"),
            SearchResult(url="https://b.com", title="B", snippet="b"),
        ]
        meta = SearchMetadata(provider="test", total_results=2, latency_ms=10)
        r = SearchResponse(results=results, metadata=meta)
        assert len(r.results) == 2
        assert r.metadata is not None
        assert r.metadata.provider == "test"
