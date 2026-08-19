from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from core.settings import get_settings
from persistence.sqlite_store import get_durable_store


@dataclass
class SessionRecord:
    messages: list[dict] = field(default_factory=list)
    profile: dict[str, str] = field(default_factory=dict)
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class SessionStore:
    def __init__(self):
        self._settings = get_settings()
        self._durable = get_durable_store()
        self._use_durable = bool(self._settings.durable_store_enabled)
        self.sessions: dict[str, SessionRecord] = {}

    def _is_expired(self, record: SessionRecord) -> bool:
        ttl = timedelta(minutes=self._settings.session_ttl_minutes)
        return datetime.now(timezone.utc) - record.updated_at > ttl

    def _prune_expired(self) -> None:
        expired_keys = [
            session_id
            for session_id, record in self.sessions.items()
            if self._is_expired(record)
        ]
        for key in expired_keys:
            self.sessions.pop(key, None)

    def get(self, session_id: str) -> list[dict]:
        if self._use_durable:
            self._durable.prune_sessions()
            return self._durable.get_messages(session_id)

        self._prune_expired()
        record = self.sessions.get(session_id)
        if not record:
            return []
        return list(record.messages)

    def append(self, session_id: str, message: dict) -> None:
        if self._use_durable:
            self._durable.prune_sessions()
            self._durable.append_message(session_id, message)
            return

        self._prune_expired()
        record = self.sessions.get(session_id)
        if not record:
            record = SessionRecord()
            self.sessions[session_id] = record

        record.messages.append(message)
        if len(record.messages) > self._settings.session_max_messages:
            record.messages = record.messages[-self._settings.session_max_messages :]
        record.updated_at = datetime.now(timezone.utc)

    def get_profile(self, session_id: str) -> dict[str, str]:
        if self._use_durable:
            self._durable.prune_sessions()
            return self._durable.get_profile(session_id)

        self._prune_expired()
        record = self.sessions.get(session_id)
        if not record:
            return {}
        return dict(record.profile)

    def upsert_profile(self, session_id: str, updates: dict[str, str]) -> dict[str, str]:
        if self._use_durable:
            self._durable.prune_sessions()
            return self._durable.upsert_profile(session_id, updates)

        self._prune_expired()
        record = self.sessions.get(session_id)
        if not record:
            record = SessionRecord()
            self.sessions[session_id] = record

        for key, value in updates.items():
            normalized = str(value or "").strip()
            if normalized:
                record.profile[key] = normalized
        record.updated_at = datetime.now(timezone.utc)
        return dict(record.profile)

    def save(self, session_id: str, messages: list[dict]) -> None:
        if self._use_durable:
            self._durable.prune_sessions()
            self._durable.save_messages(session_id, messages)
            return

        trimmed = messages[-self._settings.session_max_messages :]
        existing_profile = {}
        if session_id in self.sessions:
            existing_profile = dict(self.sessions[session_id].profile)
        self.sessions[session_id] = SessionRecord(
            messages=list(trimmed),
            profile=existing_profile,
            updated_at=datetime.now(timezone.utc),
        )


_session_store = SessionStore()


def get_session_store() -> SessionStore:
    return _session_store
