"""Persistence for the Resume Builder (master resumes + tailored versions).

Isolated from ``careers_store`` to keep separation of concerns, but mirrors the
existing store pattern: a Supabase-first store with an SQLite fallback, exposed
through a single ``get_resume_builder_store()`` selector.

Tables:
  - resume_drafts   : master resume records (id, created_by, title, resume_data JSON, source info)
  - resume_versions : tailored versions per draft (jd, keywords, tailored resume, ATS score, audit)

Supabase equivalents (``careers_resume_drafts`` / ``careers_resume_versions``)
use JSONB columns — see ``security/resume_builder_schema.sql``.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.settings import PROJECT_ROOT, get_settings

_logger = logging.getLogger("ofstride.resume_builder_store")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ResumeBuilderSQLiteStore:
    """Local SQLite fallback store for resume builder data."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._lock = threading.Lock()
        self._available = False
        self._db_path = self._resolve_db_path()
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._init_db()
            self._available = True
        except Exception as exc:
            _logger.warning("Resume builder SQLite store unavailable: %s", exc)

    def _resolve_db_path(self) -> Path:
        raw = Path(self._settings.durable_careers_sqlite_path)
        # Co-locate with the careers SQLite db so it shares the same writable volume.
        stem = raw.stem
        return raw.with_name(f"{stem}_resume_builder.db")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS resume_drafts (
                    id TEXT PRIMARY KEY,
                    created_by TEXT,
                    title TEXT NOT NULL,
                    resume_data TEXT NOT NULL,
                    source_filename TEXT,
                    source_blob_path TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS resume_versions (
                    id TEXT PRIMARY KEY,
                    draft_id TEXT NOT NULL,
                    version_number INTEGER NOT NULL,
                    jd_text TEXT,
                    jd_keywords TEXT,
                    tailored_resume TEXT NOT NULL,
                    ats_score TEXT,
                    applied_changes TEXT,
                    skipped_changes TEXT,
                    strategy_notes TEXT,
                    ai_used INTEGER DEFAULT 0,
                    ai_provider TEXT,
                    ai_error TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (draft_id) REFERENCES resume_drafts(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_resume_versions_draft ON resume_versions(draft_id)"
            )

    @property
    def is_available(self) -> bool:
        return self._available

    # ── Master resumes ───────────────────────────────────────────────────

    def save_master_resume(
        self,
        *,
        created_by: str | None,
        title: str,
        resume_data: dict[str, Any],
        source_filename: str | None = None,
        source_blob_path: str | None = None,
        draft_id: str | None = None,
    ) -> dict[str, Any]:
        if not self._available:
            raise RuntimeError("Resume builder store unavailable.")
        draft_id = draft_id or str(uuid.uuid4())
        now = _now_iso()
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO resume_drafts (id, created_by, title, resume_data,
                        source_filename, source_blob_path, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (draft_id, created_by, title, json.dumps(resume_data),
                     source_filename, source_blob_path, now, now),
                )
        return self.get_master_resume(draft_id) or {"id": draft_id, "title": title}

    def list_master_resumes(self, created_by: str | None = None) -> list[dict[str, Any]]:
        if not self._available:
            return []
        with self._lock:
            with self._connect() as conn:
                if created_by:
                    rows = conn.execute(
                        "SELECT id, created_by, title, source_filename, source_blob_path, "
                        "created_at, updated_at FROM resume_drafts WHERE created_by = ? ORDER BY updated_at DESC",
                        (created_by,),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT id, created_by, title, source_filename, source_blob_path, "
                        "created_at, updated_at FROM resume_drafts ORDER BY updated_at DESC"
                    ).fetchall()
                return [dict(r) for r in rows]

    def get_master_resume(self, draft_id: str) -> dict[str, Any] | None:
        if not self._available:
            return None
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM resume_drafts WHERE id = ?", (draft_id,)
                ).fetchone()
                if not row:
                    return None
                data = dict(row)
                data["resume_data"] = json.loads(data.get("resume_data") or "{}")
                return data

    def delete_master_resume(self, draft_id: str) -> bool:
        if not self._available:
            return False
        with self._lock:
            with self._connect() as conn:
                cur = conn.execute("DELETE FROM resume_drafts WHERE id = ?", (draft_id,))
                return int(cur.rowcount or 0) > 0

    # ── Tailored versions ───────────────────────────────────────────────

    def save_tailored_version(
        self,
        *,
        draft_id: str,
        jd_text: str,
        jd_keywords: dict[str, Any],
        tailored_resume: dict[str, Any],
        ats_score: dict[str, Any],
        applied_changes: list[dict[str, Any]] | None = None,
        skipped_changes: list[dict[str, Any]] | None = None,
        strategy_notes: str = "",
        ai_used: bool = False,
        ai_provider: str | None = None,
        ai_error: str | None = None,
    ) -> dict[str, Any]:
        if not self._available:
            raise RuntimeError("Resume builder store unavailable.")
        version_id = str(uuid.uuid4())
        now = _now_iso()
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT COALESCE(MAX(version_number), 0) AS m FROM resume_versions WHERE draft_id = ?",
                    (draft_id,),
                ).fetchone()
                next_num = int(row["m"] or 0) + 1
                conn.execute(
                    """
                    INSERT INTO resume_versions (id, draft_id, version_number, jd_text, jd_keywords,
                        tailored_resume, ats_score, applied_changes, skipped_changes, strategy_notes,
                        ai_used, ai_provider, ai_error, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (version_id, draft_id, next_num, jd_text, json.dumps(jd_keywords),
                     json.dumps(tailored_resume), json.dumps(ats_score),
                     json.dumps(applied_changes or []), json.dumps(skipped_changes or []),
                     strategy_notes, 1 if ai_used else 0, ai_provider, ai_error, now),
                )
                conn.execute(
                    "UPDATE resume_drafts SET updated_at = ? WHERE id = ?", (now, draft_id)
                )
        return self.get_version(draft_id, version_id) or {"id": version_id, "version_number": next_num}

    def list_versions(self, draft_id: str) -> list[dict[str, Any]]:
        if not self._available:
            return []
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT id, draft_id, version_number, ai_used, ai_provider, "
                    "json_extract(ats_score, '$.overall_score') AS overall_score, created_at "
                    "FROM resume_versions WHERE draft_id = ? ORDER BY version_number DESC",
                    (draft_id,),
                ).fetchall()
                return [dict(r) for r in rows]

    def get_version(self, draft_id: str, version_id: str) -> dict[str, Any] | None:
        if not self._available:
            return None
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM resume_versions WHERE id = ? AND draft_id = ?",
                    (version_id, draft_id),
                ).fetchone()
                if not row:
                    return None
                data = dict(row)
                for key in ("jd_keywords", "tailored_resume", "ats_score", "applied_changes", "skipped_changes"):
                    if data.get(key):
                        try:
                            data[key] = json.loads(data[key])
                        except Exception:
                            data[key] = {} if key in ("jd_keywords", "ats_score") else []
                data["ai_used"] = bool(data.get("ai_used"))
                return data


class ResumeBuilderSupabaseStore:
    """Supabase-backed resume builder store (PostgREST, JSONB columns)."""

    def __init__(self) -> None:
        self._url = (os.getenv("SUPABASE_URL") or "").rstrip("/")
        self._service_key = (os.getenv("SUPABASE_SERVICE_KEY") or "").strip()
        self._available = bool(self._url and self._service_key)
        if self._available:
            try:
                # Schema probe: if resume-builder tables are not provisioned yet,
                # treat Supabase store as unavailable and let caller fall back.
                self._request(
                    "GET",
                    "careers_resume_drafts",
                    params={"select": "id", "limit": "1"},
                )
            except Exception as exc:
                _logger.warning(
                    "Supabase resume builder schema unavailable; falling back to SQLite: %s",
                    exc,
                )
                self._available = False

    @property
    def is_available(self) -> bool:
        return self._available

    def _headers(self, *, prefer: str | None = None) -> dict[str, str]:
        headers = {"apikey": self._service_key, "Authorization": f"Bearer {self._service_key}",
                   "Content-Type": "application/json"}
        if prefer:
            headers["Prefer"] = prefer
        return headers

    def _request(self, method: str, path: str, *, body=None, params=None, prefer=None):
        import urllib.parse as up
        import urllib.request as ur
        url = f"{self._url}/rest/v1/{path}"
        if params:
            url = f"{url}?{up.urlencode(params)}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = ur.Request(url, data=data, headers=self._headers(prefer=prefer), method=method)
        with ur.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else None

    def save_master_resume(self, *, created_by, title, resume_data, source_filename=None,
                           source_blob_path=None, draft_id=None):
        draft_id = draft_id or str(uuid.uuid4())
        now = _now_iso()
        body = {"id": draft_id, "created_by": created_by, "title": title, "resume_data": resume_data,
                "source_filename": source_filename, "source_blob_path": source_blob_path,
                "created_at": now, "updated_at": now}
        rows = self._request("POST", "careers_resume_drafts", body=body, prefer="return=representation")
        return rows[0] if isinstance(rows, list) and rows else body

    def list_master_resumes(self, created_by=None):
        params = {"select": "id,created_by,title,source_filename,source_blob_path,created_at,updated_at",
                  "order": "updated_at.desc"}
        if created_by:
            params["created_by"] = f"eq.{created_by}"
        rows = self._request("GET", "careers_resume_drafts", params=params) or []
        return rows if isinstance(rows, list) else []

    def get_master_resume(self, draft_id):
        rows = self._request("GET", "careers_resume_drafts",
                            params={"id": f"eq.{draft_id}", "select": "*"}) or []
        return rows[0] if isinstance(rows, list) and rows else None

    def delete_master_resume(self, draft_id):
        try:
            self._request("DELETE", "careers_resume_drafts", params={"id": f"eq.{draft_id}"})
            return True
        except Exception:
            return False

    def save_tailored_version(self, *, draft_id, jd_text, jd_keywords, tailored_resume, ats_score,
                              applied_changes=None, skipped_changes=None, strategy_notes="",
                              ai_used=False, ai_provider=None, ai_error=None):
        version_id = str(uuid.uuid4())
        now = _now_iso()
        rows = self._request("GET", "careers_resume_versions",
                            params={"draft_id": f"eq.{draft_id}", "select": "version_number",
                                    "order": "version_number.desc"})
        next_num = 1
        if isinstance(rows, list) and rows and rows[0].get("version_number") is not None:
            next_num = int(rows[0]["version_number"]) + 1
        body = {"id": version_id, "draft_id": draft_id, "version_number": next_num, "jd_text": jd_text,
                "jd_keywords": jd_keywords, "tailored_resume": tailored_resume, "ats_score": ats_score,
                "applied_changes": applied_changes or [], "skipped_changes": skipped_changes or [],
                "strategy_notes": strategy_notes, "ai_used": bool(ai_used), "ai_provider": ai_provider,
                "ai_error": ai_error, "created_at": now}
        out = self._request("POST", "careers_resume_versions", body=body, prefer="return=representation")
        try:
            self._request("PATCH", "careers_resume_drafts", body={"updated_at": now}, params={"id": f"eq.{draft_id}"})
        except Exception:
            pass
        return out[0] if isinstance(out, list) and out else body

    def list_versions(self, draft_id):
        params = {"draft_id": f"eq.{draft_id}",
                  "select": "id,draft_id,version_number,ai_used,ai_provider,ats_score,created_at",
                  "order": "version_number.desc"}
        rows = self._request("GET", "careers_resume_versions", params=params) or []
        return rows if isinstance(rows, list) else []

    def get_version(self, draft_id, version_id):
        rows = self._request("GET", "careers_resume_versions",
                            params={"id": f"eq.{version_id}", "draft_id": f"eq.{draft_id}", "select": "*"}) or []
        if isinstance(rows, list) and rows:
            data = rows[0]
            data["ai_used"] = bool(data.get("ai_used"))
            return data
        return None


_sqlite_store = ResumeBuilderSQLiteStore()
_active_store = None
_supabase_unconfigured = False


def get_resume_builder_store():
    """Return the best available resume builder store (Supabase-first, SQLite fallback)."""
    global _active_store, _supabase_unconfigured
    if _active_store is not None:
        return _active_store
    if _supabase_unconfigured:
        return _sqlite_store
    try:
        sup = ResumeBuilderSupabaseStore()
        if sup.is_available:
            _active_store = sup
            _logger.info("Using Supabase resume builder store.")
            return _active_store
        _supabase_unconfigured = True
        _logger.info("Supabase not configured for resume builder — using SQLite store.")
        return _sqlite_store
    except Exception as exc:
        _logger.warning("Supabase resume builder store init failed (will retry): %s", exc)
    return _sqlite_store


def get_resume_builder_store_for_draft(draft_id: str):
    """Resolve (store, draft) by checking active store then alternate store.

    This smooths local transitions where older drafts may exist in SQLite while
    Supabase just became available (or vice versa).
    """
    primary = get_resume_builder_store()

    # 1) Try the currently selected store first.
    try:
        if primary.is_available:
            draft = primary.get_master_resume(draft_id)
            if draft:
                return primary, draft
    except Exception as exc:
        _logger.warning("Primary resume builder store lookup failed (%s): %s", draft_id, exc)

    # 2) Probe the alternate store.
    alternates = []
    if isinstance(primary, ResumeBuilderSQLiteStore):
        try:
            sup = ResumeBuilderSupabaseStore()
            if sup.is_available:
                alternates.append(sup)
        except Exception as exc:
            _logger.warning("Alternate Supabase resume builder store init failed: %s", exc)
    else:
        if _sqlite_store.is_available:
            alternates.append(_sqlite_store)

    for alt in alternates:
        try:
            draft = alt.get_master_resume(draft_id)
            if draft:
                _logger.info(
                    "Resolved draft %s from alternate store %s",
                    draft_id,
                    type(alt).__name__,
                )
                return alt, draft
        except Exception as exc:
            _logger.warning("Alternate resume builder store lookup failed (%s): %s", draft_id, exc)

    return primary, None




