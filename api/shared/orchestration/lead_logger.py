from __future__ import annotations

import json
import logging
import os
import time

from core.settings import get_settings

_logger = logging.getLogger("ofstride.lead_logger")


def log_lead_capture_step(session_id: str | None, step: str, payload: dict | None = None) -> None:
    """Progressive lead-capture logging stub.

    Records each step of the deterministic lead-collection sequence
    (capture_name -> capture_contact -> complete). This is intentionally a
    lightweight stub: it emits a structured INFO log and appends a JSONL
    record next to the chat event queue file so a downstream CRM/webhook or
    batch exporter can consume it later without code changes here.

    Failures are swallowed so lead logging never breaks the chat experience.
    """
    record = {
        "event": "lead_capture",
        "session_id": session_id or "unknown",
        "step": step,
        "payload": payload or {},
        "occurred_at": time.time(),
    }
    _logger.info("lead_capture session=%s step=%s", record["session_id"], step)

    try:
        settings = get_settings()
        queue_file = getattr(settings, "chat_event_queue_file", None)
        if queue_file:
            log_path = os.path.join(os.path.dirname(str(queue_file)), "lead_capture.jsonl")
        else:
            log_path = os.path.join(os.path.dirname(str(__file__)), "lead_capture.jsonl")
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except Exception as exc:  # pragma: no cover - logging must never fail loud
        _logger.debug("lead_capture_log_write_failed reason=%s", str(exc)[:160])
