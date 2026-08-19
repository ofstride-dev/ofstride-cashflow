"""
Website content extractor for Ofstride.

NOTE: The Ofstride website is a React SPA (JavaScript-rendered). Standard HTTP
crawling with httpx cannot extract content because the browser never executes the JS.

Instead, this module loads curated content from `ingestion.static_content`, which is
maintained directly from the JSX source files. Update static_content.py whenever
website content changes.

The httpx/BeautifulSoup code is retained as a fallback for any future static pages.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ingestion.parsers import _chunk_text
from ingestion.static_content import get_all_documents, StaticDocument

logger = logging.getLogger("ofstride.crawler")

APPROVED_PAGES: list[str] = [
    "https://ofstride.com/",
    "https://ofstride.com/about",
    "https://ofstride.com/services",
    "https://ofstride.com/industries",
    "https://ofstride.com/contact",
    "https://ofstride.com/book-call",
]


@dataclass
class CrawledPage:
    url: str
    title: str
    description: str
    text: str
    crawled_at: str
    extra_metadata: dict[str, Any] | None = None


async def crawl_approved_pages() -> list[CrawledPage]:
    """
    Load all approved Ofstride content from the static content module.
    Returns CrawledPage objects ready for chunking and ingestion.
    """
    crawled_at = datetime.now(timezone.utc).isoformat()
    results: list[CrawledPage] = []

    for doc in get_all_documents():
        results.append(
            CrawledPage(
                url=doc.url,
                title=doc.title,
                description=f"{doc.section} — {doc.title}",
                text=doc.content,
                crawled_at=crawled_at,
                extra_metadata=doc.metadata if doc.metadata else None,
            )
        )
        logger.info("Loaded static page: %s (%d chars)", doc.title, len(doc.content))

    logger.info("Total static documents loaded: %d", len(results))
    return results


def crawled_page_to_documents(
    page: CrawledPage,
    chunk_size: int = 1400,
    overlap: int = 200,
) -> list[dict[str, Any]]:
    """Split a CrawledPage into chunked documents for vector storage."""
    chunks = _chunk_text(page.text, chunk_size=chunk_size, overlap=overlap)
    chunk_count = len(chunks)
    documents: list[dict[str, Any]] = []

    for idx, chunk in enumerate(chunks):
        meta: dict[str, Any] = {
            "source": page.url,
            "title": page.title,
            "description": page.description,
            "source_type": "website_content",
            "section": "website",
            "chunk_index": idx,
            "chunk_count": chunk_count,
            "last_crawled": page.crawled_at,
        }
        # Merge any extra metadata (e.g. consultant_name, role, location)
        if page.extra_metadata:
            meta.update(page.extra_metadata)

        documents.append({"page_content": chunk, "metadata": meta})

    return documents

