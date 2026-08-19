from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from core.settings import PROJECT_ROOT, get_settings


import logging as _logging
_store_logger = _logging.getLogger("ofstride.sqlite_store")


class DurableSQLiteStore:
    def __init__(self):
        self._settings = get_settings()
        self._lock = threading.Lock()
        self._available = False
        self._db_path = self._resolve_db_path()
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._init_db()
            self._available = True
        except Exception as exc:
            _store_logger.warning("SQLite store unavailable (read-only fs?): %s", exc)

    def _resolve_db_path(self) -> Path:
        raw = Path(self._settings.durable_sqlite_path)
        if raw.is_absolute():
            return raw
        return PROJECT_ROOT / raw

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS session_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS session_profiles (
                    session_id TEXT PRIMARY KEY,
                    profile_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    delivery_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS leads (
                    lead_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    lead_type TEXT NOT NULL,
                    name TEXT,
                    email TEXT,
                    phone TEXT,
                    consultant_name TEXT,
                    domain TEXT,
                    business_requirement TEXT,
                    status TEXT DEFAULT 'new',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    notes TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_session_messages_session_id
                ON session_messages(session_id, id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chat_events_session_id
                ON chat_events(session_id)
                """
            )

    def prune_sessions(self) -> None:
        if not self._available:
            return
        ttl_minutes = max(1, self._settings.session_ttl_minutes)
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=ttl_minutes)).isoformat()
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "DELETE FROM session_messages WHERE session_id IN ("
                    "SELECT session_id FROM session_profiles WHERE updated_at < ?"
                    ")",
                    (cutoff,),
                )
                conn.execute("DELETE FROM session_profiles WHERE updated_at < ?", (cutoff,))
                conn.execute("DELETE FROM leads WHERE status = 'new' AND updated_at < ?", (cutoff,))

    def append_message(self, session_id: str, message: dict[str, Any]) -> None:
        if not self._available:
            return
        role = str(message.get("role", "user"))
        content = str(message.get("content", ""))
        now_iso = self._now_iso()

        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO session_messages(session_id, role, content, created_at) VALUES(?,?,?,?)",
                    (session_id, role, content, now_iso),
                )
                max_msgs = max(1, int(self._settings.session_max_messages))
                conn.execute(
                    "DELETE FROM session_messages WHERE id IN ("
                    "SELECT id FROM session_messages WHERE session_id = ? ORDER BY id DESC LIMIT -1 OFFSET ?"
                    ")",
                    (session_id, max_msgs),
                )
                existing = conn.execute(
                    "SELECT profile_json FROM session_profiles WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                profile_json = existing["profile_json"] if existing else "{}"
                conn.execute(
                    "INSERT OR REPLACE INTO session_profiles(session_id, profile_json, updated_at) VALUES(?,?,?)",
                    (session_id, profile_json, now_iso),
                )

    def log_lead(self, session_id: str, lead_type: str, profile: dict[str, str], domain: str | None = None, consultant_name: str | None = None, business_requirement: str | None = None) -> str:
        """Log a lead intent (meeting_request, callback_request, message_consultant, recommendation)."""
        if not self._available:
            return ""
        import uuid
        lead_id = f"lead_{uuid.uuid4().hex[:12]}"
        now_iso = self._now_iso()

        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO leads(
                        lead_id, session_id, lead_type, name, email, phone,
                        consultant_name, domain, business_requirement, status,
                        created_at, updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        lead_id, session_id, lead_type,
                        profile.get("name"), profile.get("email"), profile.get("phone"),
                        consultant_name, domain, business_requirement,
                        "new", now_iso, now_iso,
                    ),
                )
        return lead_id

    def get_messages(self, session_id: str) -> list[dict[str, str]]:
        if not self._available:
            return []
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT role, content FROM session_messages WHERE session_id = ? ORDER BY id ASC",
                    (session_id,),
                ).fetchall()
        return [{"role": row["role"], "content": row["content"]} for row in rows]

    def get_profile(self, session_id: str) -> dict[str, str]:
        if not self._available:
            return {}
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT profile_json FROM session_profiles WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
        if not row:
            return {}
        try:
            data = json.loads(row["profile_json"])
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}

    def upsert_profile(self, session_id: str, updates: dict[str, str]) -> dict[str, str]:
        if not self._available:
            return dict(updates)
        now_iso = self._now_iso()
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT profile_json FROM session_profiles WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                profile = {}
                if row:
                    try:
                        parsed = json.loads(row["profile_json"])
                        if isinstance(parsed, dict):
                            profile = parsed
                    except json.JSONDecodeError:
                        profile = {}

                for key, value in updates.items():
                    normalized = str(value or "").strip()
                    if normalized:
                        profile[key] = normalized

                conn.execute(
                    "INSERT OR REPLACE INTO session_profiles(session_id, profile_json, updated_at) VALUES(?,?,?)",
                    (session_id, json.dumps(profile, ensure_ascii=True), now_iso),
                )
        return profile

    def save_messages(self, session_id: str, messages: list[dict[str, Any]]) -> None:
        trimmed = messages[-max(1, self._settings.session_max_messages) :]
        now_iso = self._now_iso()
        profile = self.get_profile(session_id)

        with self._lock:
            with self._connect() as conn:
                conn.execute("DELETE FROM session_messages WHERE session_id = ?", (session_id,))
                for item in trimmed:
                    conn.execute(
                        "INSERT INTO session_messages(session_id, role, content, created_at) VALUES(?,?,?,?)",
                        (
                            session_id,
                            str(item.get("role", "user")),
                            str(item.get("content", "")),
                            now_iso,
                        ),
                    )
                conn.execute(
                    "INSERT OR REPLACE INTO session_profiles(session_id, profile_json, updated_at) VALUES(?,?,?)",
                    (session_id, json.dumps(profile, ensure_ascii=True), now_iso),
                )

    def append_event(self, record: dict[str, Any]) -> None:
        if not self._available:
            return
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO chat_events(
                        event_id,
                        event_type,
                        session_id,
                        trace_id,
                        occurred_at,
                        payload_json,
                        delivery_json
                    ) VALUES(?,?,?,?,?,?,?)
                    """,
                    (
                        str(record.get("event_id", "")),
                        str(record.get("event_type", "")),
                        str(record.get("session_id", "")),
                        str(record.get("trace_id", "")),
                        str(record.get("occurred_at", "")),
                        json.dumps(record.get("payload") or {}, ensure_ascii=True),
                        json.dumps(record.get("delivery") or {}, ensure_ascii=True),
                    ),
                )


_store = DurableSQLiteStore()


def get_durable_store() -> DurableSQLiteStore:
    return _store
