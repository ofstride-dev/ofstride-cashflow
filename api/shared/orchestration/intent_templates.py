"""
Deterministic response templates for high-frequency intents.

These templates bypass the LLM entirely to guarantee accuracy, speed, and
consistency for questions about the company, pricing, booking, and human handoff.
Add new intents here rather than in the main prompt system.
"""
from __future__ import annotations

import re
from typing import Callable

# ─── Intent detection token sets ─────────────────────────────────────────────

_COMPANY_INTRO_TOKENS: frozenset[str] = frozenset({
    "who is ofstride",
    "what is ofstride",
    "tell me about ofstride",
    "about ofstride",
    "what do you do",
    "what does ofstride do",
    "who are you",
    "what company is this",
    "describe ofstride",
    "ofstride services",
    "about your company",
    "your company",
    "what kind of company",
})

_PRICING_TOKENS: frozenset[str] = frozenset({
    "how much",
    "what is your price",
    "what are your rates",
    "pricing",
    "cost",
    "fee",
    "fees",
    "charges",
    "how much do you charge",
    "how much does it cost",
    "what do you charge",
    "rate card",
    "price list",
    "your price",
    "your rates",
    "cost of services",
    "service cost",
    "service fee",
    "consultation fee",
    "engagement cost",
    "retainer",
    "package",
})

_BOOKING_TOKENS: frozenset[str] = frozenset({
    "book a call",
    "book call",
    "schedule a call",
    "schedule call",
    "book a meeting",
    "schedule a meeting",
    "arrange a call",
    "arrange a meeting",
    "how do i book",
    "how to book",
    "set up a call",
    "set up call",
    "talk to a consultant",
    "speak to a consultant",
    "connect with a consultant",
    "book discovery",
    "discovery call",
    "free call",
    "cal.id",
    "book-call",
})

_HUMAN_HANDOFF_TOKENS: frozenset[str] = frozenset({
    "talk to human",
    "speak to human",
    "talk to a human",
    "speak to a human",
    "talk to a person",
    "speak to a person",
    "real person",
    "actual person",
    "human agent",
    "live agent",
    "connect me to someone",
    "connect me to a person",
    "escalate",
    "human support",
    "talk to support",
    "speak to support",
    "talk to someone",
    "speak to someone",
    "human help",
})

_LOCATION_TOKENS: frozenset[str] = frozenset({
    "where are you",
    "where is ofstride",
    "your office",
    "your location",
    "your address",
    "head office",
    "headquarters",
    "which city",
    "where located",
    "india office",
    "delhi office",
    "bangalore office",
    "bengaluru office",
})

_CONTACT_TOKENS: frozenset[str] = frozenset({
    "how do i contact",
    "how to contact",
    "contact details",
    "contact information",
    "get in touch",
    "reach you",
    "reach ofstride",
    "email address",
    "phone number",
    "your email",
    "your phone",
    "contact ofstride",
})


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    return text.lower().strip()


def _matches_any(text: str, tokens: frozenset[str]) -> bool:
    n = _normalize(text)
    return any(token in n for token in tokens)


# ─── Template response builders ───────────────────────────────────────────────

def _company_intro_response() -> str:
    return (
        "**Ofstride Services LLP** is an AI-powered business consulting firm established in 2019, "
        "headquartered in New Delhi with a presence in Bengaluru.\n\n"
        "We combine defence discipline, corporate leadership, and intelligent systems to help "
        "small and medium businesses grow with confidence.\n\n"
        "**Our service areas:**\n"
        "• People & Workforce — HR, Executive Search, Payroll & Compliance, EOR\n"
        "• Finance & Compliance — Virtual CFO, GST & Tax Advisory, Legal & Regulatory\n"
        "• Technology & Growth — IT & Digital, AI & Data Science\n"
        "• Strategy — Business Strategy & Process Improvement\n\n"
        "We serve industries including Manufacturing, Healthcare, Hospitality, Retail, "
        "Technology, Logistics, Education, Wellness & Fitness, Startups, MSMEs, and GCCs.\n\n"
        "Would you like to:\n"
        "1) Explore a specific service area\n"
        "2) Book a free 30-minute discovery call"
    )


def _pricing_response() -> str:
    return (
        "Ofstride does not publish standard rate cards — every engagement is scoped and priced "
        "based on your organisation's size, complexity, and requirements.\n\n"
        "**Our approach to pricing:**\n"
        "• All engagements begin with a **free 30-minute discovery call** — no cost, no commitment\n"
        "• After understanding your needs, we present a clear, fixed-scope proposal\n"
        "• Retainer, project, and advisory models are all available depending on the service\n"
        "• We are cost-aware by design — our model is built for SMEs and MSMEs\n\n"
        "The fastest way to get an accurate picture is a short conversation with our team.\n\n"
        "Would you like to:\n"
        "1) Book a free discovery call\n"
        "2) Send us a message with your requirements"
    )


