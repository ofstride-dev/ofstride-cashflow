"""Resume document parsing (adapted from Resume-Matcher onto our stack).

Replaces ``markitdown`` with our existing PDF/DOCX text extraction (PyMuPDF,
docx2txt — both already in ``api/requirements.txt``) and replaces Resume-
Matcher's ``app.llm.complete_json`` with our ``core.llm_factory`` JSON-mode
interface. The date-restoration logic is ported verbatim from the source.
"""

from __future__ import annotations

import json
import logging
import re
from io import BytesIO
from pathlib import Path
from typing import Any

from core.llm_factory import get_llm_factory
from prompts.resume_builder_prompts import (
    PARSE_RESUME_PROMPT,
    PARSE_SYSTEM_PROMPT,
    RESUME_SCHEMA_EXAMPLE,
)
from .resume_schema import ResumeData, normalize_resume_data

logger = logging.getLogger(__name__)

# Matches "Jan 2020 - Dec 2023", "May 2021 - Present", single "Jun 2023".
_MD_DATE_RE = re.compile(
    r"(?:(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?"
    r"|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?"
    r"|Dec(?:ember)?)"
    r"\.?\s+\d{4})"
    r"(?:\s*[-\u2013\u2014]\s*"
    r"(?:(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?"
    r"|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?"
    r"|Dec(?:ember)?)"
    r"\.?\s+\d{4}"
    r"|Present|Current|Now|Ongoing))?",
    re.IGNORECASE,
)


def _extract_markdown_dates(markdown: str) -> list[str]:
    return _MD_DATE_RE.findall(markdown)


def restore_dates_from_markdown(parsed_data: dict[str, Any], markdown: str) -> dict[str, Any]:
    """Patch year-only dates with month-inclusive dates from raw markdown."""
    md_dates = _extract_markdown_dates(markdown)
    if not md_dates:
        return parsed_data

    year_to_full: dict[str, str] = {}
    year_only_re = re.compile(r"\d{4}")
    for md_date in md_dates:
        years_in_date = year_only_re.findall(md_date)
        if years_in_date:
            year_key = " - ".join(years_in_date)
            if year_key not in year_to_full:
                normalized = re.sub(r"\s*[-\u2013\u2014]\s*", " - ", md_date.strip())
                year_to_full[year_key] = normalized

    if not year_to_full:
        return parsed_data

    patched = 0
    for section_key in ("workExperience", "education", "personalProjects"):
        for entry in parsed_data.get(section_key, []):
            if not isinstance(entry, dict):
                continue
            years = entry.get("years", "")
            if not isinstance(years, str) or not years:
                continue
            if re.search(r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)", years, re.IGNORECASE):
                continue
            if years in year_to_full:
                entry["years"] = year_to_full[years]
                patched += 1

    custom = parsed_data.get("customSections", {})
    if isinstance(custom, dict):
        for section in custom.values():
            if not isinstance(section, dict) or section.get("sectionType") != "itemList":
                continue
            for item in section.get("items", []):
                if not isinstance(item, dict):
                    continue
                years = item.get("years", "")
                if not isinstance(years, str) or not years:
                    continue
                if re.search(r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)", years, re.IGNORECASE):
                    continue
                if years in year_to_full:
                    item["years"] = year_to_full[years]
                    patched += 1

    if patched:
        logger.info("Restored months in %d date fields from raw markdown", patched)
    return parsed_data


