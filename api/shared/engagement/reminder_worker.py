from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error as url_error
from urllib import request as url_request

from core.settings import PROJECT_ROOT, get_settings


class ReminderWorker:
    def __init__(self):
        self._settings = get_settings()

    def _resolve_path(self, raw_path: str) -> Path:
        path = Path(raw_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _queue_path(self) -> Path:
        return self._resolve_path(self._settings.chat_event_queue_file)

    def _state_path(self) -> Path:
        return self._resolve_path(self._settings.chat_reminder_state_file)

    def _load_state(self) -> dict[str, Any]:
        path = self._state_path()
        if not path.exists():
            return {"processed_event_ids": []}

        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
                if isinstance(data, dict) and isinstance(data.get("processed_event_ids"), list):
                    return data
        except (json.JSONDecodeError, OSError):
            pass

        return {"processed_event_ids": []}

    def _save_state(self, state: dict[str, Any]) -> None:
        path = self._state_path()
        with path.open("w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=True, indent=2)

    def _load_events(self) -> list[dict[str, Any]]:
        path = self._queue_path()
        if not path.exists():
            return []

        records: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                row = line.strip()
                if not row:
                    continue
                try:
                    parsed = json.loads(row)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    records.append(parsed)
        return records

    @staticmethod
    def _parse_iso(raw: str | None) -> datetime | None:
        if not raw:
            return None
        try:
            normalized = raw.replace("Z", "+00:00")
            return datetime.fromisoformat(normalized)
        except ValueError:
            return None

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    def _webhook_target(self) -> str | None:
        return (
            self._settings.chat_webhook_url
            or self._settings.contact_webhook_url
            or self._settings.make_webhook_chat_url
        )

    def _send_webhook(self, payload: dict[str, Any]) -> tuple[bool, str | None]:
        target = self._webhook_target()
        if not target:
            return False, "webhook_not_configured"

        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
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

    def _compose_summary_payload(self, event: dict[str, Any]) -> dict[str, Any]:
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}

        recipient_email = str(profile.get("email") or payload.get("email") or "").strip()
        recipient_name = str(profile.get("name") or "there").strip() or "there"
        last_message = str(payload.get("last_message") or payload.get("last_assistant_message") or "").strip()

        summary_lines = [
            f"Hi {recipient_name},",
            "",
            "Thanks for connecting with Ofstride. Here is your conversation summary:",
            f"- Session ID: {event.get('session_id', 'unknown')}",
        ]

        if profile.get("service_needed"):
            summary_lines.append(f"- Service Interest: {profile.get('service_needed')}")
        if profile.get("area_of_interest"):
            summary_lines.append(f"- Domain: {profile.get('area_of_interest')}")
        if profile.get("timeline"):
            summary_lines.append(f"- Timeline: {profile.get('timeline')}")
        if last_message:
            summary_lines.append(f"- Last Discussion: {last_message[:320]}")

        summary_lines.extend(
            [
                "",
                "If you would like, we can schedule a short discovery call with a relevant consultant.",
                "",
                "Regards,",
                "Ofstride Consultant Desk",
            ]
        )

        return {
            "type": "chat_summary_reminder",
            "source": "ofstride-website",
            "session_id": event.get("session_id"),
            "event_id": event.get("event_id"),
            "trace_id": event.get("trace_id"),
            "recipient": {
                "name": recipient_name,
                "email": recipient_email,
                "phone": str(profile.get("phone") or ""),
            },
            "subject": f"Ofstride summary for session {event.get('session_id', 'unknown')}",
            "message": "\n".join(summary_lines),
            "profile": profile,
        }

    def _is_due_exit_event(self, event: dict[str, Any]) -> bool:
        if event.get("event_type") != "session_exit":
            return False

        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        due_at = self._parse_iso(str(payload.get("reminder_due_at") or ""))
        if due_at is None:
            return False

        return due_at <= self._now()

    def process_due_reminders(self, *, limit: int | None = None) -> dict[str, Any]:
        records = self._load_events()
        state = self._load_state()
        processed_ids = set(str(value) for value in state.get("processed_event_ids", []))

        max_batch = max(1, int(limit or self._settings.chat_reminder_batch_size))
        due_items = [
            record
            for record in records
            if self._is_due_exit_event(record)
            and str(record.get("event_id") or "")
            and str(record.get("event_id")) not in processed_ids
        ][:max_batch]

        sent = 0
        failed = 0
        failures: list[dict[str, Any]] = []

        for item in due_items:
            summary_payload = self._compose_summary_payload(item)
            ok, webhook_error = self._send_webhook(summary_payload)
            if ok:
                sent += 1
                processed_ids.add(str(item.get("event_id")))
            else:
                failed += 1
                failures.append(
                    {
                        "event_id": item.get("event_id"),
                        "error": webhook_error or "webhook_failed",
                    }
                )

        state["processed_event_ids"] = sorted(processed_ids)
        state["updated_at"] = self._now().isoformat()
        self._save_state(state)

        return {
            "queue_total": len(records),
            "due_count": len(due_items),
            "processed_count": sent,
            "failed_count": failed,
            "failures": failures,
        }


_worker = ReminderWorker()


def get_reminder_worker() -> ReminderWorker:
    return _worker