def _booking_response() -> str:
    return (
        "You can book a **free 30-minute discovery call** directly — no forms, no waiting.\n\n"
        "**Ways to book:**\n"
        "• 🗓️ Online calendar: [ofstride.com/book-call](https://ofstride.com/book-call)\n"
        "• 📧 Email us: contact@ofstride.com\n"
        "• 📞 Call us: +91 89516 06862\n\n"
        "We respond to all inquiries within 24 hours on business days.\n\n"
        "Would you prefer I send your contact details to the team so they can reach you directly?"
    )


def _location_response() -> str:
    return (
        "Ofstride Services LLP operates from two offices in India:\n\n"
        "• **New Delhi** — Primary office (North India operations)\n"
        "• **Bengaluru** — South India operations\n\n"
        "We serve clients **pan-India** and work remotely across all states.\n\n"
        "To reach us: contact@ofstride.com | +91 89516 06862"
    )


def _contact_response() -> str:
    return (
        "Here are all the ways to reach Ofstride:\n\n"
        "• 📧 **Email:** contact@ofstride.com\n"
        "• 📞 **Phone:** +91 89516 06862\n"
        "• 🗓️ **Book a call:** [ofstride.com/book-call](https://ofstride.com/book-call)\n"
        "• 💬 **Contact form:** [ofstride.com/contact-form](https://ofstride.com/contact-form)\n\n"
        "We aim to respond to all inquiries within 24 hours on business days.\n\n"
        "Would you like me to pass your details to the team for a faster response?"
    )


def _human_handoff_response(profile: dict[str, str]) -> str:
    name = (profile.get("name") or "").strip()
    email = (profile.get("email") or "").strip()
    phone = (profile.get("phone") or "").strip()

    contact_parts: list[str] = []
    if email:
        contact_parts.append(f"email **{email}**")
    if phone:
        contact_parts.append(f"phone **{phone}**")

    contact_line = (
        f" I have your {' and '.join(contact_parts)} on file and will include it."
        if contact_parts
        else ""
    )
    greeting = f"Of course{', ' + name if name else ''}."

    return (
        f"{greeting} I am connecting you to the Ofstride support team now.{contact_line}\n\n"
        "A consultant will reach out to you directly. In the meantime, you can also:\n\n"
        "• 📧 **Email:** contact@ofstride.com\n"
        "• 📞 **Call:** +91 89516 06862\n"
        "• 🗓️ **Book a call:** [ofstride.com/book-call](https://ofstride.com/book-call)\n\n"
        "Is there anything specific you would like me to pass on to the team?"
    )


# ─── Public interface ─────────────────────────────────────────────────────────

#: Intent names returned by ``detect_intent``
INTENT_COMPANY_INTRO = "company_intro"
INTENT_PRICING = "pricing"
INTENT_BOOKING = "booking"
INTENT_LOCATION = "location"
INTENT_CONTACT = "contact"
INTENT_HUMAN_HANDOFF = "human_handoff"


def detect_intent(text: str) -> str | None:
    """
    Return the canonical intent name when the query matches a deterministic template,
    or ``None`` when it should fall through to the LLM/RAG pipeline.

    Human handoff is checked first because it overrides everything else.
    """
    if _matches_any(text, _HUMAN_HANDOFF_TOKENS):
        return INTENT_HUMAN_HANDOFF
    if _matches_any(text, _COMPANY_INTRO_TOKENS):
        return INTENT_COMPANY_INTRO
    if _matches_any(text, _PRICING_TOKENS):
        return INTENT_PRICING
    if _matches_any(text, _BOOKING_TOKENS):
        return INTENT_BOOKING
    if _matches_any(text, _LOCATION_TOKENS):
        return INTENT_LOCATION
    if _matches_any(text, _CONTACT_TOKENS):
        return INTENT_CONTACT
    return None


def render_intent(intent: str, profile: dict[str, str] | None = None) -> str:
    """
    Return the pre-built response string for a recognised intent.
    ``profile`` is required only for ``INTENT_HUMAN_HANDOFF``.
    """
    _profile = profile or {}
    _map: dict[str, Callable[[], str]] = {
        INTENT_COMPANY_INTRO: _company_intro_response,
        INTENT_PRICING: _pricing_response,
        INTENT_BOOKING: _booking_response,
        INTENT_LOCATION: _location_response,
        INTENT_CONTACT: _contact_response,
        INTENT_HUMAN_HANDOFF: lambda: _human_handoff_response(_profile),
    }
    fn = _map.get(intent)
    if fn is None:
        return ""
    return fn()
