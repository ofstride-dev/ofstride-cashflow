from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib import error as url_error
from urllib import request as url_request

from core.settings import PROJECT_ROOT, get_settings
from persistence.sqlite_store import get_durable_store


ALLOWED_EVENT_TYPES = {
    "chat_opened",
    "intent_selected",
    "lead_form_submitted",
    "consultant_viewed",
    "booking_initiated",
    "response_generated",
    "session_exit",
    "off_topic_query",
    "cta_selected",
    "email_captured",
    "phone_captured",
    "human_handoff_triggered",
}


@dataclass
class ChatEvent:
    event_type: str
    session_id: str
    trace_id: str
    payload: dict[str, Any]
    occurred_at: str


class ChatEventService:
    def __init__(self):
        self._settings = get_settings()
        self._durable = get_durable_store()

    def _resolve_queue_path(self) -> Path:
        queue_path = Path(self._settings.chat_event_queue_file)
        if not queue_path.is_absolute():
            queue_path = PROJECT_ROOT / queue_path
        queue_path.parent.mkdir(parents=True, exist_ok=True)
        return queue_path

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _normalize_payload(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload or {})
        if event_type == "session_exit":
            delay = max(1, int(self._settings.chat_event_reminder_delay_minutes))
            reminder_at = datetime.now(timezone.utc) + timedelta(minutes=delay)
            normalized.setdefault("reminder_due_at", reminder_at.isoformat())
            normalized.setdefault("summary_status", "pending_compose")
        return normalized

    def _append_to_queue(self, record: dict[str, Any]) -> None:
        try:
            path = self._resolve_queue_path()
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=True) + "\n")
        except Exception as exc:
            import logging as _log
            _log.getLogger("ofstride.event_service").warning(
                "Event queue write failed (read-only fs?): %s", exc
            )

    def _webhook_target(self) -> str | None:
        return (
            self._settings.chat_webhook_url
            or self._settings.contact_webhook_url
            or self._settings.make_webhook_chat_url
        )

    def _send_webhook(self, record: dict[str, Any]) -> tuple[bool, str | None]:
        target = self._webhook_target()
        if not target:
            return False, "webhook_not_configured"

        body = json.dumps(record, ensure_ascii=True).encode("utf-8")
        req = url_request.Request(
            target,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with url_request.urlopen(req, timeout=8) as response:
                if 200 <= response.status < 300:
                    return True, None
                return False, f"webhook_http_{response.status}"
        except (url_error.HTTPError, url_error.URLError, TimeoutError) as exc:
            return False, str(exc)

    def record_event(
        self,
        *,
        event_type: str,
        session_id: str,
        payload: dict[str, Any] | None,
        trace_id: str,
    ) -> dict[str, Any]:
        if not self._settings.chat_events_enabled:
            return {
                "accepted": False,
                "reason": "chat_events_disabled",
            }

        if event_type not in ALLOWED_EVENT_TYPES:
            raise ValueError("Unsupported event_type")

        event = ChatEvent(
            event_type=event_type,
            session_id=session_id,
            trace_id=trace_id,
            payload=self._normalize_payload(event_type, payload or {}),
            occurred_at=self._now_iso(),
        )

        record = {
            "event_id": f"evt_{uuid.uuid4().hex}",
            "event_type": event.event_type,
            "session_id": event.session_id,
            "trace_id": event.trace_id,
            "occurred_at": event.occurred_at,
            "payload": event.payload,
            "delivery": {
                "queued": True,
                "webhook_dispatched": False,
                "webhook_error": None,
            },
        }

        self._append_to_queue(record)
        if self._settings.durable_store_enabled:
            self._durable.append_event(record)

        dispatched, webhook_error = self._send_webhook(record)
        record["delivery"]["webhook_dispatched"] = dispatched
        record["delivery"]["webhook_error"] = webhook_error

        return {
            "accepted": True,
            "event_id": record["event_id"],
            "queued": record["delivery"]["queued"],
            "webhook_dispatched": record["delivery"]["webhook_dispatched"],
            "webhook_error": record["delivery"]["webhook_error"],
            "occurred_at": record["occurred_at"],
        }


_event_service = ChatEventService()


def get_chat_event_service() -> ChatEventService:
    return _event_service
