from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.settings import API_ROOT, get_settings
from ingestion.parsers import _chunk_text
from ingestion.parsers import parse_file
from ingestion.static_content import get_all_documents
from knowledge.company_profile import get_company_profile_context
from knowledge.service_catalog import get_service_catalog

logger = logging.getLogger("ofstride.codebase_kb")


_SEED_LOCK = asyncio.Lock()
_LAST_HASH: str | None = None


def _runtime_dir() -> Path:
    settings = get_settings()
    return Path(settings.durable_sqlite_path).parent


def _state_file() -> Path:
    return _runtime_dir() / "kb_seed_state.json"


def _markdown_file() -> Path:
    return API_ROOT / "data" / "generated_website_kb.md"


def _jsonl_file() -> Path:
    return API_ROOT / "data" / "generated_website_kb.jsonl"


def _build_markdown() -> str:
    now = datetime.now(timezone.utc).isoformat()
    docs = get_all_documents()
    services_text = get_service_catalog().get_services_text().strip()
    company_context = get_company_profile_context().strip()

    lines: list[str] = []
    lines.append("# Ofstride Website Knowledge Base")
    lines.append("")
    lines.append(f"GeneratedAt: {now}")
    lines.append("Source: codebase_static_content")
    lines.append("")

    lines.append("## Company Profile")
    lines.append(company_context)
    lines.append("")

    lines.append("## Service Catalog")
    lines.append(services_text or "(service catalog unavailable)")
    lines.append("")

    lines.append("## Curated Website Content")
    lines.append("")
    for idx, doc in enumerate(docs, start=1):
        lines.append(f"### Document {idx}: {doc.title}")
        lines.append(f"Url: {doc.url}")
        lines.append(f"Section: {doc.section}")
        lines.append(doc.content.strip())
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def _infer_page_type(section: str) -> str:
    normalized = (section or "").strip().lower()
    if normalized in {"services", "service"}:
        return "service"
    if normalized in {"team", "consultants"}:
        return "profile"
    if normalized in {"faq", "faqs"}:
        return "faq"
    if normalized in {"contact", "book-call"}:
        return "cta"
    return "page"


def _build_structured_records() -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc).isoformat()
    records: list[dict[str, Any]] = []

    for doc in get_all_documents():
        base_meta = {
            "url": doc.url,
            "section_heading": doc.section,
            "page_type": _infer_page_type(doc.section),
            "source_system": "ofstride_static_content",
            "publish_date": now,
            "updated_at": now,
            "source_priority": 2,
        }
        if isinstance(doc.metadata, dict):
            base_meta.update(doc.metadata)

        records.append(
            {
                "title": doc.title,
                "content": doc.content.strip(),
                "metadata": base_meta,
            }
        )

    return records


def _write_jsonl(records: list[dict[str, Any]]) -> Path:
    path = _jsonl_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in records:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")
    return path


def _compute_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _load_state() -> dict[str, Any]:
    path = _state_file()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: dict[str, Any]) -> None:
    path = _state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=True, indent=2), encoding="utf-8")


def get_codebase_kb_status() -> dict[str, Any]:
    state = _load_state()
    md_path = _markdown_file()
    jsonl_path = _jsonl_file()
    return {
        "state": state,
        "markdown_exists": md_path.exists(),
        "markdown_file": str(md_path),
        "jsonl_exists": jsonl_path.exists(),
        "jsonl_file": str(jsonl_path),
    }


async def ensure_codebase_kb_seeded(store) -> dict[str, Any]:
    """
    Build generated markdown from codebase content and seed vector store when changed.
    Also runs a lightweight retrieval validation loop after ingestion.
    """
    global _LAST_HASH

    async with _SEED_LOCK:
        markdown = _build_markdown()
        content_hash = _compute_hash(markdown)

        state = _load_state()
        if _LAST_HASH == content_hash and state.get("content_hash") == content_hash:
            return {
                "seeded": False,
                "reason": "already_seeded_in_process",
                "content_hash": content_hash,
                "validation": state.get("validation", {}),
            }

        if state.get("content_hash") == content_hash and state.get("indexed") is True:
            _LAST_HASH = content_hash
            return {
                "seeded": False,
                "reason": "already_seeded",
                "content_hash": content_hash,
                "validation": state.get("validation", {}),
            }

        md_path = _markdown_file()
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(markdown, encoding="utf-8")

        parsed_docs = list(parse_file(markdown.encode("utf-8"), md_path.name))
        structured_records = _build_structured_records()
        jsonl_path = _write_jsonl(structured_records)

        docs_to_store: list[dict[str, Any]] = []

        # Markdown chunks for long-form semantic retrieval.
        for parsed in parsed_docs:
            docs_to_store.append(
                {
                    "content": parsed.content,
                    "metadata": {
                        **parsed.metadata,
                        "source": md_path.name,
                        "source_type": "website_content",
                        "section": "generated_kb",
                        "page_type": "markdown_kb",
                        "source_system": "codebase_static_content",
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                        "content_hash": content_hash,
                        "ingested_at": datetime.now(timezone.utc).isoformat(),
                    },
                }
            )

        # Structured section records (JSONL) for metadata-filtered retrieval.
        for record in structured_records:
            metadata = dict(record.get("metadata", {}) or {})
            text = str(record.get("content", "")).strip()
            title = str(record.get("title", "")).strip()
            if title:
                text = f"{title}\n\n{text}" if text else title

            chunks = _chunk_text(
                text=text,
                chunk_size=get_settings().ingest_chunk_size,
                overlap=get_settings().ingest_chunk_overlap,
            )
            for idx, chunk in enumerate(chunks):
                docs_to_store.append(
                    {
                        "content": chunk,
                        "metadata": {
                            "source": jsonl_path.name,
                            "source_type": "website_structured",
                            "title": title,
                            "chunk_index": idx,
                            "chunk_count": len(chunks),
                            "content_hash": content_hash,
                            "ingested_at": datetime.now(timezone.utc).isoformat(),
                            **metadata,
                        },
                    }
                )

        await store.ensure_collection()
        added = await store.add_documents(docs_to_store)

        validation_queries = [
            "what services do you offer",
            "virtual cfo",
            "hr consulting",
            "book a discovery call",
        ]
        validation: dict[str, Any] = {}
        passed = True
        for query in validation_queries:
            hits = await store.similarity_search(
                query=query,
                k=2,
                filters={"source_type": {"$in": ["website_content", "consultant_profile", "consultant_data"]}},
            )
            hit_count = len(hits)
            validation[query] = hit_count
            if hit_count <= 0:
                passed = False

        state = {
            "indexed": True,
            "content_hash": content_hash,
            "documents_added": added,
            "last_seeded_at": datetime.now(timezone.utc).isoformat(),
            "validation": {
                "passed": passed,
                "query_hits": validation,
            },
            "markdown_file": str(md_path),
            "jsonl_file": str(jsonl_path),
        }
        _save_state(state)
        _LAST_HASH = content_hash

        logger.info(
            "codebase_kb_seeded docs=%d hash=%s validation_passed=%s",
            added,
            content_hash[:10],
            passed,
        )

        return {
            "seeded": True,
            "content_hash": content_hash,
            "documents_added": added,
            "validation": state["validation"],
            "markdown_file": str(md_path),
            "jsonl_file": str(jsonl_path),
        }
