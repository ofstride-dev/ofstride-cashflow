from __future__ import annotations

import re


_JAILBREAK_PATTERNS: list[re.Pattern] = [
    re.compile(r, re.IGNORECASE)
    for r in [
        r"ignore\s+(all\s+)?(previous|prior|system)\s+instructions",
        r"disregard\s+(all\s+)?(previous|prior|system)\s+instructions",
        r"(pretend|act|behave)\s+(as if|like)\s+you\s+(are|have\s+no)",
        r"you\s+are\s+now\s+(dan|an?\s+ai\s+without\s+restrictions)",
        r"(reveal|show|print|tell me|output|repeat)\s+(your\s+)?(system\s+prompt|instructions|context window|internal prompt)",
        r"(forget|override|bypass)\s+(all\s+)?(rules|restrictions|guardrails|filters)",
        r"(exfiltrate|extract|leak)\s+(data|information|context|secrets)",
        r"developer\s+mode",
        r"jailbreak",
        r"do\s+anything\s+now",
        r"no\s+restrictions",
        r"simulate\s+being\s+(an?\s+)?evil",
        r"(malware|virus|ransomware|keylogger|trojan)",
        r"sql\s+injection",
        r"(ddos|denial.of.service)",
        r"prompt\s+injection",
    ]
]


class TopicGuard:
    def __init__(self):
        self.allowed_topics = {
            "consultant",
            "consulting",
            "talent",
            "skills",
            "experience",
            "availability",
            "domain",
            "project",
            "finance",
            "hr",
            "legal",
            "it",
            "data",
            "ai",
            "strategy",
            "technology",
            "digital",
            "growth",
            "people",
            "workforce",
            "compliance",
            "tax",
            "gst",
            "cfo",
            "virtual cfo",
            "payroll",
            "recruitment",
            "hiring",
            "eor",
            "company",
            "ofstride",
            "partner",
            "partners",
            "client",
            "clients",
            "industry",
            "industries",
            "case study",
            "portfolio",
            "engagement",
            "delivery",
            "service",
            "services",
            "about",
            "contact",
            "support",
            "call",
            "email",
            # Contact and discussion intents
            "reach",
            "connect",
            "discuss",
            "discussion",
            "question",
            "query",
            "queries",
            "trusted",
            "work",
            "worked",
            "information",
            "info",
            "further",
            "more",
            "detail",
            "details",
            "help",
            "assist",
            "mail",
            "message",
            "follow",
            "followup",
            "follow-up",
            "schedule",
            "book",
            "meeting",
            "appointment",
            "confirm",
            "confirmation",
            "expect",
            "update",
            "response",
            "reply",
        }
        self.follow_up_tokens = {
            "yes",
            "no",
            "okay",
            "ok",
            "sure",
            "go ahead",
            "show",
            "continue",
            "next",
            "call",
            "book",
            "schedule",
            "thanks",
            "thank you",
            # greetings and introductions (intake flow)
            "hello",
            "hi",
            "hey",
            "good morning",
            "good afternoon",
            "good evening",
            "my name",
            "name is",
            "i am",
            "i'm",
            # exit intents
            "bye",
            "goodbye",
            "see you",
            "take care",
            "done",
            "exit",
            "quit",
        }
        self.disallowed_general_topics = {
            "weather",
            "temperature",
            "forecast",
            "news",
            "sports",
            "cricket",
            "football",
            "movie",
            "movies",
            "song",
            "songs",
            "recipe",
            "recipes",
            "joke",
            "jokes",
        }
        self.blocked_patterns = [
            "ignore previous instructions",
            "reveal system prompt",
            "developer instructions",
            "exfiltrate",
            "malware",
            "sql injection",
            "ddos",
        ]

    def check(self, text: str) -> tuple[bool, str | None]:
        normalized = text.lower().strip()
        if not normalized:
            return False, "Empty request."

        # Regex jailbreak detection (runs first — highest priority)
        for pattern in _JAILBREAK_PATTERNS:
            if pattern.search(normalized):
                return False, "Request violates safety guardrails."

        # Legacy substring patterns
        for pattern in self.blocked_patterns:
            if pattern in normalized:
                return False, "Request violates safety guardrails."

        if any(topic in normalized for topic in self.disallowed_general_topics):
            return False, "This assistant is limited to Ofstride services, consultant guidance, and business advisory topics."

        if any(topic in normalized for topic in self.allowed_topics):
            return True, None

        # Allow short conversational follow-ups and intake phrases (name, greeting, exit).
        if any(token in normalized for token in self.follow_up_tokens):
            return True, None

        return False, "This assistant is limited to Ofstride services, consultant guidance, and business advisory topics."

    def validate(self, text: str) -> bool:
        ok, _ = self.check(text)
        return ok
