from __future__ import annotations

import contextlib
import logging
import time
import warnings
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any

import httpx
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from argus.shared.config import settings

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)


def _is_retryable_scrape_error(exc: Exception) -> bool:
    """Don't retry on 4xx client errors (won't change outcome)."""
    if isinstance(exc, httpx.HTTPStatusError):
        return not (400 <= exc.response.status_code < 500)
    return True

logger = logging.getLogger(__name__)


@dataclass
class ScrapedContent:
    url: str
    markdown: str
    content_type: str = ""
    content_hash: str = ""
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class ScrapeMetadata:
    provider: str
    latency_ms: int
    cost: float = 0.0


@dataclass
class ScrapeResponse:
    content: ScrapedContent | None = None
    metadata: ScrapeMetadata | None = None


class ScrapeProvider(ABC):
    @abstractmethod
    def scrape(self, url: str) -> ScrapeResponse:
        ...


def _html_to_markdown(html: str, url: str) -> str:  # noqa: ARG001
    soup = BeautifulSoup(html, "lxml")

    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    lines: list[str] = []
    tags = ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "pre", "blockquote", "a"]
    for element in soup.find_all(tags):
        match element.name:
            case "h1":
                lines.append(f"# {element.get_text(strip=True)}")
            case "h2":
                lines.append(f"## {element.get_text(strip=True)}")
            case "h3":
                lines.append(f"### {element.get_text(strip=True)}")
            case "h4":
                lines.append(f"#### {element.get_text(strip=True)}")
            case "h5":
                lines.append(f"##### {element.get_text(strip=True)}")
            case "h6":
                lines.append(f"###### {element.get_text(strip=True)}")
            case "p":
                text = element.get_text(strip=True)
                if text:
                    lines.append(text)
                    lines.append("")
            case "li":
                text = element.get_text(strip=True)
                if text:
                    lines.append(f"- {text}")
            case "pre":
                code = element.get_text()
                lines.append(f"```\n{code}\n```")
            case "blockquote":
                text = element.get_text(strip=True)
                if text:
                    lines.append(f"> {text}")
            case "a":
                href: str = str(element.get("href", ""))
                text = element.get_text(strip=True)
                if text and href and not href.startswith("#"):
                    lines.append(f"[{text}]({href})")

    return "\n".join(lines)


TEXT_CONTENT_TYPES = {
    "text/html", "text/plain", "text/markdown",
    "application/xhtml+xml", "application/xml",
}


class HttpxScraper(ScrapeProvider):
    def __init__(self) -> None:
        self._client = httpx.Client(
            follow_redirects=True,
            timeout=30.0,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )

    @retry(
        stop=stop_after_attempt(settings.llm_retry_max_attempts),
        wait=wait_exponential(
            multiplier=settings.llm_retry_min_wait_seconds,
            max=settings.llm_retry_max_wait_seconds,
        ),
        retry=retry_if_exception(_is_retryable_scrape_error),
    )
    def scrape(self, url: str) -> ScrapeResponse:
        start = time.monotonic()
        try:
            response = self._client.get(url)
            response.raise_for_status()
        except httpx.HTTPStatusError:
            raise
        except Exception:
            return ScrapeResponse(
                metadata=ScrapeMetadata(provider="httpx", latency_ms=0, cost=0.0),
            )

        content_type = response.headers.get("content-type", "").split(";")[0]
        if content_type not in TEXT_CONTENT_TYPES:
            return ScrapeResponse(
                metadata=ScrapeMetadata(provider="httpx", latency_ms=0, cost=0.0),
            )
        html = response.text
        if not html.strip():
            return ScrapeResponse(
                metadata=ScrapeMetadata(provider="httpx", latency_ms=0, cost=0.0),
            )
        markdown = _html_to_markdown(html, url)
        content_hash = sha256(markdown.encode()).hexdigest()

        elapsed_ms = int((time.monotonic() - start) * 1000)

        return ScrapeResponse(
            content=ScrapedContent(
                url=url,
                markdown=markdown,
                content_type=content_type,
                content_hash=content_hash,
            ),
            metadata=ScrapeMetadata(
                provider="httpx",
                latency_ms=elapsed_ms,
                cost=0.0,
            ),
        )


