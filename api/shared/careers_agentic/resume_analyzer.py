from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any

SKILL_LEXICON = [
    "python", "sql", "excel", "power bi", "tableau",
    "finance", "accounting", "hr", "recruitment", "compliance",
    "payroll", "gst", "tax", "legal", "operations", "strategy",
    "project management", "data analysis", "communication", "leadership",
]


def _normalize(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").lower()).strip()


def _extract_skills(text: str) -> list[str]:
    found: list[str] = []
    for skill in SKILL_LEXICON:
        pattern = rf"(^|[^a-z0-9]){re.escape(skill)}([^a-z0-9]|$)"
        if re.search(pattern, text):
            found.append(skill)
    return found


def _extract_compound_skills(text: str) -> list[str]:
    normalized = _normalize(text)
    patterns = (
        r"(?:experience with|proficient in|proficiency in|expertise in|knowledge of|hands[- ]on with)\s+([a-z0-9+#./\- ,&]{2,120})",
        r"(?:must have|requirements?|skills?)\s*[:\-]\s*([a-z0-9+#./\- ,&]{2,200})",
    )
    captured: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, normalized):
            segment = match.group(1)
            for part in re.split(r",|/|\band\b|\bor\b", segment):
                token = re.sub(r"\s+", " ", part).strip(" .;:-")
                if 2 <= len(token) <= 50 and re.search(r"[a-z]", token):
                    captured.append(token)
    return captured


def _extract_required_skills(jd_text: str) -> list[str]:
    candidates = _extract_skills(jd_text) + _extract_compound_skills(jd_text)
    seen: set[str] = set()
    ordered: list[str] = []
    for item in candidates:
        value = _normalize(item)
        if not value or value in seen:
            continue
        if len(value) < 2:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered[:18]


def _extract_candidate_skills(candidate_text: str) -> list[str]:
    candidates = _extract_skills(candidate_text) + _extract_compound_skills(candidate_text)
    seen: set[str] = set()
    ordered: list[str] = []
    for item in candidates:
        value = _normalize(item)
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered[:24]


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
        candidate = fenced.group(1).strip()
        try:
            parsed = json.loads(candidate)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            pass

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        candidate = text[start : end + 1]
        try:
            parsed = json.loads(candidate)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


async def _load_resume_text_excerpt(application: dict[str, Any]) -> str:
    inline_text = str(application.get("resume_text") or application.get("resume_plain_text") or "").strip()
    if inline_text:
        return inline_text[:9000]

    blob_path = str(application.get("resume_blob_path") or "").strip()
    if not blob_path:
        return ""

    content_type = _normalize(application.get("resume_content_type"))
    original_name = str(application.get("resume_original_name") or "").lower()
    is_text_resume = content_type in {"text/plain", "text/markdown", "text/csv"} or original_name.endswith((".txt", ".md", ".csv"))
    if not is_text_resume:
        return ""

    connection_string = (
        (os.getenv("CAREERS_BLOB_CONNECTION_STRING") or "").strip()
        or (os.getenv("AzureWebJobsStorage") or "").strip()
    )
    container = (
        (os.getenv("CAREERS_RESUME_BLOB_CONTAINER") or "").strip()
        or (os.getenv("CAREERS_BLOB_CONTAINER") or "").strip()
        or "careers-resume-container"
    )
    if not connection_string or not container:
        return ""

    try:
        from azure.storage.blob import BlobServiceClient  # deferred import
    except Exception:
        return ""

    def _download() -> bytes:
        service = BlobServiceClient.from_connection_string(connection_string)
        blob_client = service.get_blob_client(container=container, blob=blob_path)
        return blob_client.download_blob(max_concurrency=1).readall()

    try:
        payload = await asyncio.to_thread(_download)
        text = payload.decode("utf-8", errors="replace")
        return re.sub(r"\s+", " ", text).strip()[:9000]
    except Exception:
        return ""


