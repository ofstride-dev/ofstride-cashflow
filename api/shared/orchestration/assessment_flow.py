from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from core.settings import DATA_ROOT
from orchestration.intake_flow import (
    STATE_INTAKE_FIELDS,
    STATE_INTAKE_SUBMITTED,
    STATE_OPEN,
    build_next_required_prompt,
    missing_required_fields,
)
from orchestration.llm_json import generate_assessment_focus
from orchestration.lead_logger import log_lead_capture_step
from orchestration.session_profile import EMAIL_RE, PHONE_RE


@dataclass
class AssessmentTurnResult:
    handled: bool
    next_state: str | None = None
    response_text: str = ""
    actions: list[dict[str, str]] | None = None
    profile_updates: dict[str, str] | None = None
    lead_step: str | None = None
    focus_report: dict | None = None


_Q_FILE = DATA_ROOT / "assessment_questionnaire.json"
_CACHED: dict[str, Any] | None = None


def _load_config() -> dict[str, Any]:
    global _CACHED
    if _CACHED is not None:
        return _CACHED

    raw = _Q_FILE.read_text(encoding="utf-8")
    _CACHED = json.loads(raw)
    return _CACHED


def _normalize(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def _contains_any(text: str, tokens: set[str]) -> bool:
    normalized = _normalize(text)
    return any(token in normalized for token in tokens)


def _actions(options: list[str]) -> list[dict[str, str]]:
    return [
        {
            "id": f"assessment_{idx + 1}",
            "label": option,
            "value": option,
            "kind": "quick_reply",
        }
        for idx, option in enumerate(options)
    ]


def _final_actions() -> list[dict[str, str]]:
    return [
        {
            "id": "assessment_schedule_call",
            "label": "Schedule a call",
            "value": "Schedule a call",
            "kind": "quick_reply",
        },
        {
            "id": "assessment_restart",
            "label": "Start Assessment",
            "value": "Start Assessment",
            "kind": "quick_reply",
        },
    ]


def _default_branch_followup(challenge: str) -> tuple[str, list[str]]:
    fallback_map: dict[str, tuple[str, list[str]]] = {
        "Growing the business": (
            "What's holding back your growth?",
            [
                "Finding customers",
                "Scaling operations",
                "Hiring the right people",
                "Cash flow",
                "Technology",
                "Market competition",
            ],
        ),
        "Operational inefficiencies": (
            "Which area consumes the most time?",
            [
                "Manual work",
                "Multiple spreadsheets",
                "Poor coordination",
                "Lack of SOPs",
                "Vendor management",
                "Reporting",
            ],
        ),
        "People & HR challenges": (
            "Which challenge best describes your situation?",
            [
                "Hiring",
                "Employee retention",
                "Performance management",
                "HR compliance",
                "Leadership capability",
            ],
        ),
        "AI & Automation": (
            "What are you hoping AI will do?",
            [
                "Save time",
                "Improve customer service",
                "Generate reports",
                "Build an AI assistant",
                "Automate repetitive work",
                "I don't know where to start",
            ],
        ),
        "Compliance & Legal": (
            "What's your priority?",
            [
                "Compliance",
                "Due diligence",
                "Contracts",
                "Tax",
                "Internal controls",
                "Risk management",
            ],
        ),
        "Reducing costs": (
            "Where do you see the biggest cost pressure today?",
            [
                "High operational overhead",
                "Low process efficiency",
                "Vendor spend leakage",
                "Poor budget visibility",
                "Manual rework and errors",
                "Low team productivity",
            ],
        ),
        "Decision making & reporting": (
            "What is the biggest decision/reporting bottleneck for your team?",
            [
                "Data is scattered across systems",
                "Reports take too long",
                "No real-time visibility",
                "Unclear KPIs",
                "Low confidence in data quality",
                "Too much manual analysis",
            ],
        ),
        "Not sure": (
            "Which area feels most uncertain right now?",
            [
                "Growth strategy",
                "Operations and execution",
                "People and leadership",
                "Compliance and risk",
                "Technology and automation",
                "I need a diagnostic first",
            ],
        ),
    }
    return fallback_map.get(
        challenge,
        (
            "Which area would you like to prioritize first?",
            ["Growth", "Operations", "People", "Compliance", "Technology", "Not sure"],
        ),
    )


def _resolve_branch_followup(challenge: str, branch: dict[str, Any]) -> tuple[str, list[str]]:
    question = str(branch.get("question", "")).strip()
    options = branch.get("options", [])
    if question and isinstance(options, list) and len(options) > 0:
        return question, options
    return _default_branch_followup(challenge)


def _resolve_option(user_text: str, options: list[str]) -> str | None:
    normalized = _normalize(user_text)
    if not normalized:
        return None

    exact_map = {_normalize(opt): opt for opt in options}
    if normalized in exact_map:
        return exact_map[normalized]

    for opt in options:
        if normalized in _normalize(opt) or _normalize(opt) in normalized:
            return opt

    return None


def _service_mapping(challenge: str) -> dict[str, str]:
    mapping = {
        "Growing the business": {
            "service_type": "Technology & Growth",
            "service_needed": "Business Strategy",
        },
        "Reducing costs": {
            "service_type": "Finance & Compliance",
            "service_needed": "Virtual CFO",
        },
        "People & HR challenges": {
            "service_type": "People & Workforce",
            "service_needed": "HR Consulting",
        },
        "Compliance & Legal": {
            "service_type": "Finance & Compliance",
            "service_needed": "Legal & Regulatory",
        },
        "AI & Automation": {
            "service_type": "Technology & Growth",
            "service_needed": "AI & Data Science",
        },
        "Operational inefficiencies": {
            "service_type": "Technology & Growth",
            "service_needed": "Business Strategy",
        },
        "Decision making & reporting": {
            "service_type": "Technology & Growth",
            "service_needed": "AI & Data Science",
        },
        "Not sure": {
            "service_type": "Technology & Growth",
            "service_needed": "Business Strategy",
        },
    }
    return mapping.get(challenge, {})


def _build_final_response(
    profile: dict[str, str],
    challenge: str,
    branch_response: str,
    priority: str,
    selected_focus: str | None = None,
) -> tuple[str, str, dict[str, str]]:
    config = _load_config()
    final_cfg = config.get("final_diagnosis", {})

    focus_areas = final_cfg.get("focus_areas", [])
    outcomes = final_cfg.get("typical_outcomes", [])
    expected_outcomes = [
        "Reduced operational delays",
        "Better decision-making",
        "Lower operating costs",
        "Improved productivity",
    ]

    lines = [branch_response, ""]
    if selected_focus:
        lines.append(f"You indicated your key focus area as: {selected_focus}")
        lines.append("")

    lines.extend(["Based on your responses...", f"Your likely priority: {priority}", "", "Suggested Focus Areas"])

    for area in focus_areas:
        lines.append(f"- {area}")

    lines.append("")
    lines.append("Expected Business Outcomes")
    for outcome in expected_outcomes:
        lines.append(f"- {outcome}")

    lines.append("")
    lines.append("Based on what you've shared, we believe your business would benefit most from:")
    lines.append(final_cfg.get("label", "Operational Excellence + AI Enablement"))
    lines.append("")
    lines.append("Typical outcomes include:")
    for outcome in outcomes:
        lines.append(f"- {outcome}")
    lines.append("")
    lines.append("Would you like a consultant to discuss how these outcomes could apply to your business?")

    updates = {
        "assessment_status": "completed",
        "assessment_phase": "inactive",
        "assessment_challenge": challenge,
        "assessment_priority": priority,
    }
    updates.update(_service_mapping(challenge))

    missing = missing_required_fields(profile)
    next_field = missing[0] if missing else None
    next_prompt = build_next_required_prompt([next_field]) if next_field else ""

    if next_prompt:
        lines.append("")
        lines.append("To arrange your complimentary 20-minute strategy discussion:")
        lines.append(next_prompt)

    return "\n".join(lines).strip(), (STATE_INTAKE_FIELDS if next_prompt else STATE_OPEN), updates


_START_TOKENS = {
    "start assessment",
    "start",
    "begin",
    "begin assessment",
    "take assessment",
}

PHASE_WELCOME = "welcome"
PHASE_Q1 = "q1"
PHASE_Q2 = "q2"
PHASE_CAPTURE_NAME = "capture_name"
PHASE_CAPTURE_CONTACT_EMAIL = "capture_contact_email"
PHASE_CAPTURE_CONTACT_PHONE = "capture_contact_phone"
PHASE_COMPLETE = "complete"

# Section 2, Branch A-E: challenges that branch into a sub-question.
# Anything else (Branch F) routes straight to the lead-capture sequence.
BRANCH_CHALLENGES = {
    "Growing the business",
    "Operational inefficiencies",
    "People & HR challenges",
    "AI & Automation",
    "Compliance & Legal",
}

# Section 3 progressive lead-capture prompts.
NAME_CAPTURE_PROMPT = (
    "Great job completing the diagnostic. Who do we have the pleasure of addressing?"
)
CONTACT_EMAIL_PROMPT = (
    "Thanks, {name}! Where should we send your custom Strategic Agenda "
    "and strategy session access details?"
)
CONTACT_PHONE_PROMPT = (
    "Perfect. And what is the best mobile number to reach you on, so we can "
    "share your session link and calendar invite?"
)


def _parse_name(text: str) -> str | None:
    t = (text or "").strip()
    if not t or "@" in t or re.search(r"\d", t):
        return None
    words = t.split()
    if not (1 <= len(words) <= 4):
        return None
    if not re.fullmatch(r"[A-Za-z\s.'-]+", t):
        return None
    if t.lower() in {"yes", "no", "start", "begin", "ok", "okay", "thanks"}:
        return None
    return " ".join(words)


def _parse_email(text: str) -> str | None:
    email_match = EMAIL_RE.search(text or "")
    if not email_match:
        return None
    email = email_match.group(0)
    if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return email
    return None


def _parse_phone(text: str) -> str | None:
    phone_match = PHONE_RE.search(text or "")
    if not phone_match:
        return None
    digits = "".join(ch for ch in phone_match.group(0) if ch.isdigit())
    if len(digits) < 10:
        return None
    raw = " ".join(phone_match.group(0).split())
    return ("+" + digits) if raw.startswith("+") else digits


def _priority_for(challenge: str, branches: dict[str, Any]) -> str:
    return str(branches.get(challenge, {}).get("priority", "Operational Transformation"))


def _render_focus(focus: dict) -> str:
    title = str(focus.get("focus_title", "Your Strategic Agenda")).strip()
    summary = str(focus.get("validation_summary", "")).strip()
    items = focus.get("recommended_agenda_items") or []
    lines = [title, ""]
    if summary:
        lines.append(summary)
        lines.append("")
    lines.append("Your custom Strategic Agenda:")
    for item in items:
        lines.append(f"- {item}")
    return "\n".join(lines)


async def handle_assessment_turn(
    current_state: str,
    profile: dict[str, str],
    query: str,
    session_id: str | None = None,
) -> AssessmentTurnResult:
    config = _load_config()
    q1 = config.get("question_1", {})
    q1_question = str(q1.get("question", "")).strip()
    q1_options = q1.get("options", [])
    branches = config.get("branches", {})

    phase = profile.get("assessment_phase", "inactive")
    normalized_query = _normalize(query)

    if phase in (PHASE_WELCOME, "inactive") or normalized_query in _START_TOKENS:
        return AssessmentTurnResult(
            handled=True,
            next_state=STATE_OPEN,
            response_text=q1_question or "Let's begin the assessment.",
            actions=_actions(q1_options),
            profile_updates={
                "assessment_phase": PHASE_Q1,
                "assessment_status": "active",
            },
        )

    if phase == PHASE_Q1:
        selected = _resolve_option(query, q1_options)
        if selected is None:
            return AssessmentTurnResult(
                handled=True,
                next_state=STATE_OPEN,
                response_text=(
                    f"Please choose one of the assessment options.\n\n"
                    f"{q1_question}"
                ),
                actions=_actions(q1_options),
            )

        if selected not in BRANCH_CHALLENGES:
            log_lead_capture_step(session_id, "branch_fallthrough", {"challenge": selected})
            return AssessmentTurnResult(
                handled=True,
                next_state=STATE_OPEN,
                response_text=NAME_CAPTURE_PROMPT,
                actions=[],
                profile_updates={
                    "assessment_phase": PHASE_CAPTURE_NAME,
                    "assessment_status": "active",
                    "assessment_challenge": selected,
                    "assessment_focus": "Not specified",
                },
                lead_step="name",
            )

        branch = branches.get(selected, {})
        branch_question, branch_options = _resolve_branch_followup(selected, branch)
        return AssessmentTurnResult(
            handled=True,
            next_state=STATE_OPEN,
            response_text=f"{branch.get('response', '')}\n\n{branch_question}",
            actions=_actions(branch_options),
            profile_updates={
                "assessment_phase": PHASE_Q2,
                "assessment_status": "active",
                "assessment_challenge": selected,
            },
        )

    if phase == PHASE_Q2:
        selected_challenge = profile.get("assessment_challenge", "")
        branch = branches.get(selected_challenge, {})
        _, branch_options = _resolve_branch_followup(selected_challenge, branch)
        selected_followup = _resolve_option(query, branch_options)
        if selected_followup is None:
            return AssessmentTurnResult(
                handled=True,
                next_state=STATE_OPEN,
                response_text="Please choose one option so I can continue the assessment.",
                actions=_actions(branch_options),
            )
        return AssessmentTurnResult(
            handled=True,
            next_state=STATE_OPEN,
            response_text=NAME_CAPTURE_PROMPT,
            actions=[],
            profile_updates={
                "assessment_phase": PHASE_CAPTURE_NAME,
                "assessment_focus": selected_followup,
            },
            lead_step="name",
        )

    if phase == PHASE_CAPTURE_NAME:
        name = _parse_name(query)
        if not name:
            return AssessmentTurnResult(
                handled=True,
                next_state=STATE_OPEN,
                response_text="Apologies, I didn't catch your name. " + NAME_CAPTURE_PROMPT,
                actions=[],
                lead_step="name",
            )
        log_lead_capture_step(session_id, "capture_name", {"name": name})
        return AssessmentTurnResult(
            handled=True,
            next_state=STATE_OPEN,
            response_text=CONTACT_EMAIL_PROMPT.format(name=name),
            actions=[],
            profile_updates={
                "assessment_phase": PHASE_CAPTURE_CONTACT_EMAIL,
                "name": name,
            },
            lead_step="email",
        )

    if phase == PHASE_CAPTURE_CONTACT_EMAIL:
        email = _parse_email(query)
        if not email:
            return AssessmentTurnResult(
                handled=True,
                next_state=STATE_OPEN,
                response_text=(
                    "We couldn't read a valid email there. "
                    + CONTACT_EMAIL_PROMPT.format(name=profile.get("name", ""))
                ),
                actions=[],
                lead_step="email",
            )
        log_lead_capture_step(session_id, "capture_contact_email", {"email": email})
        return AssessmentTurnResult(
            handled=True,
            next_state=STATE_OPEN,
            response_text=CONTACT_PHONE_PROMPT,
            actions=[],
            profile_updates={
                "assessment_phase": PHASE_CAPTURE_CONTACT_PHONE,
                "email": email,
            },
            lead_step="phone",
        )

    if phase == PHASE_CAPTURE_CONTACT_PHONE:
        phone = _parse_phone(query)
        if not phone:
            return AssessmentTurnResult(
                handled=True,
                next_state=STATE_OPEN,
                response_text=(
                    "That doesn't look like a valid mobile number (we need at least 10 digits). "
                    + CONTACT_PHONE_PROMPT
                ),
                actions=[],
                lead_step="phone",
            )
        log_lead_capture_step(session_id, "capture_contact_phone", {"phone": phone})

        primary = profile.get("assessment_challenge", "")
        sub = profile.get("assessment_focus", "Not specified")
        focus_report = await generate_assessment_focus(
            primary_challenge=primary,
            sub_challenge=sub,
        )
        return AssessmentTurnResult(
            handled=True,
            next_state=STATE_OPEN,
            response_text=_render_focus(focus_report),
            actions=_final_actions(),
            profile_updates={
                "assessment_phase": PHASE_COMPLETE,
                "assessment_status": "completed",
                "phone": phone,
                "assessment_priority": _priority_for(primary, branches),
            },
            focus_report=focus_report,
            lead_step=None,
        )

    return AssessmentTurnResult(handled=False)
def get_active_assessment_prompt(profile: dict[str, str]) -> tuple[str, list[dict[str, str]]] | None:
    """Return the current configured assessment prompt and options, when assessment is active."""
    config = _load_config()
    phase = profile.get("assessment_phase", "inactive")

    q1 = config.get("question_1", {})
    q1_question = str(q1.get("question", "")).strip()
    q1_options = q1.get("options", [])
    branches = config.get("branches", {})

    if phase == "q1" and q1_question and q1_options:
        return q1_question, _actions(q1_options)

    if phase == "q2":
        selected_challenge = profile.get("assessment_challenge", "")
        branch = branches.get(selected_challenge, {})
        branch_question = str(branch.get("question", "")).strip()
        branch_options = branch.get("options", [])
        if branch_question and branch_options:
            return branch_question, _actions(branch_options)

    return None
