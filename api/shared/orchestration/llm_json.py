from __future__ import annotations

import json
import logging
import re

from core.llm_factory import get_llm_factory
from prompts.assessment_focus import (
    build_focus_system_prompt,
    build_focus_user_prompt,
)

_logger = logging.getLogger("ofstride.llm_json")

_FOCUS_TEMPERATURE = 0.4
_FOCUS_MAX_TOKENS = 600


def _extract_first_json(raw: str) -> dict | None:
    """Best-effort extraction of the first JSON object from an LLM response.

    Tolerates markdown fences and stray prose around the object.
    """
    if not raw:
        return None
    text = raw.strip()
    # Strip ```json ... ``` fences if present.
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    candidate = text[start : end + 1]
    try:
        parsed = json.loads(candidate)
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _is_valid_focus(data: dict | None) -> bool:
    if not isinstance(data, dict):
        return False
    if not isinstance(data.get("focus_title"), str) or not data["focus_title"].strip():
        return False
    if not isinstance(data.get("validation_summary"), str) or not data["validation_summary"].strip():
        return False
    items = data.get("recommended_agenda_items")
    if not isinstance(items, list) or len(items) < 1:
        return False
    if not all(isinstance(item, str) and item.strip() for item in items):
        return False
    return True


def _deterministic_focus(primary_challenge: str, sub_challenge: str) -> dict:
    """Schema-compliant fallback used when the LLM is unavailable or returns bad JSON.

    Deliberately avoids any invented statistics or percentages.
    """
    primary = (primary_challenge or "your selected business challenge").strip()
    sub = (sub_challenge or "your selected sub-hurdle").strip()
    return {
        "focus_title": f"Strategic Agenda: {primary}",
        "validation_summary": (
            f"Your focus on {sub} reflects a common bottleneck where day-to-day "
            f"constraints outpace the current operating model. The root organisational "
            f"bottleneck is usually the absence of a single accountable process owner "
            f"across {primary}."
        ),
        "recommended_agenda_items": [
            (
                f"Strategic discovery: align leadership on the macro implications of "
                f"{primary} and agree one measurable objective."
            ),
            (
                f"Tactical discovery: remove the immediate constraints driving {sub} "
                f"with a short, sequenced 30-day action plan."
            ),
        ],
    }


async def generate_assessment_focus(
    *,
    primary_challenge: str,
    sub_challenge: str,
) -> dict:
    """Run the Section-4 asynchronous OpenAI JSON-mode completion loop.

    Returns a dict matching the exact assessment contract schema:
    { focus_title, validation_summary, recommended_agenda_items[>=1] }.
    Never raises; falls back to a deterministic, schema-valid structure.
    """
    system_prompt = build_focus_system_prompt()
    user_prompt = build_focus_user_prompt(
        primary_challenge=primary_challenge,
        sub_challenge=sub_challenge,
    )

    try:
        factory = get_llm_factory()
        selection = await factory.get_healthy_llm_with_metadata()
        client = selection.client
        raw = ""
        if hasattr(client, "agenerate_json"):
            raw = await client.agenerate_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=_FOCUS_TEMPERATURE,
                max_tokens=_FOCUS_MAX_TOKENS,
            )
        else:
            raw = await client.agenerate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=_FOCUS_TEMPERATURE,
                max_tokens=_FOCUS_MAX_TOKENS,
            )

        parsed = _extract_first_json(raw)
        if _is_valid_focus(parsed):
            parsed["_source"] = selection.provider.value  # type: ignore[assignment]
            return parsed

        _logger.warning(
            "assessment_focus_invalid_json provider=%s raw_len=%d",
            selection.provider.value,
            len(raw or ""),
        )
    except Exception as exc:  # pragma: no cover - must never break the chat flow
        _logger.warning("assessment_focus_llm_failed reason=%s", str(exc)[:160])

    return _deterministic_focus(primary_challenge, sub_challenge)
