from __future__ import annotations

import re

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(r"(?:\+?\d[\d\s\-]{7,}\d)")

INTEREST_KEYWORDS = {
    "business strategy": "Business Strategy",
    "hr": "HR",
    "finance": "Finance",
    "legal": "Legal",
    "it": "IT",
    "ai": "AI & Data",
    "data": "AI & Data",
    "strategy": "Strategy",
    "payroll": "Payroll",
    "hiring": "Executive Hiring",
    "executive": "Executive Hiring",
    "eor": "EOR",
}

CONTACT_MODE_PATTERNS = {
    "call": "Call",
    "phone": "Call",
    "email": "Email",
    "mail": "Email",
    "whatsapp": "WhatsApp",
}

SERVICE_KEYWORDS = {
    "business strategy": "Business Strategy",
    "hr": "HR Consulting",
    "hiring": "Executive Search",
    "recruit": "Executive Search",
    "payroll": "Payroll & Compliance",
    "cfo": "Virtual CFO",
    "tax": "GST & Tax Advisory",
    "gst": "GST & Tax Advisory",
    "legal": "Legal & Regulatory",
    "it": "IT & Digital Transformation",
    "ai": "AI & Data Science",
    "data": "AI & Data Science",
    "technology": "IT & Digital Transformation",
    "digital": "IT & Digital Transformation",
    "strategy": "Business Strategy",
    "growth": "Business Strategy",
    "people": "HR Consulting",
    "workforce": "EOR & Workforce",
    "compliance": "Legal & Regulatory",
    "eor": "EOR & Workforce",
}

# Map services to domain categories
SERVICE_TO_DOMAIN = {
    "Business Strategy": "Technology & Growth",
    "HR Consulting": "People & Workforce",
    "Executive Search": "People & Workforce",
    "Payroll & Compliance": "People & Workforce",
    "Virtual CFO": "Finance & Compliance",
    "GST & Tax Advisory": "Finance & Compliance",
    "Legal & Regulatory": "Finance & Compliance",
    "IT & Digital Transformation": "Technology & Growth",
    "AI & Data Science": "Technology & Growth",
    "EOR & Workforce": "People & Workforce",
}

TIMELINE_HINTS = [
    "immediate",
    "2 weeks",
    "1 month",
    "3 months",
    "asap",
]

NON_NAME_SINGLE_WORDS = {
    "yes",
    "no",
    "hi",
    "hello",
    "hey",
    "ok",
    "okay",
    "thanks",
    "thankyou",
    "interested",
    "service",
    "services",
    "consultant",
    "help",
    "send",
    "message",
    "schedule",
    "book",
    "call",
    "what",
    "where",
    "when",
    "why",
    "how",
}


def _contains_token(text: str, token: str) -> bool:
    normalized = text.lower().strip()
    if " " in token:
        return token in normalized
    return re.search(rf"\b{re.escape(token)}\b", normalized) is not None


def _normalize_phone(candidate: str) -> str | None:
    raw = " ".join(candidate.split())
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) < 10:
        return None

    if raw.startswith("+"):
        return "+" + digits
    return digits


def extract_profile_updates(text: str, *, allow_plain_name: bool = False) -> dict[str, str]:
    lowered = text.lower()
    updates: dict[str, str] = {}

    email_match = EMAIL_RE.search(text)
    if email_match:
        updates["email"] = email_match.group(0)

    phone_match = PHONE_RE.search(text)
    if phone_match:
        normalized_phone = _normalize_phone(phone_match.group(0))
        if normalized_phone:
            updates["phone"] = normalized_phone

    # Capture only a likely person name (1-4 words) and avoid swallowing the next sentence.
    name_patterns = [
        r"(?:my name is|i am|this is)\s+([A-Za-z][A-Za-z'-]*(?:\s+[A-Za-z][A-Za-z'-]*){0,3})(?=$|[.,;!?])",
        r"(?:it's|its|im)\s+([A-Za-z][A-Za-z'-]*(?:\s+[A-Za-z][A-Za-z'-]*){0,3})(?=$|[.,;!?])",
    ]
    for pattern in name_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            candidate = " ".join(match.group(1).split())
            if len(candidate) >= 2:
                updates["name"] = candidate
                break

    if "name" not in updates and allow_plain_name:
        plain = text.strip()
        plain_words = plain.split()
        lower_plain = plain.lower().strip()
        if (
            plain
            and "@" not in plain
            and not re.search(r"\d", plain)
            and 1 <= len(plain_words) <= 4
            and re.fullmatch(r"[A-Za-z\s.'-]+", plain)
            and lower_plain not in NON_NAME_SINGLE_WORDS
            and not lower_plain.endswith("?")
            and not lower_plain.startswith(("what ", "where ", "when ", "why ", "how ", "can ", "do ", "is ", "are "))
        ):
            updates["name"] = " ".join(plain_words)

    for token, value in INTEREST_KEYWORDS.items():
        if _contains_token(lowered, token):
            updates["area_of_interest"] = value
            break

    for token, value in CONTACT_MODE_PATTERNS.items():
        if _contains_token(lowered, token):
            updates["contact_mode"] = value
            break

    for token, value in SERVICE_KEYWORDS.items():
        if _contains_token(lowered, token):
            updates["service_needed"] = value
            # Also map to domain
            domain = SERVICE_TO_DOMAIN.get(value)
            if domain:
                updates["service_type"] = domain
            break

    for hint in TIMELINE_HINTS:
        if hint in lowered:
            updates["timeline"] = hint
            break

    return updates


def build_profile_summary(profile: dict[str, str]) -> str:
    if not profile:
        return "(none captured yet)"

    ordered_keys = [
        "name",
        "email",
        "phone",
        "service_needed",
        "area_of_interest",
        "timeline",
        "contact_mode",
    ]
    lines: list[str] = []
    for key in ordered_keys:
        value = profile.get(key)
        if value:
            lines.append(f"{key}: {value}")
    return "\n".join(lines) if lines else "(none captured yet)"
