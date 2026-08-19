from __future__ import annotations

import re

from knowledge.service_catalog import get_service_catalog

# ============ STATE MACHINE CONSTANTS ============
STATE_OPEN = "OPEN"
STATE_INTAKE_FIELDS = "INTAKE_FIELDS"
STATE_INTAKE_SUBMITTED = "INTAKE_SUBMITTED"
STATE_DOMAIN_SELECTED = "DOMAIN_SELECTED"
STATE_CONSULTANTS_SHOWN = "CONSULTANTS_SHOWN"
STATE_CONVERSATION = "CONVERSATION"

REQUIRED_FIELDS = ["name", "phone", "email"]

YES_TOKENS = {"yes", "y", "interested", "show", "services", "service", "tell me services"}
NO_EXIT_TOKENS = {"no", "not interested", "quit", "exit", "stop", "bye", "goodbye", "good bye", "close", "done", "see you", "take care"}
DIRECT_INTENT_HINTS = {
    "consultant",
    "recommend",
    "need",
    "looking for",
    "service",
    "pricing",
    "cost",
    "quote",
    "proposal",
    "help with",
    "project",
    "hr",
    "finance",
    "legal",
    "it",
    "ai",
    "data",
    "strategy",
    "technology",
    "digital",
    "growth",
    "workforce",
    "people",
    "compliance",
}

# ─── ACTION INTENT DETECTION ───────────────────────────────────────────────────
MEETING_INTENT_TOKENS = {"schedule", "book", "meeting", "calendar", "availability", "time", "slot", "appointment"}
CALLBACK_INTENT_TOKENS = {"call me back", "callback", "ring", "phone call", "call me", "ring me", "dial"}
MESSAGE_INTENT_TOKENS = {"message", "send message", "contact", "write", "reach out"}
SERVICE_INQUIRY_TOKENS = {"services", "offerings", "service you offer", "what do you offer", "your services", "service offerings", "list services", "see services", "show services", "service catalog"}
QUESTION_PREFIXES = ("what", "where", "when", "why", "how", "can", "could", "do", "does", "is", "are")
DOMAIN_SELECTION_HINTS = {
    "consultant",
    "consulting",
    "need",
    "looking for",
    "recommend",
    "connect",
    "book",
    "schedule",
    "hire",
    "recruit",
}


def has_service_inquiry_intent(text: str) -> bool:
    """Detect if user is asking for services catalog."""
    lowered = text.lower().strip()
    if not lowered:
        return False
    if any(token in lowered for token in SERVICE_INQUIRY_TOKENS):
        return True

    # Handle specific service queries like "What is Virtual CFO service?"
    service_name_hints = {
        "virtual cfo",
        "gst",
        "tax",
        "legal",
        "payroll",
        "executive search",
        "hr consulting",
        "ai",
        "data science",
        "digital transformation",
        "business strategy",
        "eor",
    }
    return "service" in lowered and any(hint in lowered for hint in service_name_hints)


def detect_action_intent(text: str) -> str | None:
    """Detect if user wants: meeting_request, callback_request, or message_consultant."""
    lowered = text.lower().strip()
    if not lowered:
        return None

    # During lead capture users often type details like "my email is..." or numbers.
    # Do not treat those as action intents.
    if "my email is" in lowered or "email is" in lowered or "my phone is" in lowered:
        return None

    # Check for exact phrases first
    for token in CALLBACK_INTENT_TOKENS:
        if token in lowered:
            return "callback_request"

    for token in MESSAGE_INTENT_TOKENS:
        if token in lowered:
            return "message_consultant"

    for token in MEETING_INTENT_TOKENS:
        if token in lowered:
            return "meeting_request"

    return None


def looks_like_lead_submission(text: str) -> bool:
    lowered = text.lower().strip()
    if not lowered:
        return False

    has_name_phrase = any(token in lowered for token in ["my name is", "i am", "this is"]) 
    has_email = "@" in lowered and "." in lowered
    digit_count = sum(1 for ch in lowered if ch.isdigit())
    has_phone = ("phone" in lowered or "mobile" in lowered) and digit_count >= 10

    # Consider it a lead submission when at least two strong signals are present.
    signal_count = sum([1 if has_name_phrase else 0, 1 if has_email else 0, 1 if has_phone else 0])
    return signal_count >= 2