class PlaywrightScraper(ScrapeProvider):
    def __init__(self) -> None:
        self._browser: Any = None  # noqa: ANN401

    def _get_browser(self) -> Any:  # noqa: ANN401
        if self._browser is None:
            try:
                from playwright.sync_api import sync_playwright
                self._pw = sync_playwright().start()
                self._browser = self._pw.chromium.launch(headless=True)
            except ImportError:
                return None
        return self._browser

    def _close_browser(self) -> None:
        if self._browser is not None:
            with contextlib.suppress(Exception):
                self._browser.close()
            self._browser = None
        if hasattr(self, "_pw") and self._pw is not None:
            with contextlib.suppress(Exception):
                self._pw.stop()
            self._pw = None

    @retry(
        stop=stop_after_attempt(settings.llm_retry_max_attempts),
        wait=wait_exponential(
            multiplier=settings.llm_retry_min_wait_seconds,
            max=settings.llm_retry_max_wait_seconds,
        ),
    )
    def scrape(self, url: str) -> ScrapeResponse:
        start = time.monotonic()

        browser = self._get_browser()
        if browser is None:
            return ScrapeResponse(
                metadata=ScrapeMetadata(provider="playwright", latency_ms=0, cost=0.0),
            )

        try:
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            html = page.content()
            page.close()
        except Exception:
            self._close_browser()
            return ScrapeResponse(
                metadata=ScrapeMetadata(provider="playwright", latency_ms=0, cost=0.0),
            )

        markdown = _html_to_markdown(html, url)
        content_hash = sha256(markdown.encode()).hexdigest()
        elapsed_ms = int((time.monotonic() - start) * 1000)

        return ScrapeResponse(
            content=ScrapedContent(
                url=url,
                markdown=markdown,
                content_type="text/html",
                content_hash=content_hash,
            ),
            metadata=ScrapeMetadata(
                provider="playwright",
                latency_ms=elapsed_ms,
                cost=0.0,
            ),
        )


class FirecrawlScraper(ScrapeProvider):
    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        self._api_key = api_key or ""
        self._base_url = (base_url or settings.firecrawl_base_url).rstrip("/") + "/v2"
        self._client = httpx.Client(timeout=30.0)

    @retry(
        stop=stop_after_attempt(settings.llm_retry_max_attempts),
        wait=wait_exponential(
            multiplier=settings.llm_retry_min_wait_seconds,
            max=settings.llm_retry_max_wait_seconds,
        ),
        retry=retry_if_exception(_is_retryable_scrape_error),
    )
    def scrape(self, url: str) -> ScrapeResponse:
        start = time.monotonic()

        response = self._client.post(
            f"{self._base_url}/scrape",
            json={"url": url, "formats": ["markdown"], "onlyMainContent": True},
            headers={"Authorization": f"Bearer {self._api_key}"},
        )
        response.raise_for_status()
        data: dict[str, Any] = response.json()  # noqa: ANN401

        elapsed_ms = int((time.monotonic() - start) * 1000)
        markdown = ""
        if "data" in data:
            markdown = data["data"].get("markdown", "")
        content_hash = sha256(markdown.encode()).hexdigest()

        return ScrapeResponse(
            content=ScrapedContent(
                url=url,
                markdown=markdown,
                content_type="text/markdown",
                content_hash=content_hash,
            ),
            metadata=ScrapeMetadata(
                provider="firecrawl",
                latency_ms=elapsed_ms,
                cost=0.003,
            ),
        )


class WebScraper:
    """Web scraper with httpx+BS4 as primary, Playwright and Firecrawl as fallbacks."""

    def __init__(self) -> None:
        self._httpx = HttpxScraper()
        self._playwright = PlaywrightScraper()
        self._firecrawl: FirecrawlScraper | None = None

    def scrape(self, url: str) -> ScrapeResponse:
        errors: list[str] = []

        result = self._httpx.scrape(url)
        if result.content and result.content.markdown.strip():
            return result
        errors.append("httpx: no content returned")

        result = self._playwright.scrape(url)
        if result.content and result.content.markdown.strip():
            return result
        errors.append("playwright: no content returned")

        if settings.firecrawl_api_key:
            self._firecrawl = FirecrawlScraper(
                api_key=settings.firecrawl_api_key,
                base_url=settings.firecrawl_base_url,
            )
            result = self._firecrawl.scrape(url)
            if result.content and result.content.markdown.strip():
                return result
            errors.append("firecrawl: no content returned")
        else:
            errors.append("firecrawl: not configured")

        logger.warning("All scrapers failed", extra={"url": url, "errors": "; ".join(errors)})
        return result
