"""ATS score computation utilities (ported from Resume-Matcher, Apache-2.0).

Calculates an ATS-style breakdown from already-processed resume and job data:
  - keyword_match: final keyword match % from the tailoring pipeline
  - skills_coverage: overlap between resume technical skills and JD skills
  - section_completeness: presence of essential resume sections (no LLM)

The overall_score is a weighted composite. Pure Python — no LLM calls — so it
complements (and does not duplicate) the existing ``resume_analyzer`` scoring.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_WEIGHTS = {"keyword_match": 0.55, "skills_coverage": 0.25, "section_completeness": 0.20}

_SECTION_PATTERNS = {
    "summary": ["summary", "objective", "profile", "about"],
    "experience": ["experience", "work history", "employment"],
    "education": ["education", "academic", "degree"],
    "skills": ["skills", "technologies", "competencies", "technical"],
}


def _extract_all_text(data: dict[str, Any]) -> str:
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

    _walk(data)
    return " ".join(parts)


def _keyword_in_text(keyword: str, text_lower: str) -> bool:
    escaped = re.escape(keyword.strip().lower())
    if not escaped:
        return False
    return bool(re.search(rf"(?<!\w){escaped}(?!\w)", text_lower))


def _compute_skills_coverage(resume: dict[str, Any], job_keywords: dict[str, Any]) -> float:
    jd_skills: list[str] = []
    jd_skills.extend(job_keywords.get("required_skills", []))
    jd_skills.extend(job_keywords.get("preferred_skills", []))
    if not jd_skills:
        return 0.0

    resume_skills: list[str] = resume.get("additional", {}).get("technicalSkills", []) or []
    resume_text = _extract_all_text(resume).lower()
    resume_skills_lower = {s.lower() for s in resume_skills if isinstance(s, str)}

    matched = 0
    for skill in jd_skills:
        if not isinstance(skill, str):
            continue
        skill_lower = skill.lower()
        if skill_lower in resume_skills_lower or _keyword_in_text(skill, resume_text):
            matched += 1

    return min(100.0, (matched / len(jd_skills)) * 100)


def _compute_section_completeness(resume: dict[str, Any]) -> float:
    found = 0
    if resume.get("summary"):
        found += 1
    if resume.get("workExperience"):
        found += 1
    if resume.get("education"):
        found += 1
    additional = resume.get("additional") or {}
    if additional.get("technicalSkills") or additional.get("certificationsTraining"):
        found += 1

    if found == 0:
        text = _extract_all_text(resume).lower()
        for patterns in _SECTION_PATTERNS.values():
            if any(p in text for p in patterns):
                found += 1

    total = len(_SECTION_PATTERNS)
    return (found / total) * 100


def _generate_recommendations(
    keyword_score: float,
    skills_score: float,
    section_score: float,
    missing_keywords: list[str],
    injectable_keywords: list[str],
) -> list[str]:
    tips: list[str] = []

    if keyword_score < 60 and missing_keywords:
        tips.append(f"Add these high-priority missing keywords: {', '.join(missing_keywords[:5])}.")
    if injectable_keywords:
        tips.append(
            "Skills present in your master resume but not in this tailored "
            f"version — consider adding: {', '.join(injectable_keywords[:5])}."
        )
    if skills_score < 60:
        tips.append("Expand your Skills section to include more tools/technologies from the JD.")
    if section_score < 75:
        tips.append("Ensure all key sections exist: Summary, Work Experience, Education, Skills.")
    if keyword_score >= 80 and skills_score >= 80:
        tips.append("Strong keyword/skills alignment — consider quantifying achievements with metrics.")
    if not tips:
        tips.append("Resume is well-aligned with the JD. Review for niche certifications or tools to add.")
    return tips


def compute_ats_score(
    refined_resume: dict[str, Any],
    job_keywords: dict[str, Any],
    keyword_match_percentage: float,
    missing_keywords: list[str],
    injectable_keywords: list[str],
) -> dict[str, Any]:
    """Compute the ATS score breakdown dict."""
    kw_score = min(100.0, max(0.0, keyword_match_percentage))
    sk_score = _compute_skills_coverage(refined_resume, job_keywords)
    sec_score = _compute_section_completeness(refined_resume)

    overall = (
        kw_score * _WEIGHTS["keyword_match"]
        + sk_score * _WEIGHTS["skills_coverage"]
        + sec_score * _WEIGHTS["section_completeness"]
    )

    return {
        "overall_score": round(overall, 1),
        "sub_scores": {
            "keyword_match": round(kw_score, 1),
            "skills_coverage": round(sk_score, 1),
            "section_completeness": round(sec_score, 1),
        },
        "missing_keywords": missing_keywords[:10],
        "injectable_keywords": injectable_keywords[:10],
        "recommendations": _generate_recommendations(
            kw_score, sk_score, sec_score, missing_keywords, injectable_keywords,
        ),
    }

