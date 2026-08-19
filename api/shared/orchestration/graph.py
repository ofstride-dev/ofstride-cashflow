from __future__ import annotations

import logging
import time

from core.llm_factory import get_llm_factory
from core.settings import get_settings
from engagement.event_service import get_chat_event_service
from guardrails.topic_guard import TopicGuard
from ingestion.codebase_kb_pipeline import ensure_codebase_kb_seeded
from knowledge.company_profile import get_company_profile_context
from knowledge.service_catalog import get_service_catalog
from memory.session_store import get_session_store
from observability.langfuse_tracer import get_tracer
from observability.quality_counters import get_quality_counters
from orchestration.intake_flow import (
    append_cta_options,
    build_domain_search_query,
    build_exit_message,
    build_intro_prompt,
    build_intake_completed_message,
    build_next_required_prompt,
    build_interest_prompt,
    build_services_catalog_response,
    detect_domain_interest,
    has_direct_consulting_intent,
    is_affirmative_interest,
    is_exit_intent,
    missing_required_fields,
    get_next_state,
    STATE_OPEN,
    STATE_INTAKE_FIELDS,
    STATE_INTAKE_SUBMITTED,
    STATE_DOMAIN_SELECTED,
    STATE_CONSULTANTS_SHOWN,
    STATE_CONVERSATION,
)
from orchestration.assessment_flow import handle_assessment_turn, get_active_assessment_prompt
from orchestration.intent_templates import detect_intent, render_intent, INTENT_HUMAN_HANDOFF
from orchestration.session_profile import (
    build_profile_summary,
    extract_profile_updates,
)
from prompts.consultant_agent import build_system_prompt, build_user_prompt
from retrieval.local_consultant_directory import get_local_consultant_directory
from retrieval.qdrant_store import QdrantStore

_logger = logging.getLogger("ofstride.graph")


