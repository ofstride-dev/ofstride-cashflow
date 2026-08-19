from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from core.settings import DATA_ROOT


@dataclass
class JdTemplate:
    template_id: str
    title_hint: str
    department_hint: str
    responsibilities: list[str]
    must_have: list[str]
    preferred: list[str]


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _tokenize(text: str) -> set[str]:
    text = _normalize(text)
    return {tok for tok in re.split(r"[^a-z0-9]+", text) if len(tok) > 2}


def _load_templates() -> list[JdTemplate]:
    source = DATA_ROOT / "jd_templates.json"
    if not source.exists():
        return []
    raw = json.loads(source.read_text(encoding="utf-8"))
    templates: list[JdTemplate] = []
    for item in raw if isinstance(raw, list) else []:
        templates.append(
            JdTemplate(
                template_id=str(item.get("id") or "template"),
                title_hint=str(item.get("title_hint") or "").strip(),
                department_hint=str(item.get("department_hint") or "").strip(),
                responsibilities=[str(x).strip() for x in (item.get("responsibilities") or []) if str(x).strip()],
                must_have=[str(x).strip() for x in (item.get("must_have") or []) if str(x).strip()],
                preferred=[str(x).strip() for x in (item.get("preferred") or []) if str(x).strip()],
            )
        )
    return templates


def _pick_best_template(*, title: str, department: str, jd_text: str, templates: list[JdTemplate]) -> JdTemplate | None:
    if not templates:
        return None
    query_tokens = _tokenize(" ".join([title, department, jd_text]))
    best: tuple[int, JdTemplate] | None = None
    for template in templates:
        haystack = " ".join(
            [
                template.title_hint,
                template.department_hint,
                " ".join(template.responsibilities),
                " ".join(template.must_have),
                " ".join(template.preferred),
            ]
        )
        score = len(query_tokens.intersection(_tokenize(haystack)))
        if best is None or score > best[0]:
            best = (score, template)
    return best[1] if best else None


def _build_requirement_brief(*, title: str, department: str, location: str, employment_type: str, jd_markdown: str, template: JdTemplate | None) -> str:
    bullets: list[str] = [
        f"Role title: {title or 'Role'}",
        f"Department: {department or 'General'}",
        f"Location: {location or 'As discussed'}",
        f"Employment type: {employment_type or 'Full-time'}",
    ]
    if template:
        bullets.append(f"Template fit: {template.template_id}")
        if template.title_hint:
            bullets.append(f"Title hint: {template.title_hint}")
        if template.department_hint:
            bullets.append(f"Department hint: {template.department_hint}")
        if template.responsibilities:
            bullets.append("Template responsibilities: " + "; ".join(template.responsibilities[:5]))
        if template.must_have:
            bullets.append("Template must-haves: " + "; ".join(template.must_have[:5]))
        if template.preferred:
            bullets.append("Template preferred skills: " + "; ".join(template.preferred[:5]))
    if jd_markdown:
        bullets.append("Source JD excerpt: " + jd_markdown[:1200])
    return "\n".join(f"- {item}" for item in bullets)


def _specificity_notes(text: str) -> list[str]:
    normalized = _normalize(text)
    notes: list[str] = []
    if any(token in normalized for token in ["dynamic environment", "fast-paced environment", "team player", "self-starter"]):
        notes.append("Replace generic hiring language with role-specific outcomes.")
    if len(_tokenize(normalized)) < 60:
        notes.append("Add more concrete responsibilities, tools, or business outcomes.")
    if "must-have" not in normalized and "preferred" not in normalized:
        notes.append("Keep the structure explicit so candidates can scan it quickly.")
    return notes


def enhance_jd_markdown(*, title: str, department: str | None, location: str | None, employment_type: str | None, jd_markdown: str) -> dict[str, Any]:
    title = str(title or "").strip() or "Role"
    department = str(department or "").strip()
    location = str(location or "").strip()
    employment_type = str(employment_type or "").strip()
    jd_markdown = str(jd_markdown or "").strip()

    templates = _load_templates()
    best = _pick_best_template(title=title, department=department, jd_text=jd_markdown, templates=templates)

    responsibilities = []
    must_have = []
    preferred = []
    if best:
        responsibilities = best.responsibilities[:5]
        must_have = best.must_have[:7]
        preferred = best.preferred[:5]

    if not responsibilities:
        responsibilities = [
            "Deliver role-specific outcomes aligned to business goals.",
            "Collaborate with cross-functional teams and stakeholders.",
            "Track KPIs, quality standards, and delivery timelines.",
            "Document processes and handoffs for continuity.",
            "Identify improvements and execute with ownership.",
        ]
    if not must_have:
        must_have = [
            "Relevant domain experience in similar role scope.",
            "Strong communication and stakeholder management skills.",
            "Problem-solving mindset with ownership and execution focus.",
            "Comfort with data-driven decision making.",
            "Ability to work in a fast-moving environment.",
        ]

    summary = (
        "Own key outcomes for this role, collaborate across teams, and deliver measurable impact "
        "through structured execution and continuous improvement."
    )

    short_jd = "\n".join(
        [
            f"# {title}",
            "",
            "## Snapshot",
            f"- Department: {department or 'General'}",
            f"- Location: {location or 'As discussed'}",
            f"- Employment Type: {employment_type or 'Full-time'}",
            "",
            "## Role Summary",
            summary,
            "",
            "## Key Responsibilities",
            *[f"- {item}" for item in responsibilities],
            "",
            "## Must-Have Skills",
            *[f"- {item}" for item in must_have],
            "",
            "## Preferred Skills",
            *([f"- {item}" for item in preferred] if preferred else ["- Nice-to-have skills based on business context."]),
            "",
            "## Interview Focus",
            "- Problem-solving depth",
            "- Functional execution quality",
            "- Collaboration and communication",
            "- Ownership and delivery consistency",
        ]
    )

    return {
        "enhanced_jd_markdown": short_jd,
        "template_id": best.template_id if best else "fallback",
        "has_template_match": bool(best),
    }


