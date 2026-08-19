from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from core.settings import PROJECT_ROOT, get_settings

import logging as _logging
_store_logger = _logging.getLogger("ofstride.careers_store")


class CareersSQLiteStore:
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
            _store_logger.warning("Careers SQLite store unavailable (read-only fs?): %s", exc)

    def _resolve_db_path(self) -> Path:
        raw = Path(self._settings.durable_careers_sqlite_path)
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

    @staticmethod
    def _normalize_email(value: str) -> str:
        return (value or "").strip().lower()

    @staticmethod
    def _column_exists(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return any(str(row[1]) == column_name for row in rows)

    def _ensure_column(self, conn: sqlite3.Connection, table_name: str, column_name: str, definition: str) -> None:
        if not self._column_exists(conn, table_name, column_name):
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    department TEXT,
                    location TEXT,
                    employment_type TEXT,
                    jd_markdown TEXT,
                    jd_raw_text TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'draft',
                    ai_assisted_version TEXT,
                    created_by TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS applications (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    full_name TEXT NOT NULL,
                    email TEXT NOT NULL,
                    phone TEXT,
                    linkedin_url TEXT,
                    years_experience REAL,
                    cover_note TEXT,
                    consent_accepted INTEGER NOT NULL DEFAULT 0,
                    resume_blob_path TEXT NOT NULL,
                    resume_original_name TEXT NOT NULL,
                    resume_content_type TEXT NOT NULL,
                    resume_size_bytes INTEGER NOT NULL,
                    submission_status TEXT NOT NULL DEFAULT 'submitted',
                    confirmation_email_sent INTEGER NOT NULL DEFAULT 0,
                    applicant_email_sent_at TEXT,
                    hr_email_sent_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (job_id) REFERENCES jobs(id)
                )
                """
            )

            # Backward-compatible migrations for existing deployments.
            self._ensure_column(conn, "applications", "reference_id", "TEXT")
            self._ensure_column(conn, "applications", "submitted_at", "TEXT")
            self._ensure_column(conn, "applications", "hr_email_sent", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "jobs", "jd_blob_path", "TEXT")
            self._ensure_column(conn, "jobs", "jd_blob_container", "TEXT")
            self._ensure_column(conn, "applications", "applicant_email_sent_at", "TEXT")

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS application_analysis (
                    id TEXT PRIMARY KEY,
                    application_id TEXT NOT NULL,
                    analysis_status TEXT NOT NULL DEFAULT 'pending',
                    match_score REAL,
                    matched_skills_json TEXT,
                    missing_skills_json TEXT,
                    strengths_summary TEXT,
                    gaps_summary TEXT,
                    recommendation TEXT,
                    analyzed_by TEXT,
                    analyzed_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (application_id) REFERENCES applications(id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_action_log (
                    id TEXT PRIMARY KEY,
                    admin_user_id TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    action_detail TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_applications_job_id
                ON applications(job_id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_applications_email_job_created
                ON applications(email, job_id, created_at DESC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_applications_status
                ON applications(submission_status)
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_applications_reference_id_unique
                ON applications(reference_id)
                WHERE reference_id IS NOT NULL
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_application_analysis_application_id
                ON application_analysis(application_id)
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_application_analysis_application_id_unique
                ON application_analysis(application_id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_admin_action_log_entity
                ON admin_action_log(entity_type, entity_id)
                """
            )

    def has_recent_duplicate_application(self, *, job_id: str, email: str, window_days: int = 30) -> bool:
        if not self._available:
            return False

        normalized_email = self._normalize_email(email)
        if not normalized_email or not (job_id or "").strip():
            return False

        cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, int(window_days)))).isoformat()
        statuses = ("submitted", "under_review", "shortlisted", "rejected")
        placeholders = ",".join("?" for _ in statuses)

        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    f"""
                    SELECT 1
                    FROM applications
                    WHERE job_id = ?
                      AND lower(trim(email)) = ?
                      AND submission_status IN ({placeholders})
                      AND created_at >= ?
                    LIMIT 1
                    """,
                    (job_id.strip(), normalized_email, *statuses, cutoff),
                ).fetchone()
        return bool(row)

    def get_active_job(self, *, job_id: str) -> dict[str, Any] | None:
        if not self._available:
            return None
        if not (job_id or "").strip():
            return None

        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT id, title, status
                    FROM jobs
                    WHERE id = ? AND status = 'active'
                    LIMIT 1
                    """,
                    (job_id.strip(),),
                ).fetchone()
        if not row:
            return None
        return {"id": row["id"], "title": row["title"], "status": row["status"]}

    def list_active_jobs(
        self,
        *,
        query: str | None = None,
        department: str | None = None,
        location: str | None = None,
        employment_type: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self._available:
            return []

        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT
                        id,
                        title,
                        department,
                        location,
                        employment_type,
                        jd_markdown,
                        jd_raw_text,
                        jd_blob_path,
                        jd_blob_container,
                        status,
                        updated_at
                    FROM jobs
                    WHERE status = 'active'
                    ORDER BY updated_at DESC
                    """
                ).fetchall()

        jobs = [{k: row[k] for k in row.keys()} for row in rows]
        if not any([query, department, location, employment_type]):
            return jobs

        def norm(value: object) -> str:
            return str(value or "").strip().lower()

        q = norm(query)
        filtered: list[dict[str, Any]] = []
        for job in jobs:
            if q:
                haystack = " ".join(
                    [
                        norm(job.get("title")),
                        norm(job.get("department")),
                        norm(job.get("location")),
                        norm(job.get("employment_type")),
                        norm(job.get("jd_markdown")),
                        norm(job.get("jd_raw_text")),
                    ]
                )
                if q not in haystack:
                    continue
            if department and norm(department) != norm(job.get("department")):
                continue
            if location and norm(location) != norm(job.get("location")):
                continue
            if employment_type and norm(employment_type) != norm(job.get("employment_type")):
                continue
            filtered.append(job)

        return filtered

    def list_jobs(self, *, include_inactive: bool = True) -> list[dict[str, Any]]:
        if not self._available:
            return []

        where_clause = "" if include_inactive else "WHERE status = 'active'"
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    f"""
                    SELECT
                        id,
                        title,
                        department,
                        location,
                        employment_type,
                        jd_markdown,
                        jd_raw_text,
                        jd_blob_path,
                        jd_blob_container,
                        status,
                        created_by,
                        created_at,
                        updated_at
                    FROM jobs
                    {where_clause}
                    ORDER BY updated_at DESC
                    """
                ).fetchall()
        return [{k: row[k] for k in row.keys()} for row in rows]

    def upsert_job(
        self,
        *,
        job_id: str | None,
        title: str,
        department: str | None,
        location: str | None,
        employment_type: str | None,
        jd_markdown: str,
        jd_raw_text: str,
        jd_blob_path: str | None,
        jd_blob_container: str | None,
        status: str,
        created_by: str | None,
    ) -> dict[str, Any] | None:
        if not self._available:
            return None

        now_iso = self._now_iso()
        final_job_id = (job_id or "").strip() or f"job_{uuid.uuid4().hex}"

        with self._lock:
            with self._connect() as conn:
                existing = conn.execute(
                    "SELECT id FROM jobs WHERE id = ? LIMIT 1",
                    (final_job_id,),
                ).fetchone()

                if existing:
                    conn.execute(
                        """
                        UPDATE jobs
                        SET title = ?,
                            department = ?,
                            location = ?,
                            employment_type = ?,
                            jd_markdown = ?,
                            jd_raw_text = ?,
                            jd_blob_path = ?,
                            jd_blob_container = ?,
                            status = ?,
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            title.strip(),
                            (department or "").strip() or None,
                            (location or "").strip() or None,
                            (employment_type or "").strip() or None,
                            jd_markdown,
                            jd_raw_text,
                            (jd_blob_path or "").strip() or None,
                            (jd_blob_container or "").strip() or None,
                            status.strip(),
                            now_iso,
                            final_job_id,
                        ),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO jobs (
                            id,
                            title,
                            department,
                            location,
                            employment_type,
                            jd_markdown,
                            jd_raw_text,
                            jd_blob_path,
                            jd_blob_container,
                            status,
                            ai_assisted_version,
                            created_by,
                            created_at,
                            updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)
                        """,
                        (
                            final_job_id,
                            title.strip(),
                            (department or "").strip() or None,
                            (location or "").strip() or None,
                            (employment_type or "").strip() or None,
                            jd_markdown,
                            jd_raw_text,
                            (jd_blob_path or "").strip() or None,
                            (jd_blob_container or "").strip() or None,
                            status.strip(),
                            (created_by or "").strip() or None,
                            now_iso,
                            now_iso,
                        ),
                    )

        return self.get_job_by_id(job_id=final_job_id)

    def create_application_draft(
        self,
        *,
        application_id: str | None,
        reference_id: str | None,
        job_id: str,
        full_name: str,
        email: str,
        phone: str | None,
        linkedin_url: str | None,
        years_experience: float | None,
        cover_note: str | None,
        consent_accepted: bool,
        resume_blob_path: str,
        resume_original_name: str,
        resume_content_type: str,
        resume_size_bytes: int,
    ) -> dict[str, Any] | None:
        if not self._available:
            return None

        now_iso = self._now_iso()
        final_application_id = (application_id or "").strip() or f"app_{uuid.uuid4().hex}"
        final_reference_id = (reference_id or "").strip() or f"OFS-{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:6].upper()}"
        normalized_email = self._normalize_email(email)

        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO applications (
                        id,
                        reference_id,
                        job_id,
                        full_name,
                        email,
                        phone,
                        linkedin_url,
                        years_experience,
                        cover_note,
                        consent_accepted,
                        resume_blob_path,
                        resume_original_name,
                        resume_content_type,
                        resume_size_bytes,
                        submission_status,
                        created_at,
                        submitted_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        final_application_id,
                        final_reference_id,
                        job_id.strip(),
                        full_name.strip(),
                        normalized_email,
                        (phone or "").strip() or None,
                        (linkedin_url or "").strip() or None,
                        years_experience,
                        (cover_note or "").strip() or None,
                        1 if consent_accepted else 0,
                        resume_blob_path,
                        resume_original_name,
                        resume_content_type,
                        int(resume_size_bytes),
                        "draft_upload_pending",
                        now_iso,
                        None,
                        now_iso,
                    ),
                )

        return {
            "application_id": final_application_id,
            "reference_id": final_reference_id,
            "resume_blob_path": resume_blob_path,
        }

    def get_application_by_id(self, *, application_id: str) -> dict[str, Any] | None:
        if not self._available:
            return None
        if not (application_id or "").strip():
            return None

        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT
                        id,
                        reference_id,
                        job_id,
                        email,
                        resume_blob_path,
                        resume_content_type,
                        resume_size_bytes,
                        submission_status,
                        hr_email_sent,
                        hr_email_sent_at,
                        created_at,
                        submitted_at,
                        updated_at
                    FROM applications
                    WHERE id = ?
                    LIMIT 1
                    """,
                    (application_id.strip(),),
                ).fetchone()

        if not row:
            return None
        return {k: row[k] for k in row.keys()}

    def finalize_submission(self, *, application_id: str) -> dict[str, Any] | None:
        if not self._available:
            return None

        now_iso = self._now_iso()
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT id, reference_id, submission_status
                    FROM applications
                    WHERE id = ?
                    LIMIT 1
                    """,
                    (application_id.strip(),),
                ).fetchone()
                if not row or row["submission_status"] != "draft_upload_pending":
                    return None

                conn.execute(
                    """
                    UPDATE applications
                    SET submission_status = 'submitted',
                        submitted_at = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (now_iso, now_iso, application_id.strip()),
                )
                conn.execute(
                    """
                    INSERT OR IGNORE INTO application_analysis (
                        id,
                        application_id,
                        analysis_status,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, 'not_started', ?, ?)
                    """,
                    (f"ana_{uuid.uuid4().hex}", application_id.strip(), now_iso, now_iso),
                )

        return {
            "application_id": application_id.strip(),
            "reference_id": row["reference_id"],
            "status": "submitted",
        }

    def mark_hr_email_sent(self, *, application_id: str) -> None:
        if not self._available:
            return

        now_iso = self._now_iso()
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE applications
                    SET hr_email_sent = 1,
                        hr_email_sent_at = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (now_iso, now_iso, application_id.strip()),
                )

    def mark_applicant_followup_sent(self, *, application_id: str) -> None:
        if not self._available:
            return

        now_iso = self._now_iso()
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE applications
                    SET applicant_email_sent_at = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (now_iso, now_iso, application_id.strip()),
                )

    def get_job_by_id(self, *, job_id: str) -> dict[str, Any] | None:
        if not self._available:
            return None
        if not (job_id or "").strip():
            return None

        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT id, title, department, location, employment_type, jd_markdown, jd_raw_text, jd_blob_path, jd_blob_container, status
                    FROM jobs
                    WHERE id = ?
                    LIMIT 1
                    """,
                    (job_id.strip(),),
                ).fetchone()
        if not row:
            return None
        return {k: row[k] for k in row.keys()}

    def list_applications(
        self,
        *,
        status: str | None = None,
        job_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        if not self._available:
            return []

        where: list[str] = []
        params: list[Any] = []
        if (status or "").strip():
            where.append("a.submission_status = ?")
            params.append(str(status).strip())
        if (job_id or "").strip():
            where.append("a.job_id = ?")
            params.append(str(job_id).strip())

        where_clause = f"WHERE {' AND '.join(where)}" if where else ""
        query = f"""
            SELECT
                a.id,
                a.reference_id,
                a.job_id,
                j.title AS job_title,
                a.full_name,
                a.email,
                a.resume_original_name,
                a.submission_status,
                a.created_at,
                a.submitted_at,
                an.analysis_status,
                an.match_score
            FROM applications a
            LEFT JOIN jobs j ON j.id = a.job_id
            LEFT JOIN application_analysis an ON an.application_id = a.id
            {where_clause}
            ORDER BY a.created_at DESC
            LIMIT ? OFFSET ?
        """

        params.extend([max(1, int(limit)), max(0, int(offset))])
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(query, tuple(params)).fetchall()
        return [{k: row[k] for k in row.keys()} for row in rows]

    def get_application_detail(self, *, application_id: str) -> dict[str, Any] | None:
        if not self._available:
            return None
        if not (application_id or "").strip():
            return None

        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT
                        a.id,
                        a.reference_id,
                        a.job_id,
                        j.title AS job_title,
                        a.full_name,
                        a.email,
                        a.phone,
                        a.linkedin_url,
                        a.years_experience,
                        a.cover_note,
                        a.resume_blob_path,
                        a.resume_original_name,
                        a.resume_content_type,
                        a.resume_size_bytes,
                        a.submission_status,
                        a.hr_email_sent,
                        a.hr_email_sent_at,
                        a.created_at,
                        a.submitted_at,
                        a.updated_at,
                        an.analysis_status,
                        an.match_score,
                        an.matched_skills_json,
                        an.missing_skills_json,
                        an.strengths_summary,
                        an.gaps_summary,
                        an.recommendation,
                        an.analyzed_by,
                        an.analyzed_at
                    FROM applications a
                    LEFT JOIN jobs j ON j.id = a.job_id
                    LEFT JOIN application_analysis an ON an.application_id = a.id
                    WHERE a.id = ?
                    LIMIT 1
                    """,
                    (application_id.strip(),),
                ).fetchone()

        if not row:
            return None
        return {k: row[k] for k in row.keys()}

    def update_application_status(self, *, application_id: str, status: str) -> bool:
        if not self._available:
            return False
        now_iso = self._now_iso()
        with self._lock:
            with self._connect() as conn:
                cur = conn.execute(
                    """
                    UPDATE applications
                    SET submission_status = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (status.strip(), now_iso, application_id.strip()),
                )
                return cur.rowcount > 0

    def update_analysis_status(
        self,
        *,
        application_id: str,
        analysis_status: str,
        analyzed_by: str | None = None,
        recommendation: str | None = None,
        match_score: float | None = None,
        matched_skills_json: str | None = None,
        missing_skills_json: str | None = None,
        strengths_summary: str | None = None,
        gaps_summary: str | None = None,
    ) -> bool:
        if not self._available:
            return False

        now_iso = self._now_iso()
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO application_analysis (
                        id,
                        application_id,
                        analysis_status,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, 'not_started', ?, ?)
                    """,
                    (f"ana_{uuid.uuid4().hex}", application_id.strip(), now_iso, now_iso),
                )

                cur = conn.execute(
                    """
                    UPDATE application_analysis
                    SET analysis_status = ?,
                        analyzed_by = COALESCE(?, analyzed_by),
                        analyzed_at = ?,
                        recommendation = COALESCE(?, recommendation),
                        match_score = COALESCE(?, match_score),
                        matched_skills_json = COALESCE(?, matched_skills_json),
                        missing_skills_json = COALESCE(?, missing_skills_json),
                        strengths_summary = COALESCE(?, strengths_summary),
                        gaps_summary = COALESCE(?, gaps_summary),
                        updated_at = ?
                    WHERE application_id = ?
                    """,
                    (
                        analysis_status.strip(),
                        (analyzed_by or "").strip() or None,
                        now_iso,
                        (recommendation or "").strip() or None,
                        match_score,
                        (matched_skills_json or "").strip() or None,
                        (missing_skills_json or "").strip() or None,
                        (strengths_summary or "").strip() or None,
                        (gaps_summary or "").strip() or None,
                        now_iso,
                        application_id.strip(),
                    ),
                )
                return cur.rowcount > 0

    def log_admin_action(
        self,
        *,
        admin_user_id: str,
        action_type: str,
        entity_type: str,
        entity_id: str,
        action_detail: str | None = None,
    ) -> None:
        if not self._available:
            return

        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO admin_action_log (
                        id,
                        admin_user_id,
                        action_type,
                        entity_type,
                        entity_id,
                        action_detail,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"act_{uuid.uuid4().hex}",
                        admin_user_id.strip() or "unknown",
                        action_type.strip(),
                        entity_type.strip(),
                        entity_id.strip(),
                        (action_detail or "").strip() or None,
                        self._now_iso(),
                    ),
                )

    def mark_stale_drafts_upload_failed(self, *, older_than_hours: int = 24) -> int:
        if not self._available:
            return 0

        cutoff = (datetime.now(timezone.utc) - timedelta(hours=max(1, int(older_than_hours)))).isoformat()
        now_iso = self._now_iso()
        with self._lock:
            with self._connect() as conn:
                cur = conn.execute(
                    """
                    UPDATE applications
                    SET submission_status = 'upload_failed',
                        updated_at = ?
                    WHERE submission_status = 'draft_upload_pending'
                      AND created_at < ?
                    """,
                    (now_iso, cutoff),
                )
                return int(cur.rowcount or 0)

    @property
    def db_path(self) -> Path:
        return self._db_path

    @property
    def is_available(self) -> bool:
        return self._available


_careers_store = CareersSQLiteStore()

# ── Store selector: prefer Supabase, fall back to SQLite ──────────────
# This allows all existing imports of get_careers_store() to automatically
# use Supabase when configured, without changing any function.py files.

_active_store = None
_supabase_unconfigured = False


def get_careers_store():
    """Return the best available careers store.

    Priority:
      1. Supabase store (if SUPABASE_URL + SUPABASE_SERVICE_KEY are set)
      2. SQLite store (fallback for local dev / unconfigured environments)

    Caching strategy:
      - Supabase working - cached permanently (fast path for all subsequent calls).
      - Supabase env vars missing (local dev) - SQLite cached permanently.
      - Supabase env vars SET but unreachable - SQLite used transiently but
        NOT cached, so the next call retries Supabase. This prevents a cold-start
        Supabase hiccup from permanently crippling an Azure Functions instance.
    """
    global _active_store, _supabase_unconfigured

    # Fast path - Supabase already confirmed working on this process
    if _active_store is not None:
        return _active_store

    # Supabase env vars were already checked and are missing - skip retry
    if _supabase_unconfigured:
        return _careers_store

    # Try Supabase first
    try:
        from persistence.careers_supabase_store import get_careers_supabase_store
        supabase_store = get_careers_supabase_store()
        if supabase_store.is_available:
            _active_store = supabase_store
            _store_logger.info("Using Supabase careers store.")
            return _active_store
        # Supabase env vars are missing/unset - cache SQLite permanently
        _supabase_unconfigured = True
        _store_logger.info(
            "Supabase not configured (SUPABASE_URL / SUPABASE_SERVICE_KEY missing). "
            "Using SQLite careers store."
        )
        return _careers_store
    except Exception as exc:
        _store_logger.warning(
            "Supabase store init failed (will retry on next request): %s", exc
        )

    # Supabase IS configured but unreachable - DON'T cache, retry next call
    _store_logger.info(
        "Using SQLite careers store transiently (Supabase unavailable - will retry "
        "on next request)."
    )
    return _careers_store