def _is_question_like(text: str) -> bool:
    normalized = text.lower().strip()
    if not normalized:
        return False
    if normalized.endswith("?"):
        return True
    return any(normalized.startswith(f"{prefix} ") for prefix in QUESTION_PREFIXES)


def is_domain_selection_intent(text: str) -> bool:
    normalized = text.lower().strip()
    domain = detect_domain_interest(normalized)
    if not domain:
        return False

    if normalized in {
        "people & workforce",
        "finance & compliance",
        "technology & growth",
    }:
        return True

    if _is_question_like(normalized):
        return False

    return any(_contains_token(normalized, token) for token in DOMAIN_SELECTION_HINTS)


def build_action_followup_response(action_intent: str, profile: dict[str, str]) -> str:
    name = (profile.get("name") or "there").strip() or "there"
    phone = profile.get("phone")
    email = profile.get("email")
    contact_line = []
    if email:
        contact_line.append(email)
    if phone:
        contact_line.append(phone)
    contact_hint = f" using {', '.join(contact_line)}" if contact_line else ""

    if action_intent == "meeting_request":
        return (
            f"Certainly, {name}. I can help schedule a discovery call{contact_hint}. "
            "Please share your preferred date and time slot, and I will proceed with the coordination."
        )

    if action_intent == "callback_request":
        return (
            f"Certainly, {name}. I can arrange a callback{contact_hint}. "
            "Please share your preferred callback window and topic so we can connect you to the right consultant."
        )

    return (
        f"Certainly, {name}. I can help send your request to the consultant team{contact_hint}. "
        "Please share a brief message with your requirement and timeline."
    )

DOMAIN_INTENT_MAP = {
    "People & Workforce": {
        "people",
        "workforce",
        "hr",
        "human resources",
        "payroll",
        "recruitment",
        "hiring",
        "eor",
        "talent",
        "staffing",
    },
    "Finance & Compliance": {
        "finance",
        "compliance",
        "tax",
        "gst",
        "legal",
        "cfo",
        "regulatory",
        "accounting",
        "audit",
    },
    "Technology & Growth": {
        "technology",
        "tech",
        "it",
        "digital",
        "ai",
        "data",
        "strategy",
        "business strategy",
        "growth",
        "transformation",
        "innovation",
        "data science",
    },
}

DOMAIN_SEARCH_QUERIES = {
    "People & Workforce": "HR payroll recruitment executive search workforce EOR consultant",
    "Finance & Compliance": "finance compliance legal GST tax virtual CFO consultant",
    "Technology & Growth": "technology IT digital transformation AI data science business strategy consultant",
}


def _contains_token(text: str, token: str) -> bool:
    normalized = text.lower().strip()
    if " " in token:
        return token in normalized
    return re.search(rf"\b{re.escape(token)}\b", normalized) is not None


def is_exit_intent(text: str) -> bool:
    return any(_contains_token(text, token) for token in NO_EXIT_TOKENS)


def is_affirmative_interest(text: str) -> bool:
    return any(_contains_token(text, token) for token in YES_TOKENS)


def has_direct_consulting_intent(text: str) -> bool:
    normalized = text.lower().strip()
    if not normalized:
        return False
    return any(_contains_token(normalized, token) for token in DIRECT_INTENT_HINTS)


def detect_domain_interest(text: str) -> str | None:
    normalized = text.lower().strip()
    if not normalized:
        return None

    for domain, tokens in DOMAIN_INTENT_MAP.items():
        if normalized == domain.lower():
            return domain
        if any(_contains_token(normalized, token) for token in tokens):
            return domain
    return None


def build_domain_search_query(domain: str) -> str:
    return DOMAIN_SEARCH_QUERIES.get(domain, domain)


def build_intro_prompt() -> str:
    return (
        "Welcome to Ofstride Services LLP. 👋 I'm your virtual assistant. Every business faces challenges. Let's identify yours and suggest a practical way forward. It takes less than 2 minutes.\n\n"
        "To begin, please share your name, mobile number, and email."
    )


def build_assessment_start_prompt(name: str | None = None) -> str:
    if name:
        return (
            f"Thank you, {name}. Your details are captured.\n\n"
            "Please click Start Assessment to begin the guided questionnaire."
        )
    return "Thank you. Your details are captured. Please click Start Assessment to begin the guided questionnaire."