def _extract_json_object(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        pass
    fenced = re.search(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", text, re.IGNORECASE)
    if fenced:
        try:
            parsed = json.loads(fenced.group(1).strip())
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _first_nonempty_line(text: str) -> str:
    for line in text.splitlines():
        clean = line.strip()
        if clean:
            return clean
    return ""


def _extract_contact(text: str) -> tuple[str, str]:
    email_match = re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", text, re.IGNORECASE)
    phone_match = re.search(r"(?:\+?\d[\d\s().-]{7,}\d)", text)
    email = email_match.group(0).strip() if email_match else ""
    phone = phone_match.group(0).strip() if phone_match else ""
    return email, phone


def _extract_skill_tokens(text: str, max_items: int = 20) -> list[str]:
    common_skills = [
        "python", "java", "javascript", "typescript", "react", "node", "sql", "postgresql",
        "mysql", "mongodb", "azure", "aws", "docker", "kubernetes", "git", "linux",
        "fastapi", "django", "flask", "rest", "api", "power bi", "tableau", "excel",
    ]
    lowered = text.lower()
    seen: set[str] = set()
    out: list[str] = []
    for skill in common_skills:
        if skill in lowered and skill not in seen:
            seen.add(skill)
            out.append(skill.title() if " " not in skill else " ".join(p.capitalize() for p in skill.split()))
            if len(out) >= max_items:
                break
    return out


def _fallback_resume_json(markdown_text: str) -> dict[str, Any]:
    """Best-effort non-LLM parser used when provider calls fail.

    Keeps upload flow functional in local/dev or transient provider outages.
    """
    text = (markdown_text or "").strip()
    name_guess = _first_nonempty_line(text)
    if len(name_guess) > 80:
        name_guess = name_guess[:80].strip()
    email, phone = _extract_contact(text)

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    summary_lines = [ln for ln in lines[:12] if len(ln) >= 30 and "@" not in ln]
    summary = " ".join(summary_lines[:2])[:600] if summary_lines else ""

    skills = _extract_skill_tokens(text)

    fallback = {
        "personalInfo": {
            "name": name_guess,
            "title": "",
            "email": email,
            "phone": phone,
            "location": "",
            "website": None,
            "linkedin": None,
            "github": None,
        },
        "summary": summary,
        "workExperience": [],
        "education": [],
        "personalProjects": [],
        "additional": {
            "technicalSkills": skills,
            "languages": [],
            "certificationsTraining": [],
            "awards": [],
        },
        "sectionMeta": [],
        "customSections": {},
    }
    return normalize_resume_data(fallback)


async def _llm_json(*, system_prompt: str, user_prompt: str, max_tokens: int = 4096) -> dict[str, Any]:
    """Call the LLM factory in JSON mode and parse the result defensively."""
    factory = get_llm_factory()
    selection = await factory.get_healthy_llm_with_metadata()
    client = selection.client
    raw = ""
    try:
        if hasattr(client, "agenerate_json"):
            raw = await client.agenerate_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.0,
                max_tokens=max_tokens,
            )
        else:
            raw = await client.agenerate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.0,
                max_tokens=max_tokens,
            )
        factory.mark_provider_result(selection.provider, success=True)
    except Exception as exc:
        factory.mark_provider_result(selection.provider, success=False)
        detail = str(exc).strip() or exc.__class__.__name__
        raise RuntimeError(f"LLM JSON call failed: {detail}") from exc

    parsed = _extract_json_object(raw)
    if not parsed:
        raise RuntimeError("LLM returned no parseable JSON object.")
    return parsed


def parse_resume_document(content: bytes, filename: str) -> str:
    """Convert a PDF/DOCX/TXT resume to plain text using our existing libs."""
    suffix = Path(filename).suffix.lower()
    if suffix in {".txt", ".md"}:
        return content.decode("utf-8", errors="ignore").strip()

    if suffix == ".pdf":
        try:
            import fitz  # PyMuPDF
        except ImportError as exc:
            raise ValueError("PDF parsing unavailable. Install 'PyMuPDF' (fitz).") from exc
        text_parts: list[str] = []
        with fitz.open(stream=BytesIO(content), filetype="pdf") as doc:
            for page in doc:
                text_parts.append(page.get_text("text") or "")
        return "\n\n".join(p for p in (t.strip() for t in text_parts) if p)

    if suffix in {".docx"}:
        try:
            import docx2txt
        except ImportError as exc:
            raise ValueError("DOCX parsing unavailable. Install 'docx2txt'.") from exc
        extracted = docx2txt.process(BytesIO(content)) or ""
        return extracted.strip()

    if suffix == ".doc":
        # Legacy binary .doc — best-effort text extraction.
        try:
            import docx2txt
            extracted = docx2txt.process(BytesIO(content)) or ""
            if extracted.strip():
                return extracted.strip()
        except Exception:
            pass
        return content.decode("utf-8", errors="ignore").strip()

    raise ValueError(f"Unsupported resume extension: {suffix}")


async def parse_resume_to_json(markdown_text: str) -> dict[str, Any]:
    """Parse resume markdown to structured ResumeData JSON via LLM.

    Falls back to a deterministic local parser if LLM extraction fails.
    """
    prompt = PARSE_RESUME_PROMPT.format(
        schema=RESUME_SCHEMA_EXAMPLE,
        resume_text=markdown_text[:12000],
    )

    try:
        result = await _llm_json(system_prompt=PARSE_SYSTEM_PROMPT, user_prompt=prompt, max_tokens=4096)
        result = restore_dates_from_markdown(result, markdown_text)
        result = normalize_resume_data(result)
        validated = ResumeData.model_validate(result)
        return validated.model_dump()
    except Exception as exc:
        logger.warning("LLM resume parsing unavailable, using fallback parser: %s", exc)
        fallback = _fallback_resume_json(markdown_text)
        validated = ResumeData.model_validate(fallback)
        return validated.model_dump()