async def _call_llm_for_json(*, client: Any, system_prompt: str, user_prompt: str, temperature: float, max_tokens: int) -> dict[str, Any]:
    raw = ""
    if hasattr(client, "agenerate_json"):
        try:
            raw = await client.agenerate_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            parsed = _extract_json_object(raw)
            if parsed:
                return parsed
        except Exception:
            pass

    raw = await client.agenerate(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return _extract_json_object(raw)


def _normalize_recommendation(recommendation: str, score: float) -> str:
    reco = str(recommendation or "").strip().lower()
    if reco in {"shortlist", "review", "hold"}:
        return reco
    if score >= 72:
        return "shortlist"
    if score >= 54:
        return "review"
    return "hold"


def _score_to_status(score: float) -> str:
    if score >= 85:
        return "shortlisted"
    if score <= 45:
        return "rejected"
    return "under_review"


def _safe_years_experience(value: Any) -> float:
    raw = str(value or "").strip()
    if not raw:
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        match = re.search(r"\d+(\.\d+)?", raw)
        if not match:
            return 0.0
        try:
            return float(match.group(0))
        except (TypeError, ValueError):
            return 0.0


def _coerce_str_list(value: Any, fallback: list[str]) -> list[str]:
    """Coerce an LLM-returned value into a list of short bullet strings.

    Accepts a JSON array of strings or a single string split on ; / bullet /
    newline. Falls back to the supplied deterministic bullets when empty.
    """
    if isinstance(value, list):
        out = [str(x).strip(" -•\t") for x in value if str(x).strip()]
        if out:
            return out[:8]
        return list(fallback)
    if isinstance(value, str) and value.strip():
        parts = [p.strip(" -•\t") for p in re.split(r"[;\u2022\n]", value) if p.strip()]
        if parts:
            return parts[:8]
    return list(fallback)


def _clamp_num(value: Any, lo: float, hi: float, default: float) -> float:
    try:
        return max(lo, min(hi, round(float(value), 1)))
    except (TypeError, ValueError):
        return float(default)


def _build_strengths_bullets(matched: list[str], required: list[str], years: float, recommendation: str) -> list[str]:
    bullets: list[str] = []
    if matched:
        preview = ", ".join(matched[:4])
        suffix = "" if len(matched) <= 4 else f" (+{len(matched) - 4} more)"
        bullets.append(f"Matches {len(matched)}/{len(required)} critical skills: {preview}{suffix}.")
    else:
        bullets.append("No critical skills directly matched the job description keywords.")
    if years >= 8:
        bullets.append(f"Strong experience ({years:.1f} years) — above the typical mid-level expectation.")
    elif years >= 3:
        bullets.append(f"Solid experience ({years:.1f} years) relevant to the role.")
    elif years > 0:
        bullets.append(f"Early-career ({years:.1f} years); good growth potential with some upskilling.")
    if recommendation == "shortlist":
        bullets.append("Overall alignment supports progressing the candidate to interview.")
    return bullets[:5]


def _build_gaps_bullets(missing: list[str], required: list[str], years: float) -> list[str]:
    bullets: list[str] = []
    if missing:
        preview = ", ".join(missing[:4])
        suffix = "" if len(missing) <= 4 else f" (+{len(missing) - 4} more)"
        bullets.append(f"Missing {len(missing)}/{len(required)} required skills: {preview}{suffix}.")
    else:
        bullets.append("No critical skill gaps identified against the JD.")
    if 0 <= years < 3:
        bullets.append("Years of experience may be below the role's seniority expectation.")
    return bullets[:5]


def analyze_application(*, job: dict[str, Any], application: dict[str, Any]) -> dict[str, Any]:
    jd_text = " ".join(
        [
            _normalize(job.get("title")),
            _normalize(job.get("department")),
            _normalize(job.get("employment_type")),
            _normalize(job.get("jd_markdown")),
            _normalize(job.get("jd_raw_text")),
        ]
    )
    candidate_text = " ".join(
        [
            _normalize(application.get("cover_note")),
            _normalize(application.get("linkedin_url")),
            _normalize(application.get("full_name")),
            _normalize(application.get("resume_original_name")),
            _normalize(application.get("email")),
        ]
    )

    required = _extract_required_skills(jd_text) or ["communication", "operations", "strategy"]
    candidate = _extract_candidate_skills(candidate_text)
    matched = sorted({skill for skill in required if skill in candidate})
    missing = sorted({skill for skill in required if skill not in candidate})

    years = _safe_years_experience(application.get("years_experience"))
    skill_ratio = (len(matched) / len(required)) if required else 0.0
    experience_score = min(years, 20.0) * 1.4
    score = round(min(97.0, 24.0 + (skill_ratio * 55.0) + experience_score), 1)

    recommendation = _normalize_recommendation("", score)

    strengths = f"Matched {len(matched)} of {len(required)} key skills" + (f": {', '.join(matched)}." if matched else ".")
    gaps = f"Missing {len(missing)} skills" + (f": {', '.join(missing)}." if missing else ".")
    fit_band = "high" if score >= 75 else ("medium" if score >= 60 else "low")

    # ── Weighted dimension + composite scores (drives the frontend "Score
    #    Breakout" tab). skills_fit is on a 0-40 scale, experience_fit 0-30,
    #    education_fit 0-30. The composite keyword/semantic/overall scores are
    #    0-100. The LLM revalidation step refines these against the evidence.
    skills_fit = round(skill_ratio * 40)
    experience_fit = round(min(experience_score, 30.0))
    # Education is not parsed by the deterministic layer; use a conservative
    # proxy so the dimension renders rather than being hidden.
    education_fit = 18 if years >= 5 else (12 if years >= 2 else 6)
    keyword_score = round(skill_ratio * 100)                                  # Layer 1 overlap (0-100)
    semantic_score = round(min(100.0, skill_ratio * 70.0 + experience_score))  # proxy (0-100)
    overall_score = round(score)                                               # composite (0-100)

    strengths_list = _build_strengths_bullets(matched, required, years, recommendation)
    gaps_list = _build_gaps_bullets(missing, required, years)

    structured_report = {
        "summary": (
            f"Recommendation: {recommendation.upper()}. Candidate scores {score:.1f}/100 "
            f"({fit_band} fit) — matched {len(matched)} of {len(required)} key skills "
            f"with {years:.1f} years of experience."
        ),
        "fit_band": fit_band,
        "score_breakdown": {
            "skills_fit": skills_fit,
            "skills_max": 40,
            "experience_fit": experience_fit,
            "experience_max": 30,
            "education_fit": education_fit,
            "education_max": 30,
            "keyword_score": keyword_score,
            "keyword_max": 100,
            "semantic_score": semantic_score,
            "semantic_max": 100,
            "overall_score": overall_score,
            "overall_max": 100,
            # Legacy counters retained for backward compatibility.
            "experience_years": years,
            "matched_skills_count": len(matched),
            "missing_skills_count": len(missing),
        },
        "recommendation_rationale": (
            f"'{recommendation}' based on {len(matched)}/{len(required)} critical skill matches "
            f"and {years:.1f} years of experience. See the Strengths & Gaps tab for evidence."
        ),
        "strengths": strengths_list,
        "gaps": gaps_list,
        "executive_summary": _build_executive_summary_structured(
            score=score,
            fit_band=fit_band,
            recommendation=recommendation,
            breakdown={
                "skills_fit": skills_fit,
                "skills_max": 40,
                "experience_fit": experience_fit,
                "experience_max": 30,
                "education_fit": education_fit,
                "education_max": 30,
            },
            matched=matched,
            missing=missing,
            years=years,
        ),
    }

    return {
        "match_score": score,
        "recommendation": recommendation,
        "matched_skills": matched,
        "missing_skills": missing,
        "strengths_summary": strengths,
        "gaps_summary": gaps,
        "strengths": strengths_list,
        "gaps": gaps_list,
        "suggested_status": _score_to_status(score),
        "admin_summary": {
            "fit_band": fit_band,
            "years_experience": years,
            "top_matched": matched[:5],
            "top_gaps": missing[:5],
        },
        "structured_report": structured_report,
    }


def _merge_score_breakdown(
    base: dict[str, Any], llm: dict[str, Any] | None, ai_score: float
) -> dict[str, Any]:
    """Merge the LLM-refined score breakdown over the deterministic base.

    Each dimension/composite value is clamped to its valid range and the
    composite ``overall_score`` is forced to equal the calibrated match score
    so the UI's "Overall (Composite)" row always matches the headline score.
    """
    llm = llm or {}
    base = base or {}

    def _pick(key: str, lo: float, hi: float, default: float) -> float:
        val = llm.get(key)
        if val is None:
            val = base.get(key, default)
        return _clamp_num(val, lo, hi, default)

    skills_fit = _pick("skills_fit", 0, 40, float(base.get("skills_fit", 0)))
    experience_fit = _pick("experience_fit", 0, 30, float(base.get("experience_fit", 0)))
    education_fit = _pick("education_fit", 0, 30, float(base.get("education_fit", 0)))
    keyword_score = _pick("keyword_score", 0, 100, float(base.get("keyword_score", 0)))
    semantic_score = _pick("semantic_score", 0, 100, float(base.get("semantic_score", 0)))

    return {
        "skills_fit": skills_fit,
        "skills_max": 40,
        "experience_fit": experience_fit,
        "experience_max": 30,
        "education_fit": education_fit,
        "education_max": 30,
        "keyword_score": keyword_score,
        "keyword_max": 100,
        "semantic_score": semantic_score,
        "semantic_max": 100,
        # Force the composite to equal the calibrated match score.
        "overall_score": _clamp_num(ai_score, 0, 100, ai_score),
        "overall_max": 100,
        # Legacy counters retained for backward compatibility.
        "experience_years": base.get("experience_years", 0.0),
        "matched_skills_count": base.get("matched_skills_count", 0),
        "missing_skills_count": base.get("missing_skills_count", 0),
    }


def _build_consistent_summary(
    *,
    ai_score: float,
    fit_band: str,
    recommendation: str,
    breakdown: dict[str, Any],
    matched: list[str],
    missing: list[str],
    years: float,
) -> str:
    """Build a humanized fallback executive summary whose stated scores are
    guaranteed consistent with the calibrated match score and breakdown."""
    skills_fit = breakdown.get("skills_fit", 0)
    experience_fit = breakdown.get("experience_fit", 0)
    education_fit = breakdown.get("education_fit", 0)
    total_required = len(matched) + len(missing)
    return (
        f"Recommendation: {recommendation.upper()} ({fit_band} fit). "
        f"The candidate scores {ai_score:.1f}/100 overall, driven by "
        f"skills fit {skills_fit:.0f}/40, experience {experience_fit:.0f}/30 "
        f"and education {education_fit:.0f}/30 — matching "
        f"{len(matched)} of {total_required} critical skills with "
        f"{years:.1f} years of experience."
    )


def _build_executive_summary_structured(
    *,
    score: float,
    fit_band: str,
    recommendation: str,
    breakdown: dict[str, Any],
    matched: list[str],
    missing: list[str],
    years: float,
    narrative: str | None = None,
) -> dict[str, Any]:
    """Build a structured executive-summary object whose numbers are guaranteed
    consistent with the calibrated match score and score breakdown.

    Mirrors the structured "Score Breakout" by exposing the same weighted
    dimension scores as labelled bars, plus a verdict headline, the top
    matched (highlights) and missing (risks) skills, and a confidence band.
    """
    narrative = (narrative or "").strip() or _build_consistent_summary(
        ai_score=score,
        fit_band=fit_band,
        recommendation=recommendation,
        breakdown=breakdown,
        matched=matched,
        missing=missing,
        years=years,
    )
    reco_norm = str(recommendation).lower()
    reco_label = {
        "shortlist": "Shortlist",
        "review": "Review",
        "hold": "Hold",
    }.get(reco_norm, str(recommendation).capitalize() or "-")
    band_label = str(fit_band).capitalize()
    return {
        "headline": f"{reco_label} · {band_label} fit · {round(float(score))}/100",
        "narrative": narrative,
        "recommendation": reco_norm,
        "fit_band": str(fit_band),
        "score": round(float(score)),
        "dimensions": [
            {
                "label": "Skills Fit",
                "score": float(breakdown.get("skills_fit", 0)),
                "max": float(breakdown.get("skills_max", 40)),
                "color": "indigo",
            },
            {
                "label": "Experience",
                "score": float(breakdown.get("experience_fit", 0)),
                "max": float(breakdown.get("experience_max", 30)),
                "color": "cyan",
            },
            {
                "label": "Education",
                "score": float(breakdown.get("education_fit", 0)),
                "max": float(breakdown.get("education_max", 30)),
                "color": "violet",
            },
        ],
        "highlights": list(matched[:3]),
        "risks": list(missing[:3]),
        "confidence": str(fit_band),
    }


async def ai_revalidate_analysis(*, job: dict[str, Any], application: dict[str, Any], base_result: dict[str, Any]) -> dict[str, Any]:
    """Use configured LLM to revalidate deterministic analysis.
    Falls back to base_result if AI provider is unavailable.
    """
    try:
        from core.llm_factory import get_llm_factory

        factory = get_llm_factory()
        selection = await factory.get_healthy_llm_with_metadata()
        client = selection.client
        resume_excerpt = await _load_resume_text_excerpt(application)

        system_prompt = (
            "You are a senior technical recruiter and hiring quality reviewer. "
            "Return only valid JSON with evidence-grounded scoring."
        )

        draft_prompt = json.dumps(
            {
                "job": {
                    "title": job.get("title"),
                    "department": job.get("department"),
                    "employment_type": job.get("employment_type"),
                    "jd_markdown": job.get("jd_markdown"),
                    "jd_raw_text": job.get("jd_raw_text"),
                },
                "candidate": {
                    "full_name": application.get("full_name"),
                    "years_experience": application.get("years_experience"),
                    "cover_note": application.get("cover_note"),
                    "linkedin_url": application.get("linkedin_url"),
                    "resume_original_name": application.get("resume_original_name"),
                    "resume_excerpt": resume_excerpt,
                },
                "base_result": base_result,
                "required_output": {
                    "match_score": "number between 0 and 100",
                    "recommendation": "shortlist | review | hold",
                    "executive_summary": "2-3 sentence humanized narrative for an HR admin. MUST state the exact match_score number, the fit band (high/medium/low), the recommendation, and cite the skills_fit/experience_fit/education_fit dimension scores. Every number cited MUST exactly equal the corresponding value in score_breakdown and match_score - never invent, round, or approximate differently.",
                    "strengths": "JSON array of 3-5 short bullet strings (each <= 90 chars), each an evidence-grounded strength",
                    "gaps": "JSON array of 3-5 short bullet strings (each <= 90 chars), each an evidence-grounded gap or risk",
                    "strengths_summary": "one-line summary of the top strengths",
                    "gaps_summary": "one-line summary of the top gaps",
                    "recommendation_rationale": "2-3 sentences with concrete evidence (skills matched, years of experience, education)",
                    "score_breakdown": {
                        "skills_fit": "number 0-40 (weighted critical-skills score)",
                        "experience_fit": "number 0-30 (weighted experience/seniority score)",
                        "education_fit": "number 0-30 (weighted education/certification score)",
                        "keyword_score": "number 0-100 (Layer 1 keyword overlap)",
                        "semantic_score": "number 0-100 (Layer 2 semantic similarity)",
                        "overall_score": "number 0-100 (composite, must equal match_score)",
                    },
                },
            },
            ensure_ascii=True,
        )

        draft_data = await _call_llm_for_json(
            client=client,
            system_prompt=system_prompt,
            user_prompt=draft_prompt,
            temperature=0.25,
            max_tokens=900,
        )

        review_prompt = json.dumps(
            {
                "task": "Critique and calibrate the draft analysis against the supplied evidence. "
                "If unsupported claims exist, lower confidence and adjust score/recommendation.",
                "job": {
                    "title": job.get("title"),
                    "department": job.get("department"),
                    "employment_type": job.get("employment_type"),
                    "jd_markdown": job.get("jd_markdown"),
                },
                "candidate": {
                    "years_experience": application.get("years_experience"),
                    "cover_note": application.get("cover_note"),
                    "resume_excerpt": resume_excerpt,
                },
                "draft_analysis": draft_data,
                "required_output": {
                    "match_score": "number between 0 and 100",
                    "recommendation": "shortlist | review | hold",
                    "executive_summary": "2-3 sentence humanized narrative for an HR admin. MUST state the exact match_score number, the fit band (high/medium/low), the recommendation, and cite the skills_fit/experience_fit/education_fit dimension scores. Every number cited MUST exactly equal the corresponding value in score_breakdown and match_score - never invent, round, or approximate differently.",
                    "strengths": "JSON array of 3-5 short bullet strings (each <= 90 chars), each an evidence-grounded strength",
                    "gaps": "JSON array of 3-5 short bullet strings (each <= 90 chars), each an evidence-grounded gap or risk",
                    "strengths_summary": "one-line summary of the top strengths",
                    "gaps_summary": "one-line summary of the top gaps",
                    "recommendation_rationale": "2-3 sentences with concrete evidence (skills matched, years of experience, education)",
                    "score_breakdown": {
                        "skills_fit": "number 0-40 (weighted critical-skills score)",
                        "experience_fit": "number 0-30 (weighted experience/seniority score)",
                        "education_fit": "number 0-30 (weighted education/certification score)",
                        "keyword_score": "number 0-100 (Layer 1 keyword overlap)",
                        "semantic_score": "number 0-100 (Layer 2 semantic similarity)",
                        "overall_score": "number 0-100 (composite, must equal match_score)",
                    },
                },
            },
            ensure_ascii=True,
        )

        reviewed_data = await _call_llm_for_json(
            client=client,
            system_prompt=system_prompt,
            user_prompt=review_prompt,
            temperature=0.1,
            max_tokens=800,
        )
        data = reviewed_data or draft_data

        ai_score = float(data.get("match_score")) if data.get("match_score") is not None else float(base_result["match_score"])
        ai_score = max(0.0, min(100.0, round(ai_score, 1)))
        ai_reco = _normalize_recommendation(str(data.get("recommendation") or base_result["recommendation"]), ai_score)

        fit_band = "high" if ai_score >= 75 else ("medium" if ai_score >= 60 else "low")

        base_breakdown = (
            base_result.get("structured_report", {}).get("score_breakdown", {}) or {}
        )
        llm_breakdown = data.get("score_breakdown") if isinstance(data.get("score_breakdown"), dict) else {}
        score_breakdown = _merge_score_breakdown(base_breakdown, llm_breakdown, ai_score)

        executive_summary = str(
            data.get("executive_summary") or data.get("summary") or ""
        ).strip()
        if not executive_summary:
            executive_summary = _build_consistent_summary(
                ai_score=ai_score,
                fit_band=fit_band,
                recommendation=ai_reco,
                breakdown=score_breakdown,
                matched=base_result.get("matched_skills", []),
                missing=base_result.get("missing_skills", []),
                years=base_result.get("admin_summary", {}).get("years_experience", 0.0),
            )

        strengths_list = _coerce_str_list(
            data.get("strengths"),
            base_result.get("structured_report", {}).get("strengths", []),
        )
        gaps_list = _coerce_str_list(
            data.get("gaps"),
            base_result.get("structured_report", {}).get("gaps", []),
        )

        structured_report = {
            "summary": executive_summary,
            "fit_band": fit_band,
            "score_breakdown": score_breakdown,
            "recommendation_rationale": str(
                data.get("recommendation_rationale")
                or base_result.get("structured_report", {}).get("recommendation_rationale")
                or "AI-reviewed recommendation based on job and profile alignment."
            ).strip(),
            "strengths": strengths_list,
            "gaps": gaps_list,
            "executive_summary": _build_executive_summary_structured(
                score=ai_score,
                fit_band=fit_band,
                recommendation=ai_reco,
                breakdown=score_breakdown,
                matched=base_result.get("matched_skills", []),
                missing=base_result.get("missing_skills", []),
                years=base_result.get("admin_summary", {}).get("years_experience", 0.0),
                narrative=executive_summary,
            ),
        }

        return {
            **base_result,
            "match_score": ai_score,
            "recommendation": ai_reco,
            "strengths_summary": str(data.get("strengths_summary") or base_result["strengths_summary"]),
            "gaps_summary": str(data.get("gaps_summary") or base_result["gaps_summary"]),
            "strengths": strengths_list,
            "gaps": gaps_list,
            "ai_summary": executive_summary,
            "ai_used": True,
            "ai_provider": selection.provider.value,
            "ai_fallback_reason": selection.fallback_reason,
            "structured_report": structured_report,
        }
    except Exception as exc:
        return {
            **base_result,
            "ai_summary": str(base_result.get("structured_report", {}).get("summary") or "").strip(),
            "ai_used": False,
            "ai_provider": None,
            "ai_error": str(exc),
        }
