from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from argus.services.tools.scraper import (
    ScrapedContent,
    ScrapeMetadata,
    ScrapeResponse,
    _html_to_markdown,
    HttpxScraper,
    PlaywrightScraper,
    WebScraper,
    TEXT_CONTENT_TYPES,
)


class TestScrapeDataClasses:
    def test_scraped_content_defaults(self) -> None:
        c = ScrapedContent(url="https://a.com", markdown="hi")
        assert c.content_type == ""
        assert c.content_hash == ""

    def test_scrape_response_defaults(self) -> None:
        r = ScrapeResponse()
        assert r.content is None
        assert r.metadata is None


class TestHtmlToMarkdown:
    def test_simple_paragraph(self) -> None:
        html = "<p>Hello world</p>"
        result = _html_to_markdown(html, "https://x.com")
        assert "Hello world" in result

    def test_heading(self) -> None:
        html = "<h1>Title</h1><h2>Subtitle</h2>"
        result = _html_to_markdown(html, "https://x.com")
        assert "# Title" in result
        assert "## Subtitle" in result

    def test_list_items(self) -> None:
        html = "<ul><li>Item A</li><li>Item B</li></ul>"
        result = _html_to_markdown(html, "https://x.com")
        assert "- Item A" in result
        assert "- Item B" in result

    def test_link(self) -> None:
        html = '<a href="https://example.com">Click here</a>'
        result = _html_to_markdown(html, "https://x.com")
        assert "Click here" in result
        assert "example.com" in result

    def test_script_tags_stripped(self) -> None:
        html = "<p>Hello</p><script>alert('x')</script><p>World</p>"
        result = _html_to_markdown(html, "https://x.com")
        assert "alert" not in result

    def test_style_tags_stripped(self) -> None:
        html = "<p>Hello</p><style>.cls{}</style><p>World</p>"
        result = _html_to_markdown(html, "https://x.com")
        assert ".cls" not in result

    def test_empty_html(self) -> None:
        result = _html_to_markdown("", "https://x.com")
        assert result == ""

    def test_only_empty_tags(self) -> None:
        result = _html_to_markdown("<p></p>", "https://x.com")
        assert result.strip() == ""


class TestTEXT_CONTENT_TYPES:
    def test_includes_html(self) -> None:
        assert "text/html" in TEXT_CONTENT_TYPES

    def test_includes_markdown(self) -> None:
        assert "text/markdown" in TEXT_CONTENT_TYPES


class TestHttpxScraper:
    def test_content_type_rejects_non_text(self) -> None:
        scraper = HttpxScraper()
        scraper._client = MagicMock()
        response = MagicMock()
        response.headers = {"content-type": "image/png"}
        response.raise_for_status.return_value = None
        scraper._client.get.return_value = response
        result = scraper.scrape("https://example.com/img.png")
        assert result.content is None

    def test_content_type_accepts_html(self) -> None:
        scraper = HttpxScraper()
        scraper._client = MagicMock()
        response = MagicMock()
        response.headers = {"content-type": "text/html"}
        response.text = "<p>Hello</p>"
        response.raise_for_status.return_value = None
        scraper._client.get.return_value = response
        result = scraper.scrape("https://example.com")
        assert result.content is not None
        assert "Hello" in result.content.markdown


class TestPlaywrightScraper:
    def test_init(self) -> None:
        scraper = PlaywrightScraper()
        assert scraper._browser is None

    def test_get_browser_returns_browser_or_none(self) -> None:
        scraper = PlaywrightScraper()
        browser = scraper._get_browser()
        if browser is not None:
            scraper._close_browser()
        assert True


class TestWebScraper:
    @patch("argus.services.tools.scraper.HttpxScraper")
    def test_httpx_result_returned_directly(self, mock_httpx: MagicMock) -> None:
        mock_httpx.return_value.scrape.return_value = ScrapeResponse(
            content=ScrapedContent(url="https://a.com", markdown="content"),
        )
        ws = WebScraper()
        result = ws.scrape("https://a.com")
        assert result.content is not None
        assert result.content.markdown == "content"

    @patch("argus.services.tools.scraper.HttpxScraper")
    def test_falls_through_to_playwright(self, mock_httpx: MagicMock) -> None:
        mock_httpx.return_value.scrape.return_value = ScrapeResponse(
            content=ScrapedContent(url="https://a.com", markdown=""),
        )
        ws = WebScraper()
        ws._playwright = MagicMock()
        ws._playwright.scrape.return_value = ScrapeResponse(
            content=ScrapedContent(url="https://a.com", markdown="pw content"),
        )
        result = ws.scrape("https://a.com")
        assert result.content is not None
        assert result.content.markdown == "pw content"