async def enhance_jd_with_existing_llm(*, title: str, department: str | None, location: str | None, employment_type: str | None, jd_markdown: str) -> dict[str, Any]:
    baseline = enhance_jd_markdown(
        title=title,
        department=department,
        location=location,
        employment_type=employment_type,
        jd_markdown=jd_markdown,
    )
    try:
        # Lazy import keeps non-LLM routes healthy even if optional LLM deps are absent.
        from core.llm_factory import get_llm_factory
        llm_factory = get_llm_factory()
        selection = await llm_factory.get_healthy_llm_with_metadata()
        requirement_brief = _build_requirement_brief(
            title=title,
            department=str(department or "").strip(),
            location=str(location or "").strip(),
            employment_type=str(employment_type or "").strip(),
            jd_markdown=jd_markdown or baseline["enhanced_jd_markdown"],
            template=_pick_best_template(title=title, department=str(department or "").strip(), jd_text=jd_markdown, templates=_load_templates()),
        )
        draft_system_prompt = (
            "You are a senior hiring specialist. Draft a concise job description from structured intake. "
            "Stay grounded in the provided facts, do not invent compensation or policies, and make the role specific enough that a candidate can tell what success looks like."
        )
        draft_user_prompt = "\n".join(
            [
                "Structured intake:",
                requirement_brief,
                "",
                "Write markdown only with these sections:",
                "1) Snapshot",
                "2) Role Summary",
                "3) Key Responsibilities",
                "4) Must-Have Skills",
                "5) Preferred Skills",
                "6) Interview Focus",
                "",
                "Keep the wording specific, practical, and business-facing.",
            ]
        )
        draft_content = await selection.client.agenerate(
            system_prompt=draft_system_prompt,
            user_prompt=draft_user_prompt,
            temperature=0.25,
            max_tokens=900,
        )
        draft_markdown = str(draft_content or "").strip()
        if len(draft_markdown) < 80:
            return {
                **baseline,
                "used_llm": False,
                "llm_provider": None,
                "llm_reason": "llm_response_too_short",
            }
        review_system_prompt = (
            "You are a skeptical hiring reviewer. Check whether the job description sounds generic, vague, or repetitive. "
            "If it does, rewrite it once so the final version is more specific and grounded in the intake. Return markdown only."
        )
        review_user_prompt = "\n".join(
            [
                "Structured intake:",
                requirement_brief,
                "",
                "Draft job description:",
                draft_markdown,
                "",
                "Review checklist:",
                "- Replace generic wording with role-specific outcomes",
                "- Keep responsibilities concrete",
                "- Keep the document concise and business-facing",
                "- Preserve only facts supported by the intake",
            ]
        )
        reviewed_content = await selection.client.agenerate(
            system_prompt=review_system_prompt,
            user_prompt=review_user_prompt,
            temperature=0.15,
            max_tokens=1000,
        )
        reviewed_markdown = str(reviewed_content or "").strip()
        final_markdown = reviewed_markdown if len(reviewed_markdown) >= len(draft_markdown) * 0.8 else draft_markdown
        notes = _specificity_notes(final_markdown)
        if notes and final_markdown == draft_markdown:
            followup = await selection.client.agenerate(
                system_prompt="You are a precision editor for job descriptions. Improve specificity without adding unsupported facts.",
                user_prompt="\n".join([
                    "Structured intake:",
                    requirement_brief,
                    "",
                    "Current markdown:",
                    final_markdown,
                    "",
                    "Apply these fixes:",
                    *[f"- {note}" for note in notes],
                ]),
                temperature=0.1,
                max_tokens=1000,
            )
            improved_markdown = str(followup or "").strip()
            if len(improved_markdown) > 80:
                final_markdown = improved_markdown
        return {
            **baseline,
            "enhanced_jd_markdown": final_markdown,
            "used_llm": True,
            "llm_provider": selection.provider.value,
            "llm_reason": selection.fallback_reason,
            "jd_review_notes": notes,
            "jd_intake_specificity": "high" if not notes else "needs_review",
        }
    except Exception as exc:
        return {
            **baseline,
            "used_llm": False,
            "llm_provider": None,
            "llm_reason": str(exc),
            "jd_review_notes": _specificity_notes(baseline["enhanced_jd_markdown"]),
        }
