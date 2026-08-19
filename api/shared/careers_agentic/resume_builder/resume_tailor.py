"""Resume tailoring pipeline (diff-based improvement + ATS scoring).

Ported/adapted from Resume-Matcher's improver/refiner onto our stack. The
pipeline is:
  1. Extract structured JD keywords (LLM, regex fallback).
  2. Ask the LLM for targeted ``ResumeChange`` diffs (no full rewrite — keeps
     changes auditable and prevents hallucination).
  3. Apply diffs to the master resume with an ``original`` verification gate.
  4. Recompute keyword coverage and the ATS sub-score breakdown.

Separation: this module owns *tailoring logic only* — persistence and HTTP
transport live in ``resume_builder_store`` and ``routes`` respectively.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from core.llm_factory import get_llm_factory
from prompts.resume_builder_prompts import (
    EXTRACT_JD_KEYWORDS_PROMPT,
    IMPROVE_DIFF_PROMPT,
)
from .ats_scorer import compute_ats_score
from .resume_parser import _extract_json_object, _llm_json
from .resume_schema import ResumeChange, ResumeData

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"([^\[\].]+)|\[(\d+)\]")


def _parse_path(path: str) -> list[tuple[str, str | int]]:
    tokens: list[tuple[str, str | int]] = []
    for m in _TOKEN_RE.finditer(path):
        if m.group(1) is not None:
            tokens.append(("key", m.group(1)))
        else:
            tokens.append(("index", int(m.group(2))))
    return tokens


def _step(obj: Any, token: tuple[str, str | int]) -> Any:
    kind, val = token
    if kind == "key":
        return obj[val] if isinstance(obj, dict) and val in obj else None
    if isinstance(obj, list) and isinstance(val, int) and 0 <= val < len(obj):
        return obj[val]
    return None


def _get_at_path(root: dict[str, Any], path: str) -> Any:
    cur: Any = root
    for token in _parse_path(path):
        if cur is None:
            return None
        cur = _step(cur, token)
    return cur


def _parent_and_accessor(root: dict[str, Any], path: str) -> tuple[Any, tuple[str, str | int]]:
    tokens = _parse_path(path)
    cur: Any = root
    for token in tokens[:-1]:
        if cur is None:
            return None, token
        cur = _step(cur, token)
    return cur, tokens[-1]


def _set_at_path(root: dict[str, Any], path: str, value: Any) -> bool:
    parent, accessor = _parent_and_accessor(root, path)
    if parent is None:
        return False
    kind, val = accessor
    if kind == "key" and isinstance(parent, dict):
        parent[val] = value
        return True
    if isinstance(parent, list) and isinstance(val, int) and 0 <= val < len(parent):
        parent[val] = value
        return True
    return False


def _append_to_path(root: dict[str, Any], path: str, value: Any) -> bool:
    parent, accessor = _parent_and_accessor(root, path)
    if parent is None:
        return False
    kind, val = accessor
    if kind == "key" and isinstance(parent, dict):
        target = parent.get(val)
        if isinstance(target, list):
            target.append(value)
            return True
    if isinstance(parent, list) and isinstance(val, int) and 0 <= val < len(parent):
        target = parent[val]
        if isinstance(target, list):
            target.append(value)
            return True
    return False


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _resume_text(resume: dict[str, Any]) -> str:
    parts: list[str] = []

    def _walk(obj: Any) -> None:
        if isinstance(obj, str):
            parts.append(obj)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)
        elif isinstance(obj, dict):
            for v in obj.values():
                _walk(v)

    _walk(resume)
    return " ".join(parts).lower()


async def extract_jd_keywords(jd_text: str) -> dict[str, Any]:
    """Extract structured JD keywords (LLM with regex fallback)."""
    try:
        prompt = EXTRACT_JD_KEYWORDS_PROMPT.format(jd_text=jd_text[:8000])
        result = await _llm_json(system_prompt="Output only valid JSON.", user_prompt=prompt, max_tokens=1024)
        required = [s for s in (result.get("required_skills") or []) if isinstance(s, str) and s.strip()]
        preferred = [s for s in (result.get("preferred_skills") or []) if isinstance(s, str) and s.strip()]
        return {
            "required_skills": required,
            "preferred_skills": preferred,
            "job_title": str(result.get("job_title") or "").strip(),
            "seniority": str(result.get("seniority") or "").strip(),
            "key_responsibilities": [s for s in (result.get("key_responsibilities") or []) if isinstance(s, str)],
        }
    except Exception as exc:
        logger.warning("JD keyword LLM extraction failed (%s); using regex fallback", exc)
        return {"required_skills": _regex_jd_skills(jd_text), "preferred_skills": [],
                "job_title": "", "seniority": "", "key_responsibilities": []}


def _regex_jd_skills(jd_text: str) -> list[str]:
    normalized = _normalize_text(jd_text)
    patterns = (
        r"(?:experience with|proficient in|proficiency in|expertise in|knowledge of|hands[- ]on with)\s+([a-z0-9+#./\- ,&]{2,120})",
        r"(?:must have|requirements?|skills?)\s*[:\-]\s*([a-z0-9+#./\- ,&]{2,200})",
    )
    captured: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, normalized):
            for part in re.split(r",|/|\band\b|\bor\b", match.group(1)):
                token = re.sub(r"\s+", " ", part).strip(" .;:-")
                if 2 <= len(token) <= 50 and re.search(r"[a-z]", token):
                    captured.append(token)
    seen: set[str] = set()
    ordered: list[str] = []
    for item in captured:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered[:18]


def _keyword_in_text(keyword: str, text_lower: str) -> bool:
    escaped = re.escape(keyword.strip().lower())
    if not escaped:
        return False
    return bool(re.search(rf"(?<!\w){escaped}(?!\w)", text_lower))


def _compute_coverage(resume: dict[str, Any], jd_keywords: dict[str, Any]) -> tuple[float, list[str]]:
    jd_skills = list(jd_keywords.get("required_skills", [])) + list(jd_keywords.get("preferred_skills", []))
    if not jd_skills:
        return 100.0, []
    text = _resume_text(resume)
    missing = [s for s in jd_skills if not _keyword_in_text(s, text)]
    matched = len(jd_skills) - len(missing)
    return (matched / len(jd_skills)) * 100, missing


def _apply_change(resume: dict[str, Any], change: ResumeChange) -> tuple[bool, str]:
    """Apply one verified diff. Returns (applied, reason)."""
    current = _get_at_path(resume, change.path)

    if change.action == "add_skill":
        target = _get_at_path(resume, "additional.technicalSkills")
        if not isinstance(target, list):
            return False, "technicalSkills missing"
        skill = change.value if isinstance(change.value, str) else (change.value[0] if change.value else "")
        skill = str(skill).strip()
        if skill and skill.lower() not in {s.lower() for s in target if isinstance(s, str)}:
            target.append(skill)
            return True, "skill added"
        return False, "skill already present"

    if change.action == "reorder":
        if not isinstance(change.original, list) or not isinstance(change.value, list):
            return False, "reorder requires list original/value"
        current_list = current if isinstance(current, list) else []
        if [str(x).lower() for x in current_list] != [str(x).lower() for x in change.original]:
            return False, "original list mismatch — skipped"
        return _set_at_path(resume, change.path, list(change.value)), "reordered"

    if change.action == "replace":
        if change.original is None or not isinstance(change.original, str):
            return False, "replace requires string original"
        if _normalize_text(current) != _normalize_text(change.original):
            return False, "original text mismatch — skipped (anti-hallucination)"
        new_val = change.value if isinstance(change.value, str) else " ".join(str(v) for v in change.value)
        return _set_at_path(resume, change.path, new_val), "replaced"

    if change.action == "append":
        new_val = change.value if isinstance(change.value, str) else " ".join(str(v) for v in change.value)
        return _append_to_path(resume, change.path, new_val), "appended"

    return False, "unknown action"


@dataclass
class TailorResult:
    tailored_resume: dict[str, Any]
    jd_keywords: dict[str, Any]
    ats_score: dict[str, Any]
    applied_changes: list[dict[str, Any]] = field(default_factory=list)
    skipped_changes: list[dict[str, Any]] = field(default_factory=list)
    strategy_notes: str = ""
    ai_used: bool = True
    ai_provider: str | None = None
    ai_fallback_reason: str | None = None
    ai_error: str | None = None


async def tailor_resume_to_jd(
    master_resume: dict[str, Any],
    jd_text: str,
) -> TailorResult:
    """Tailor a master resume to a JD via verified diffs, then score it."""
    import copy as _copy

    jd_keywords = await extract_jd_keywords(jd_text)
    resume_copy = _copy.deepcopy(master_resume)

    changes: list[ResumeChange] = []
    strategy_notes = ""
    ai_used = False
    ai_provider = None
    ai_fallback_reason = None
    ai_error = None

    try:
        factory = get_llm_factory()
        selection = await factory.get_healthy_llm_with_metadata()
        prompt = IMPROVE_DIFF_PROMPT.format(
            resume_json=json.dumps(resume_copy, ensure_ascii=False)[:8000],
            jd_keywords=json.dumps(jd_keywords, ensure_ascii=False)[:2000],
        )
        raw = ""
        client = selection.client
        try:
            if hasattr(client, "agenerate_json"):
                raw = await client.agenerate_json(
                    system_prompt="Output only valid JSON.", user_prompt=prompt,
                    temperature=0.2, max_tokens=4096,
                )
            else:
                raw = await client.agenerate(
                    system_prompt="Output only valid JSON.", user_prompt=prompt,
                    temperature=0.2, max_tokens=4096,
                )
            factory.mark_provider_result(selection.provider, success=True)
            ai_used = True
            ai_provider = selection.provider.value
            ai_fallback_reason = selection.fallback_reason
        except Exception as exc:
            factory.mark_provider_result(selection.provider, success=False)
            raise RuntimeError(f"improve-diff LLM call failed: {exc}") from exc

        parsed = _extract_json_object(raw)
        strategy_notes = str(parsed.get("strategy_notes") or "")
        for raw_change in (parsed.get("changes") or []):
            if isinstance(raw_change, dict):
                try:
                    changes.append(ResumeChange.model_validate(raw_change))
                except Exception as vex:
                    logger.warning("Skipping invalid ResumeChange: %s", vex)
    except Exception as exc:
        ai_error = str(exc)
        logger.warning("Resume tailoring LLM step failed: %s", exc)

    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for change in changes:
        ok, reason = _apply_change(resume_copy, change)
        record = {"path": change.path, "action": change.action, "reason": change.reason, "status": reason}
        (applied if ok else skipped).append(record)

    # Recompute coverage against the tailored resume.
    match_pct, missing = _compute_coverage(resume_copy, jd_keywords)
    master_text = _resume_text(master_resume)
    injectable = [s for s in missing if _keyword_in_text(s, master_text)]

    ats = compute_ats_score(
        refined_resume=resume_copy,
        job_keywords=jd_keywords,
        keyword_match_percentage=match_pct,
        missing_keywords=missing,
        injectable_keywords=injectable,
    )

    # Re-validate so the tailored resume still conforms to the schema.
    try:
        resume_copy = ResumeData.model_validate(resume_copy).model_dump()
    except Exception as vex:
        logger.warning("Tailored resume failed schema revalidation: %s", vex)

    return TailorResult(
        tailored_resume=resume_copy,
        jd_keywords=jd_keywords,
        ats_score=ats,
        applied_changes=applied,
        skipped_changes=skipped,
        strategy_notes=strategy_notes,
        ai_used=ai_used,
        ai_provider=ai_provider,
        ai_fallback_reason=ai_fallback_reason,
        ai_error=ai_error,
    )