class RAGGraph:
    def __init__(self):
        self.settings = get_settings()
        self.topic_guard = TopicGuard()
        self.session_store = get_session_store()
        self.store = QdrantStore()
        self.local_directory = get_local_consultant_directory()
        self.llm_factory = get_llm_factory()
        self._kb_seeded = False
        # Cache valid consultant names from seed for validation
        self._valid_consultant_names = self._load_valid_consultant_names()

    def _load_valid_consultant_names(self) -> set[str]:
        """Load all valid consultant names from seed data for validation."""
        self.local_directory._load_if_needed()
        names = set()
        for row in self.local_directory._rows:
            name = (row.get("name") or "").strip()
            if name:
                names.add(name.lower())
        return names

    def _sanitize_llm_response(self, response: str) -> str:
        """Strip prompt leakage and validate output safety."""
        leakage_markers = [
            "retrieved context:", "system prompt:", "known session profile:",
            "conversation history:", "company support context:",
        ]
        lower = response.lower()
        for marker in leakage_markers:
            if marker in lower:
                _logger.warning("output_leakage_detected marker=%s", marker)
                # Strip everything from the marker onwards
                idx = lower.find(marker)
                response = response[:idx].strip()
        if len(response) > 4000:
            response = response[:4000].rstrip() + "..."
        return response

    async def _rewrite_query(self, query: str, history: list[dict]) -> str:
        """Rewrite the user query into a standalone search query using recent history."""
        if not history or len(history) < 2:
            return query
        recent = history[-4:]
        history_text = "\n".join(f"{m.get('role','user')}: {m.get('content','')}" for m in recent)
        rewrite_prompt = (
            f"Conversation so far:\n{history_text}\n\n"
            f"User's latest message: {query}\n\n"
            "Rewrite the latest message as a standalone, self-contained search query "
            "that makes sense without the conversation context. "
            "Reply with only the rewritten query, nothing else."
        )
        try:
            selection = await self.llm_factory.get_healthy_llm_with_metadata()
            rewritten = await selection.client.agenerate(
                system_prompt="You are a search query rewriter. Output only the rewritten query.",
                user_prompt=rewrite_prompt,
                temperature=0.0,
                max_tokens=80,
            )
            rewritten = rewritten.strip()
            return rewritten if rewritten else query
        except Exception:
            return query

    @staticmethod
    def _format_sources(docs: list) -> list[dict]:
        sources: list[dict] = []
        for doc in docs:
            content = (doc.page_content or "").strip()
            snippet = content[:420]
            if len(content) > 420:
                snippet += "..."
            sources.append(
                {
                    "content": snippet,
                    "metadata": doc.metadata or {},
                }
            )
        return sources

    @staticmethod
    def _build_context(docs: list) -> str:
        if not docs:
            return ""

        chunks: list[str] = []
        for idx, doc in enumerate(docs, start=1):
            meta = doc.metadata or {}
            source_type = meta.get("source_type", "")

            if source_type in ("consultant_profile", "consultant_cv", "consultant_data"):
                # Make consultant identity explicit so LLM can reference the name
                name = meta.get("consultant_name") or meta.get("source") or "Unknown"
                role = meta.get("role") or meta.get("domain") or "Consultant"
                location = meta.get("location") or "India"
                domain = meta.get("domain") or ""
                email = meta.get("email") or ""
                body = doc.page_content.strip()
                entry = (
                    f"Consultant {idx}:\n"
                    f"  Name: {name}\n"
                    f"  Role: {role}\n"
                    f"  Location: {location}\n"
                )
                if domain:
                    entry += f"  Domain: {domain}\n"
                if email:
                    entry += f"  Email: {email}\n"
                entry += f"  Profile: {body}"
                chunks.append(entry)
            else:
                # Website / general content
                source_name = meta.get("title") or meta.get("source") or "website"
                chunks.append(f"Source {idx} [{source_name}]:\n{doc.page_content}")

        return "\n\n".join(chunks)

    @staticmethod
    def _cap_text(text: str, max_chars: int) -> str:
        if max_chars <= 0 or len(text) <= max_chars:
            return text
        return text[:max_chars].rstrip() + "\n\n[context truncated]"

    @staticmethod
    def _normalize_response_text(text: str) -> str:
        if not text:
            return text

        banned_prefixes = (
            "conversation history:",
            "known session profile:",
            "company support context:",
            "retrieved context:",
            "user question:",
            "request summary:",
            "assistant:",
            "user:",
        )
        normalized_lines: list[str] = []
        seen_content: set[str] = set()
        previous_blank = False

        for raw_line in text.replace("\r\n", "\n").split("\n"):
            line = raw_line.rstrip()
            key = line.strip().lower()

            if not key:
                if not previous_blank and normalized_lines:
                    normalized_lines.append("")
                previous_blank = True
                continue

            if any(key.startswith(prefix) for prefix in banned_prefixes):
                continue

            if key in seen_content:
                continue

            normalized_lines.append(line)
            seen_content.add(key)
            previous_blank = False

        return "\n".join(normalized_lines).strip()

    @staticmethod
    def _is_near_duplicate(new_text: str, history: list[dict], threshold: float = 0.80) -> bool:
        """Return True if new_text is very similar to the last assistant message."""
        last_assistant = next(
            (m.get("content", "") for m in reversed(history) if m.get("role") == "assistant"),
            None,
        )
        if not last_assistant or not new_text:
            return False
        # Token-level Jaccard similarity
        a_tokens = set(new_text.lower().split())
        b_tokens = set(last_assistant.lower().split())
        if not a_tokens or not b_tokens:
            return False
        intersection = len(a_tokens & b_tokens)
        union = len(a_tokens | b_tokens)
        return (intersection / union) >= threshold

    @staticmethod
    def _deterministic_fallback_answer(query: str, profile: dict[str, str], reason: str) -> str:
        name = (profile.get("name") or "there").strip() or "there"
        service_hint = profile.get("service_needed") or profile.get("area_of_interest") or "your requirement"
        return (
            f"Thanks, {name}. I can still help map {service_hint} to the right Ofstride consultants. "
            "I am currently using a resilient fallback path while some backend dependencies recover.\n\n"
            "Based on our service lines, we can proceed with one of these domains:\n"
            "1) People & Workforce\n"
            "2) Finance & Compliance\n"
            "3) Technology & Growth\n\n"
            f"Technical note: {reason}."
        )

    @staticmethod
    def _build_actions(values: list[str]) -> list[dict]:
        return [
            {
                "id": f"act_{idx + 1}",
                "label": value,
                "value": value,
                "kind": "quick_reply",
            }
            for idx, value in enumerate(values)
        ]

    async def _search_consultants(self, query: str) -> tuple[list, str | None]:
        docs = []
        retrieval_warning = None
        try:
            await self.store.ensure_collection()
            docs = await self.store.similarity_search(
                query=query,
                k=self.settings.retrieval_k,
                filters={
                    "source_type": {
                        "$in": [
                            "consultant_profile",
                            "consultant_cv",
                            "consultant_data",
                            "website_content",
                            "website_structured",
                        ]
                    }
                },
            )
        except Exception as retrieval_exc:
            retrieval_warning = f"retrieval_unavailable:{str(retrieval_exc)[:120]}"

        if not docs:
            try:
                docs = self.local_directory.search(query=query, k=min(5, self.settings.retrieval_k))
            except Exception as local_exc:
                if retrieval_warning is None:
                    retrieval_warning = f"local_directory_unavailable:{str(local_exc)[:120]}"

        return docs, retrieval_warning

    @staticmethod
    def _build_domain_consultant_response(
        domain: str,
        docs: list,
        profile: dict[str, str],
        missing_required: list[str],
    ) -> str:
        name = (profile.get("name") or "").strip()
        greeting = f"Certainly, {name}." if name else "Certainly."

        # Use specific service type if captured in profile, otherwise use domain
        service_type = profile.get("service_needed") or domain

        if not docs:
            return (
                f"{greeting} Based on your interest in {service_type}, I can help shortlist the right Ofstride consultant.\n\n"
                "Summary:\n"
                f"- Focus area: {service_type}\n"
                "- Consultant options: I am preparing the best-fit shortlist.\n"
                "- Next step: share your exact scope or timeline and I will refine the recommendation politely and precisely."
            )

        lines = [
            f"{greeting} Based on your interest in {service_type}, here is a concise consultant shortlist.",
            "",
            "Recommended consultants:",
        ]

        for index, doc in enumerate(docs[:3], start=1):
            metadata = doc.metadata or {}
            consultant_name = metadata.get("consultant_name") or metadata.get("source") or "Ofstride Consultant"
            role = metadata.get("role") or domain
            location = metadata.get("location") or "India"
            brief_summary = metadata.get("brief_summary") or (doc.page_content or "Profile summary available on request.")
            lines.extend(
                [
                    f"{index}. {consultant_name}",
                    f"   Role: {role}",
                    f"   Location: {location}",
                    f"   Brief profile: {brief_summary}",
                ]
            )

        lines.extend(
            [
                "",
                "Recommended next step:",
                "- Share your exact requirement, timeline, or preferred mode of discussion and I will narrow this to the best fit.",
            ]
        )

        if missing_required:
            lines.append(f"- If convenient, please also share your {missing_required[0]} so I can keep the recommendation aligned for follow-up.")

        return "\n".join(lines)

    async def run(
        self,
        *,
        query: str,
        session_id: str,
        trace_id: str | None = None,
        client_profile: dict[str, str] | None = None,
    ) -> dict:
        if not self._kb_seeded:
            try:
                seed_result = await ensure_codebase_kb_seeded(self.store)
                validation = seed_result.get("validation", {}) if isinstance(seed_result, dict) else {}
                passed = bool(validation.get("passed", False)) if isinstance(validation, dict) else False
                if seed_result.get("seeded") or passed:
                    self._kb_seeded = True
            except Exception as seed_exc:
                _logger.warning("codebase_kb_seed_failed session=%s reason=%s", session_id, str(seed_exc)[:160])

        # Hydrate profile from client to survive cross-instance execution in cloud hosting.
        if client_profile:
            self.session_store.upsert_profile(session_id, client_profile)

        # Get session data first to check current state
        history = self.session_store.get(session_id)
        profile = self.session_store.get_profile(session_id)
        current_state = profile.get("state", STATE_OPEN)

        # Deterministic assessment flow (questionnaire-first) runs before topic guard.
        assessment = await handle_assessment_turn(current_state=current_state, profile=profile, query=query, session_id=session_id)
        if assessment.handled:
            updates = assessment.profile_updates or {}
            if assessment.next_state:
                updates["state"] = assessment.next_state
            if updates:
                profile = self.session_store.upsert_profile(session_id, updates)

            response_text = self._normalize_response_text(assessment.response_text)

            self.session_store.append(session_id, {"role": "user", "content": query})
            self.session_store.append(session_id, {"role": "assistant", "content": response_text})

            missing_required = missing_required_fields(profile)

            return {
                "response": response_text,
                "session_id": session_id,
                "state": profile.get("state", STATE_OPEN),
                "route_decision": "conversational_action",
                "confidence": 0.95,
                "sources": [],
                "provider_used": "state_machine",
                "fallback_reason": None,
                "session_profile": profile,
                "ui_hints": {
                    "actions": assessment.actions or [],
                    "next_required_field": assessment.lead_step,
                    "assessment_focus": assessment.focus_report,
                },
                "debug": {
                    "history_length": len(history) if history else 0,
                    "profile_fields": list(profile.keys()) if profile else [],
                    "missing_required_fields": missing_required,
                },
            }
        
        # 1. TOPIC GUARD CHECK (skip during intake to allow single-word inputs like names)
        if current_state not in [STATE_INTAKE_FIELDS, STATE_INTAKE_SUBMITTED]:
            allowed, reason = self.topic_guard.check(query)
            if not allowed:
                polite_redirect = (
                    "I am focused on Ofstride services, consultant recommendations, and engagement planning. "
                    "If you share your business requirement, preferred domain, or need for a call, I can help concisely."
                )
                response_text = self._normalize_response_text(polite_redirect)
                return {
                    "response": response_text,
                    "session_id": session_id,
                    "state": STATE_OPEN,
                    "route_decision": "blocked",
                    "confidence": 0.0,
                    "sources": [],
                    "provider_used": "none",
                    "fallback_reason": reason or "out_of_scope",
                    "ui_hints": {
                        "actions": self._build_actions(
                            [
                                "People & Workforce services",
                                "Finance & Compliance services",
                                "Technology & Growth services",
                                "Schedule a call",
                            ]
                        ),
                        "next_required_field": None,
                    },
                }
        
        # 2. EXTRACT PROFILE FIELDS
        missing_before = missing_required_fields(profile)
        allow_plain_name_capture = (
            current_state in [STATE_OPEN, STATE_INTAKE_FIELDS, STATE_INTAKE_SUBMITTED]
            and bool(missing_before)
            and missing_before[0] == "name"
        )
        profile_updates = extract_profile_updates(query, allow_plain_name=allow_plain_name_capture)
        profile = self.session_store.upsert_profile(session_id, profile_updates)

        # Fire funnel analytics events for newly-captured required fields (first capture only)
        _event_svc = get_chat_event_service()
        _missing_after = missing_required_fields(profile)
        for _field in missing_before:
            if _field not in _missing_after:
                _evt_type = {"email": "email_captured", "phone": "phone_captured"}.get(_field)
                if _evt_type:
                    try:
                        _event_svc.record_event(
                            event_type=_evt_type,
                            session_id=session_id,
                            payload={"field": _field},
                            trace_id=trace_id,
                        )
                    except Exception as _evt_exc:
                        _logger.debug(
                            "funnel_event_skipped event=%s trace_id=%s reason=%s",
                            _evt_type, trace_id, str(_evt_exc)[:80],
                        )
        
        # 3. DETERMINISTIC INTENT TEMPLATES (bypass LLM for high-frequency / safety-critical queries)
        #    Run AFTER profile extraction so the profile is up to date (e.g. human handoff can use name).
        #    Skip during active intake flow so we don't interrupt slot-filling.
        if current_state not in [STATE_INTAKE_FIELDS]:
            _det_intent = detect_intent(query)
            if _det_intent is not None:
                _det_response = render_intent(_det_intent, profile)
                if _det_response:
                    _det_route = "deterministic_template"
                    _det_actions = self._build_actions(
                        ["Book a free call", "Send a message", "Explore our services"]
                    )
                    if _det_intent == INTENT_HUMAN_HANDOFF:
                        _det_route = "human_handoff"
                        # Fire escalation event so webhook/email can be triggered downstream
                        _logger.info(
                            "human_handoff_triggered session_id=%s name=%s email=%s phone=%s trace_id=%s",
                            session_id,
                            profile.get("name", ""),
                            profile.get("email", ""),
                            profile.get("phone", ""),
                            trace_id,
                        )
                        try:
                            get_chat_event_service().record_event(
                                event_type="human_handoff_triggered",
                                session_id=session_id,
                                payload={
                                    "name": profile.get("name", ""),
                                    "email": profile.get("email", ""),
                                    "phone": profile.get("phone", ""),
                                    "service_needed": profile.get("service_needed", ""),
                                    "area_of_interest": profile.get("area_of_interest", ""),
                                },
                                trace_id=trace_id,
                            )
                        except Exception as _he_exc:
                            _logger.debug("handoff_event_failed trace_id=%s reason=%s", trace_id, str(_he_exc)[:80])
                    return {
                        "response": self._normalize_response_text(_det_response),
                        "session_id": session_id,
                        "state": current_state,
                        "route_decision": _det_route,
                        "confidence": 1.0,
                        "sources": [],
                        "provider_used": "template",
                        "fallback_reason": None,
                        "trace_id": trace_id,
                        "ui_hints": {
                            "actions": _det_actions,
                            "next_required_field": missing_required_fields(profile)[0] if missing_required_fields(profile) else None,
                        },
                        "debug": {
                            "intent": _det_intent,
                        },
                    }

        # 4. USE STATE MACHINE TO DETERMINE NEXT STATE AND RESPONSE
        next_state, response_text, actions = get_next_state(current_state, profile, query)

        # Ensure provider/fallback always have defaults (prevents NameError in non-LLM states)
        provider = None
        fallback_reason: str | None = None
        rewritten_query: str | None = None
        sources: list = []
        trace_chunks: list[dict] = []
        llm_latency_ms = 0.0
        observability_system_prompt = ""
        observability_user_prompt = ""
        route_decision = "conversational"
        
        # Save state
        profile = self.session_store.upsert_profile(session_id, {"state": next_state})
        
        # 5. HANDLE DOMAIN-SELECTED STATE (retrieve consultants)
        if next_state == STATE_DOMAIN_SELECTED:
            # Use domain from current query OR stored domain from profile
            domain = detect_domain_interest(query) or profile.get("service_type")
            if domain:
                search_query = build_domain_search_query(domain)
                docs, retrieval_warning = await self._search_consultants(search_query)
                if not docs:
                    docs, fallback_warning = await self._search_consultants(query)
                    retrieval_warning = retrieval_warning or fallback_warning
                
                missing_required = missing_required_fields(profile)
                response_text = self._normalize_response_text(
                    self._build_domain_consultant_response(domain, docs, profile, missing_required)
                )
                
                # Move to CONSULTANTS_SHOWN after retrieving
                next_state = STATE_CONSULTANTS_SHOWN
                profile = self.session_store.upsert_profile(session_id, {"state": next_state})
                
                sources = self._format_sources(docs)
                trace_chunks = [
                    {"content": d.page_content[:200], "score": d.score, "metadata": d.metadata}
                    for d in docs
                ]
                route_decision = "kb_success" if docs else "kb_no_results"
            else:
                sources = []
                route_decision = "kb_no_results"
        
        # 5. HANDLE CONVERSATION STATE (LLM-based retrieval)
        elif next_state == STATE_CONVERSATION:
            if response_text.strip():
                response_text = self._normalize_response_text(response_text)
                route_decision = "conversational_action"
            else:
            # Rewrite query using recent history for better semantic search
                rewritten_query = await self._rewrite_query(query, history)
                docs, retrieval_warning = await self._search_consultants(rewritten_query)
                route_decision = "kb_success" if docs else "kb_no_results"

                active_assessment_prompt = get_active_assessment_prompt(profile)
                if not docs and active_assessment_prompt is not None:
                    next_question, next_actions = active_assessment_prompt
                    response_text = self._normalize_response_text(
                        "I can only respond from approved Ofstride material. "
                        "Please continue the configured assessment so I can stay grounded.\n\n"
                        f"{next_question}"
                    )
                    actions = next_actions
                    sources = []
                    trace_chunks = []
                    provider = None
                    fallback_reason = retrieval_warning
                    route_decision = "conversational_action"
                else:
                    context = self._build_context(docs)
                    context = self._cap_text(context, self.settings.retrieval_max_context_chars)
                    company_context = get_company_profile_context()
                    short_history = history[-10:]  # wider window: 5 turns instead of 3
                    history_block = "\n".join(
                        [f"{msg.get('role', 'user')}: {msg.get('content', '')}" for msg in short_history]
                    )
                    profile_summary = build_profile_summary(profile)
                    service_context = get_service_catalog().get_services_text()

                    system_prompt = build_system_prompt()
                    user_prompt = build_user_prompt(
                        history_block=history_block,
                        profile_summary=profile_summary,
                        company_context=company_context,
                        context=context,
                        service_context=service_context,
                        query=query,
                    )
                    observability_system_prompt = system_prompt
                    observability_user_prompt = user_prompt

                    llm_start = time.monotonic()
                    provider = None
                    fallback_reason = retrieval_warning

                    try:
                        selection = await self.llm_factory.get_healthy_llm_with_metadata()
                        provider = selection.provider
                        fallback_reason = selection.fallback_reason or retrieval_warning
                    except Exception as provider_exc:
                        fallback_reason = retrieval_warning or f"provider_selection_failed:{str(provider_exc)[:120]}"
                        response_text = self._deterministic_fallback_answer(
                            query=query,
                            profile=profile,
                            reason=fallback_reason,
                        )
                        response_text = self._normalize_response_text(append_cta_options(response_text))
                        sources = []
                        route_decision = "fallback"
                        provider = None
                    else:
                        try:
                            response_text = await selection.client.agenerate(
                                system_prompt=system_prompt,
                                user_prompt=user_prompt,
                                temperature=self.settings.temperature,
                                max_tokens=self.settings.max_tokens,
                            )
                            response_text = self._sanitize_llm_response(response_text)
                            # Cross-turn deduplication: if response is too similar to last answer, ask to clarify
                            domain_in_query = detect_domain_interest(query)
                            has_consulting_intent = has_direct_consulting_intent(query)
                            if (
                                self._is_near_duplicate(response_text, history)
                                and not domain_in_query
                                and not has_consulting_intent
                                and len(query.strip().split()) >= 5
                            ):
                                response_text = (
                                    "I may have already addressed that — could you clarify what specific detail "
                                    "you would like me to expand on? I want to make sure my answer is useful."
                                )
                            self.llm_factory.mark_provider_result(provider, success=True)
                        except Exception as llm_exc:
                            self.llm_factory.mark_provider_result(provider, success=False)
                            fallback_reason = fallback_reason or f"llm_generation_failed:{str(llm_exc)[:120]}"
                            response_text = self._deterministic_fallback_answer(
                                query=query,
                                profile=profile,
                                reason=fallback_reason,
                            )
                            route_decision = "fallback"

                        response_text = self._normalize_response_text(
                            # Only append CTAs if lead profile is still incomplete (avoids CTA repetition)
                            append_cta_options(response_text) if missing_required_fields(profile) else response_text
                        )
                        sources = self._format_sources(docs)
                        trace_chunks = [
                            {"content": d.page_content[:200], "score": d.score, "metadata": d.metadata}
                            for d in docs
                        ]

                    llm_latency_ms = (time.monotonic() - llm_start) * 1000
        
        else:
            # OPEN, INTAKE_FIELDS, INTAKE_SUBMITTED, CONSULTANTS_SHOWN: use state machine response as-is
            pass  # provider/fallback_reason/sources/route_decision already defaulted above

        # Emit Langfuse trace for every completed turn (state-machine and LLM routes).
        try:
            get_tracer().trace_turn(
                conversation_id=session_id,
                trace_id=trace_id or session_id,
                user_message=query,
                rewritten_query=rewritten_query if rewritten_query != query else None,
                retrieved_chunks=trace_chunks,
                model_used=provider.value if provider else "state_machine",
                fallback_triggered=route_decision == "fallback",
                system_prompt=observability_system_prompt,
                user_prompt=observability_user_prompt,
                response=response_text,
                latency_ms=llm_latency_ms,
                input_tokens=None,
                output_tokens=None,
                route_decision=route_decision,
            )
        except Exception as trace_exc:
            _logger.warning(
                "langfuse_emit_failed session=%s trace=%s route=%s reason=%s",
                session_id,
                trace_id or session_id,
                route_decision,
                str(trace_exc)[:180],
            )

        # 6. APPEND TO HISTORY
        self.session_store.append(session_id, {"role": "user", "content": query})
        self.session_store.append(session_id, {"role": "assistant", "content": response_text})

        # 7. BUILD RESPONSE
        missing_required = missing_required_fields(profile)
        confidence = 0.95 if next_state in [STATE_INTAKE_FIELDS, STATE_INTAKE_SUBMITTED] else 0.85

        _logger.info(
            "chat_turn session=%s trace=%s state=%s route=%s docs=%d provider=%s fallback=%s",
            session_id, trace_id, next_state, route_decision,
            len(sources) if sources else 0,
            provider.value if provider else "state_machine",
            fallback_reason or "none",
        )
        get_quality_counters().record(
            route_decision=route_decision,
            doc_count=len(sources) if sources else 0,
        )

        return {
            "response": response_text,
            "session_id": session_id,
            "trace_id": trace_id,
            "state": next_state,
            "route_decision": route_decision,
            "confidence": confidence,
            "sources": sources,
            "provider_used": provider.value if provider else "state_machine",
            "fallback_reason": fallback_reason,
            "session_profile": profile,
            "ui_hints": {
                "actions": actions if actions else self._build_actions(
                    [
                        "People & Workforce",
                        "Finance & Compliance",
                        "Technology & Growth",
                        "Schedule a call",
                    ]
                ),
                "next_required_field": missing_required[0] if missing_required else None,
            },
            "debug": {
                "history_length": len(history) if history else 0,
                "profile_fields": list(profile.keys()) if profile else [],
                "missing_required_fields": missing_required,
            },
        }