def missing_required_fields(profile: dict[str, str]) -> list[str]:
    missing: list[str] = []
    for field in REQUIRED_FIELDS:
        if not profile.get(field):
            missing.append(field)
    return missing


def build_next_required_prompt(missing_fields: list[str]) -> str:
    if not missing_fields:
        return ""

    next_field = missing_fields[0]
    if next_field == "name":
        return "What's your name?"

    if next_field == "phone":
        return "Could you share your phone number?"

    if next_field == "email":
        return "What's your email address?"

    return "One more detail please?"


def build_intake_completed_message() -> str:
    return "Thank you. Now let me find the right consultant for you."


def build_interest_prompt(name: str | None = None) -> str:
    return (
        "Which service area interests you?\n"
        "• People & Workforce\n"
        "• Finance & Compliance\n"
        "• Technology & Growth"
    )


def build_services_catalog_response() -> tuple[str, list[dict]]:
    """Build services catalog response from CSV data."""
    catalog = get_service_catalog()
    message = catalog.get_services_summary()

    sources = [
        {
            "content": "Ofstride service catalog",
            "metadata": {
                "source": "services.csv",
                "source_type": "company_service_catalog",
            },
        }
    ]
    return message, sources


def build_exit_message() -> str:
    return (
        "No problem. I've saved your information. Come back anytime to continue, "
        "and I'll pick up where we left off."
    )


def append_cta_options(answer: str) -> str:
    base = answer.rstrip()
    lowered = base.lower()
    if (
        "schedule a call" in lowered
        or "send a message" in lowered
        or "would you like to continue with:" in lowered
    ):
        return base

    return (
        f"{base}\n\n"
        "Would you like to continue with:\n"
        "1) Send a message\n"
        "2) Schedule a call"
    )


# ============ STATE MACHINE ORCHESTRATION ============
def get_next_state(
    current_state: str,
    profile: dict[str, str],
    query: str,
) -> tuple[str, str, list[dict]]:
    """
    Determine next state and response based on current state, profile, and user query.
    
    Returns: (next_state, response_text, actions)
    """
    
    # Check for service inquiry at any state (highest priority)
    if has_service_inquiry_intent(query):
        services_msg, _ = build_services_catalog_response()
        return (
            STATE_INTAKE_SUBMITTED,
            services_msg,
            [
                {"id": "act_1", "label": "People & Workforce", "value": "People & Workforce", "kind": "quick_reply"},
                {"id": "act_2", "label": "Finance & Compliance", "value": "Finance & Compliance", "kind": "quick_reply"},
                {"id": "act_3", "label": "Technology & Growth", "value": "Technology & Growth", "kind": "quick_reply"},
            ],
        )
    
    # Check for exit intent at any state
    if is_exit_intent(query):
        return STATE_OPEN, build_exit_message(), [
            {"id": "act_1", "label": "Send a message", "value": "Send a message", "kind": "quick_reply"},
            {"id": "act_2", "label": "Schedule a call", "value": "Schedule a call", "kind": "quick_reply"},
        ]
    
    # STATE: OPEN (chat just started or state recovered after TTL/instance changes)
    if current_state == STATE_OPEN:
        missing = missing_required_fields(profile)
        domain = detect_domain_interest(query)

        # Enforce lead capture before progressing to service/domain conversation.
        if missing:
            return (
                STATE_INTAKE_FIELDS,
                build_next_required_prompt(missing),
                [],
            )

        # If lead appears to be submitted in one message, move directly to assessment prompt.
        if not missing and looks_like_lead_submission(query):
            return (
                STATE_INTAKE_SUBMITTED,
                build_assessment_start_prompt(profile.get("name")),
                [
                    {"id": "act_1", "label": "Start Assessment", "value": "Start Assessment", "kind": "quick_reply"},
                ],
            )

        # If lead details are complete, default to assessment start prompt.
        if not missing and not query.strip():
            return (
                STATE_INTAKE_SUBMITTED,
                build_assessment_start_prompt(profile.get("name")),
                [
                    {"id": "act_1", "label": "Start Assessment", "value": "Start Assessment", "kind": "quick_reply"},
                ],
            )

        # For informational questions (website/company/services flow), use conversation mode first.
        if _is_question_like(query) or len(query.strip().split()) >= 5:
            return (
                STATE_CONVERSATION,
                "",
                [],
            )

        # If user selects a domain and profile is complete, route directly to consultant retrieval.
        if domain and not missing and is_domain_selection_intent(query):
            return (
                STATE_DOMAIN_SELECTED,
                f"Perfect! I'm finding the best {domain} consultant for you.",
                [],
            )

        # If user has domain/consulting intent but required intake fields are missing,
        # continue the intake journey from the next missing field.
        if (domain and is_domain_selection_intent(query)) or has_direct_consulting_intent(query):
            if missing:
                return (
                    STATE_INTAKE_FIELDS,
                    build_next_required_prompt(missing),
                    [],
                )
            return (
                STATE_INTAKE_SUBMITTED,
                build_interest_prompt(profile.get("name")),
                [
                    {"id": "act_1", "label": "Yes, show services", "value": "Yes, show services", "kind": "quick_reply"},
                    {"id": "act_2", "label": "Schedule a call", "value": "Schedule a call", "kind": "quick_reply"},
                ],
            )

        # "Yes, show services" should never reset to the generic welcome.
        if is_affirmative_interest(query):
            if missing:
                return (
                    STATE_INTAKE_FIELDS,
                    build_next_required_prompt(missing),
                    [],
                )
            return (
                STATE_INTAKE_SUBMITTED,
                build_interest_prompt(profile.get("name")),
                [
                    {"id": "act_1", "label": "People & Workforce", "value": "People & Workforce", "kind": "quick_reply"},
                    {"id": "act_2", "label": "Finance & Compliance", "value": "Finance & Compliance", "kind": "quick_reply"},
                    {"id": "act_3", "label": "Technology & Growth", "value": "Technology & Growth", "kind": "quick_reply"},
                ],
            )

        # Generic fallback after lead capture.
        return (
            STATE_INTAKE_SUBMITTED,
            build_assessment_start_prompt(profile.get("name")),
            [
                {"id": "act_1", "label": "Start Assessment", "value": "Start Assessment", "kind": "quick_reply"},
            ],
        )
    
    # STATE: INTAKE_FIELDS (collecting name, phone, email)
    if current_state == STATE_INTAKE_FIELDS:
        missing = missing_required_fields(profile)
        
        if missing:
            # Still have missing fields, stay in INTAKE_FIELDS
            next_prompt = build_next_required_prompt(missing)
            return (
                STATE_INTAKE_FIELDS,
                next_prompt,
                [],
            )
        else:
            # All lead fields collected; gate next step to questionnaire start.
            return (
                STATE_INTAKE_SUBMITTED,
                build_assessment_start_prompt(profile.get("name")),
                [
                    {"id": "act_1", "label": "Start Assessment", "value": "Start Assessment", "kind": "quick_reply"},
                ],
            )
    
    # STATE: INTAKE_SUBMITTED (waiting for domain selection or service catalog view)
    if current_state == STATE_INTAKE_SUBMITTED:
        missing = missing_required_fields(profile)
        if missing:
            return (
                STATE_INTAKE_FIELDS,
                build_next_required_prompt(missing),
                [],
            )

        if query.strip().lower() in {"start assessment", "assessment", "start"}:
            return (
                STATE_OPEN,
                "Start Assessment",
                [],
            )

        action_intent = detect_action_intent(query)
        if action_intent:
            return (
                STATE_CONVERSATION,
                build_action_followup_response(action_intent, profile),
                [
                    {"id": "act_1", "label": "Share preferred date/time", "value": "Share preferred date/time", "kind": "quick_reply"},
                    {"id": "act_2", "label": "Send a message", "value": "Send a message", "kind": "quick_reply"},
                ],
            )

        # Check if domain is already known from earlier conversation
        stored_domain = profile.get("service_type")
        domain = detect_domain_interest(query) or stored_domain
        
        if domain and is_domain_selection_intent(query):
            # User selected a domain (or it's already known)
            return (
                STATE_DOMAIN_SELECTED,
                f"Perfect! I'm finding the best {domain} consultant for you.",
                [],
            )
        elif is_affirmative_interest(query):
            # User wants to see services catalog
            services_msg, _ = build_services_catalog_response()
            return (
                STATE_DOMAIN_SELECTED,
                services_msg,
                [
                    {"id": "act_1", "label": "People & Workforce", "value": "People & Workforce", "kind": "quick_reply"},
                    {"id": "act_2", "label": "Finance & Compliance", "value": "Finance & Compliance", "kind": "quick_reply"},
                    {"id": "act_3", "label": "Technology & Growth", "value": "Technology & Growth", "kind": "quick_reply"},
                ],
            )
        else:
            if _is_question_like(query):
                return (STATE_CONVERSATION, "", [])
            # Re-ask for assessment start.
            return (
                STATE_INTAKE_SUBMITTED,
                build_assessment_start_prompt(profile.get("name")),
                [
                    {"id": "act_1", "label": "Start Assessment", "value": "Start Assessment", "kind": "quick_reply"},
                ],
            )
    
    # STATE: DOMAIN_SELECTED (user selected domain, ready to show consultants)
    if current_state == STATE_DOMAIN_SELECTED:
        # In graph.py, this state triggers consultant retrieval
        # Move to CONSULTANTS_SHOWN (handled by graph.py after retrieval)
        return (
            STATE_CONSULTANTS_SHOWN,
            "",  # Response will be built by graph.py with consultant data
            [],
        )
    
    # STATE: CONSULTANTS_SHOWN (showing consultants, open for Q&A)
    if current_state == STATE_CONSULTANTS_SHOWN:
        action_intent = detect_action_intent(query)
        if action_intent:
            return (
                STATE_CONVERSATION,
                build_action_followup_response(action_intent, profile),
                [
                    {"id": "act_1", "label": "Share preferred date/time", "value": "Share preferred date/time", "kind": "quick_reply"},
                    {"id": "act_2", "label": "Connect me now", "value": "Connect me now", "kind": "quick_reply"},
                ],
            )

        domain = detect_domain_interest(query)
        if domain and is_domain_selection_intent(query):
            return (
                STATE_DOMAIN_SELECTED,
                f"Perfect! I'm finding the best {domain} consultant for you.",
                [],
            )

        if is_affirmative_interest(query):
            services_msg, _ = build_services_catalog_response()
            return (
                STATE_DOMAIN_SELECTED,
                services_msg,
                [
                    {"id": "act_1", "label": "People & Workforce", "value": "People & Workforce", "kind": "quick_reply"},
                    {"id": "act_2", "label": "Finance & Compliance", "value": "Finance & Compliance", "kind": "quick_reply"},
                    {"id": "act_3", "label": "Technology & Growth", "value": "Technology & Growth", "kind": "quick_reply"},
                ],
            )

        # User can ask follow-up questions, view more consultants, etc.
        # Stay in conversation mode
        return (
            STATE_CONVERSATION,
            "",  # Response will be LLM-generated
            [],
        )
    
    # STATE: CONVERSATION (ongoing Q&A)
    if current_state == STATE_CONVERSATION:
        action_intent = detect_action_intent(query)
        if action_intent:
            return (
                STATE_CONVERSATION,
                build_action_followup_response(action_intent, profile),
                [
                    {"id": "act_1", "label": "Share preferred date/time", "value": "Share preferred date/time", "kind": "quick_reply"},
                    {"id": "act_2", "label": "Send a message", "value": "Send a message", "kind": "quick_reply"},
                ],
            )

        domain = detect_domain_interest(query)
        if domain and is_domain_selection_intent(query):
            return (
                STATE_DOMAIN_SELECTED,
                f"Perfect! I'm finding the best {domain} consultant for you.",
                [],
            )

        if is_affirmative_interest(query):
            services_msg, _ = build_services_catalog_response()
            return (
                STATE_DOMAIN_SELECTED,
                services_msg,
                [
                    {"id": "act_1", "label": "People & Workforce", "value": "People & Workforce", "kind": "quick_reply"},
                    {"id": "act_2", "label": "Finance & Compliance", "value": "Finance & Compliance", "kind": "quick_reply"},
                    {"id": "act_3", "label": "Technology & Growth", "value": "Technology & Growth", "kind": "quick_reply"},
                ],
            )

        # Continue in conversation
        return (
            STATE_CONVERSATION,
            "",  # Response will be LLM-generated
            [],
        )
    
    # Default fallback
    return (
        STATE_OPEN,
        "I'm not sure what happened. Let's start fresh. How can I help you today?",
        [],
    )
