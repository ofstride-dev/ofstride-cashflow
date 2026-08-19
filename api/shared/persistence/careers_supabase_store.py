"""Supabase-backed careers store using PostgREST REST API.

This module replaces the deprecated SQLite store (careers_store.py).
It communicates with Supabase PostgreSQL via the PostgREST REST API
using Python's standard library urllib — no additional pip dependencies.

Environment variables required:
    SUPABASE_URL          — e.g. https://your-project.supabase.co
    SUPABASE_SERVICE_KEY  — service-role key (server-side only, bypasses RLS)

All public methods match the interface of CareersSQLiteStore so that
careers_manage/function.py can switch stores with a single import change.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib import error as url_error
from urllib import parse as url_parse
from urllib import request as url_request

_logger = logging.getLogger("ofstride.careers_supabase_store")


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip() or default


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_email(value: str) -> str:
    return (value or "").strip().lower()


class CareersSupabaseStore:
    """Careers store backed by Supabase PostgreSQL via PostgREST REST API."""

    def __init__(self) -> None:
        self._url = (_env("SUPABASE_URL") or "").rstrip("/")
        self._service_key = _env("SUPABASE_SERVICE_KEY") or ""
        self._available = bool(self._url and self._service_key)
        if not self._available:
            _logger.warning(
                "CareersSupabaseStore unavailable: SUPABASE_URL or SUPABASE_SERVICE_KEY not set. "
                "SUPABASE_SERVICE_KEY must be the Supabase service_role key (not SUPABASE_JWT_SECRET). "
                "Get it from Supabase Dashboard > Settings > API > service_role key."
            )

    @property
    def is_available(self) -> bool:
        return self._available

    # ── HTTP helpers ───────────────────────────────────────────────────

    def _headers(self, *, prefer: str | None = None) -> dict[str, str]:
        headers = {
            "apikey": self._service_key,
            "Authorization": f"Bearer {self._service_key}",
            "Content-Type": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict | list | None = None,
        params: dict[str, str] | None = None,
        prefer: str | None = None,
    ) -> list[dict] | dict | None:
        """Execute a PostgREST request and return parsed JSON."""
        url = f"{self._url}/rest/v1/{path}"
        if params:
            query = url_parse.urlencode(params)
            url = f"{url}?{query}"

        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")

        req = url_request.Request(
            url,
            data=data,
            headers=self._headers(prefer=prefer),
            method=method,
        )
        try:
            with url_request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("utf-8")
                if not raw:
                    return None
                return json.loads(raw)
        except url_error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            _logger.error("Supabase HTTP %s %s → %d: %s", method, path, exc.code, err_body[:500])
            raise
        except (url_error.URLError, TimeoutError) as exc:
            _logger.error("Supabase connection error: %s", exc)
            raise

    @staticmethod
    def _job_matches_filters(
        job: dict[str, Any],
        *,
        query: str | None = None,
        department: str | None = None,
        location: str | None = None,
        employment_type: str | None = None,
    ) -> bool:
        def norm(value: object) -> str:
            return str(value or "").strip().lower()

        q = norm(query)
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
                return False

        filters = (
            (department, job.get("department")),
            (location, job.get("location")),
            (employment_type, job.get("employment_type")),
        )
        for expected, actual in filters:
            if norm(expected) and norm(expected) != norm(actual):
                return False
        return True

    # ── Jobs ───────────────────────────────────────────────────────────

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
        params = {
            "select": "id,title,department,location,employment_type,jd_markdown,jd_raw_text,jd_blob_path,jd_blob_container,status,updated_at",
            "status": "eq.active",
            "order": "updated_at.desc",
        }
        result = self._request("GET", "careers_jobs", params=params)
        jobs = result if isinstance(result, list) else []
        if not any([query, department, location, employment_type]):
            return jobs
        return [
            job
            for job in jobs
            if self._job_matches_filters(
                job,
                query=query,
                department=department,
                location=location,
                employment_type=employment_type,
            )
        ]

    def list_jobs(self, *, include_inactive: bool = True) -> list[dict[str, Any]]:
        if not self._available:
            return []
        params = {
            "select": "id,title,department,location,employment_type,jd_markdown,jd_raw_text,jd_blob_path,jd_blob_container,status,created_by,created_at,updated_at",
            "order": "updated_at.desc",
        }
        if not include_inactive:
            params["status"] = "eq.active"
        result = self._request("GET", "careers_jobs", params=params)
        return result if isinstance(result, list) else []

    def get_job_by_id(self, *, job_id: str) -> dict[str, Any] | None:
        if not self._available or not (job_id or "").strip():
            return None
        params = {
            "select": "id,title,department,location,employment_type,jd_markdown,jd_raw_text,jd_blob_path,jd_blob_container,status",
            "id": f"eq.{job_id.strip()}",
            "limit": "1",
        }
        result = self._request("GET", "careers_jobs", params=params)
        if isinstance(result, list) and result:
            return result[0]
        return None

    def get_active_job(self, *, job_id: str) -> dict[str, Any] | None:
        if not self._available or not (job_id or "").strip():
            return None
        params = {
            "select": "id,title,status",
            "id": f"eq.{job_id.strip()}",
            "status": "eq.active",
            "limit": "1",
        }
        result = self._request("GET", "careers_jobs", params=params)
        if isinstance(result, list) and result:
            return result[0]
        return None

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

        final_job_id = (job_id or "").strip() or f"job_{uuid.uuid4().hex}"
        now_iso = _now_iso()

        body = {
            "id": final_job_id,
            "title": title.strip(),
            "department": (department or "").strip() or None,
            "location": (location or "").strip() or None,
            "employment_type": (employment_type or "").strip() or None,
            "jd_markdown": jd_markdown,
            "jd_raw_text": jd_raw_text,
            "jd_blob_path": (jd_blob_path or "").strip() or None,
            "jd_blob_container": (jd_blob_container or "").strip() or None,
            "status": status.strip(),
            "created_by": (created_by or "").strip() or None,
            "created_at": now_iso,
            "updated_at": now_iso,
        }

        # Upsert via PostgREST: Prefer resolution=merge-duplicates
        self._request(
            "POST",
            "careers_jobs",
            body=body,
            prefer="resolution=merge-duplicates,return=representation",
        )
        return self.get_job_by_id(job_id=final_job_id)

    # ── Applications ───────────────────────────────────────────────────

    def has_recent_duplicate_application(self, *, job_id: str, email: str, window_days: int = 30) -> bool:
        if not self._available:
            return False
        normalized_email = _normalize_email(email)
        if not normalized_email or not (job_id or "").strip():
            return False
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, int(window_days)))).isoformat()
        params = {
            "select": "id",
            "job_id": f"eq.{job_id.strip()}",
            "email": f"eq.{normalized_email}",
            "submission_status": "in.(submitted,under_review,shortlisted,rejected)",
            "created_at": f"gte.{cutoff}",
            "limit": "1",
        }
        result = self._request("GET", "careers_applications", params=params)
        return bool(isinstance(result, list) and result)

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

        now_iso = _now_iso()
        final_application_id = (application_id or "").strip() or f"app_{uuid.uuid4().hex}"
        final_reference_id = (reference_id or "").strip() or f"OFS-{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:6].upper()}"
        normalized_email = _normalize_email(email)

        body = {
            "id": final_application_id,
            "reference_id": final_reference_id,
            "job_id": job_id.strip(),
            "full_name": full_name.strip(),
            "email": normalized_email,
            "phone": (phone or "").strip() or None,
            "linkedin_url": (linkedin_url or "").strip() or None,
            "years_experience": years_experience,
            "cover_note": (cover_note or "").strip() or None,
            "consent_accepted": 1 if consent_accepted else 0,
            "resume_blob_path": resume_blob_path,
            "resume_original_name": resume_original_name,
            "resume_content_type": resume_content_type,
            "resume_size_bytes": int(resume_size_bytes),
            "submission_status": "draft_upload_pending",
            "created_at": now_iso,
            "submitted_at": None,
            "updated_at": now_iso,
        }

        self._request("POST", "careers_applications", body=body, prefer="return=representation")
        return {
            "application_id": final_application_id,
            "reference_id": final_reference_id,
            "resume_blob_path": resume_blob_path,
        }

    def get_application_by_id(self, *, application_id: str) -> dict[str, Any] | None:
        if not self._available or not (application_id or "").strip():
            return None
        params = {
            "select": "id,reference_id,job_id,email,resume_blob_path,resume_content_type,resume_size_bytes,submission_status,hr_email_sent,hr_email_sent_at,created_at,submitted_at,updated_at",
            "id": f"eq.{application_id.strip()}",
            "limit": "1",
        }
        result = self._request("GET", "careers_applications", params=params)
        if isinstance(result, list) and result:
            return result[0]
        return None

    def finalize_submission(self, *, application_id: str) -> dict[str, Any] | None:
        if not self._available:
            return None

        now_iso = _now_iso()
        # Check current status
        existing = self.get_application_by_id(application_id=application_id)
        if not existing or existing.get("submission_status") != "draft_upload_pending":
            return None

        # Update status
        self._request(
            "PATCH",
            "careers_applications",
            body={"submission_status": "submitted", "submitted_at": now_iso, "updated_at": now_iso},
            params={"id": f"eq.{application_id.strip()}"},
        )

        # Create analysis row if not exists
        analysis_id = f"ana_{uuid.uuid4().hex}"
        self._request(
            "POST",
            "careers_application_analysis",
            body={
                "id": analysis_id,
                "application_id": application_id.strip(),
                "analysis_status": "not_started",
                "created_at": now_iso,
                "updated_at": now_iso,
            },
            prefer="resolution=merge-duplicates",
        )

        return {
            "application_id": application_id.strip(),
            "reference_id": existing.get("reference_id"),
            "status": "submitted",
        }

    def mark_hr_email_sent(self, *, application_id: str) -> None:
        if not self._available:
            return
        now_iso = _now_iso()
        self._request(
            "PATCH",
            "careers_applications",
            body={"hr_email_sent": 1, "hr_email_sent_at": now_iso, "updated_at": now_iso},
            params={"id": f"eq.{application_id.strip()}"},
        )

    def mark_applicant_followup_sent(self, *, application_id: str) -> None:
        if not self._available:
            return
        now_iso = _now_iso()
        self._request(
            "PATCH",
            "careers_applications",
            body={"applicant_email_sent_at": now_iso, "updated_at": now_iso},
            params={"id": f"eq.{application_id.strip()}"},
        )

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

        # Use the RPC-free approach: query applications with joins via foreign key
        # PostgREST supports embedded resources via select with fk reference
        select_fields = (
            "id,reference_id,job_id,full_name,email,resume_original_name,"
            "submission_status,created_at,submitted_at,"
            "careers_application_analysis(analysis_status,match_score),"
            "careers_jobs!left(title)"
        )
        fallback_select_fields = (
            "id,reference_id,job_id,full_name,email,resume_original_name,"
            "submission_status,created_at,submitted_at"
        )
        params: dict[str, str] = {
            "select": select_fields,
            "order": "created_at.desc",
            "limit": str(max(1, int(limit))),
            "offset": str(max(0, int(offset))),
        }
        if (status or "").strip():
            params["submission_status"] = f"eq.{str(status).strip()}"
        if (job_id or "").strip():
            params["job_id"] = f"eq.{str(job_id).strip()}"

        try:
            result = self._request("GET", "careers_applications", params=params)
        except Exception as exc:
            fallback_params = dict(params)
            fallback_params["select"] = fallback_select_fields
            _logger.warning(
                "list_applications falling back to base fields because embedded relationship lookup failed: %s",
                exc,
            )
            result = self._request("GET", "careers_applications", params=fallback_params)
        if not isinstance(result, list):
            return []

        # Flatten the nested response for API compatibility
        rows: list[dict[str, Any]] = []
        for item in result:
            analysis = item.get("careers_application_analysis") or {}
            job = item.get("careers_jobs") or {}
            rows.append({
                "id": item.get("id"),
                "reference_id": item.get("reference_id"),
                "job_id": item.get("job_id"),
                "job_title": job.get("title") if isinstance(job, dict) else None,
                "full_name": item.get("full_name"),
                "email": item.get("email"),
                "resume_original_name": item.get("resume_original_name"),
                "submission_status": item.get("submission_status"),
                "created_at": item.get("created_at"),
                "submitted_at": item.get("submitted_at"),
                "analysis_status": analysis.get("analysis_status") if isinstance(analysis, dict) else None,
                "match_score": analysis.get("match_score") if isinstance(analysis, dict) else None,
            })
        return rows

    def get_application_detail(self, *, application_id: str) -> dict[str, Any] | None:
        if not self._available or not (application_id or "").strip():
            return None

        select_fields = (
            "id,reference_id,job_id,full_name,email,phone,linkedin_url,years_experience,"
            "cover_note,resume_blob_path,resume_original_name,resume_content_type,resume_size_bytes,"
            "submission_status,hr_email_sent,hr_email_sent_at,applicant_email_sent_at,"
            "created_at,submitted_at,updated_at,"
            "careers_application_analysis(analysis_status,match_score,matched_skills_json,"
            "missing_skills_json,strengths_summary,gaps_summary,recommendation,analyzed_by,analyzed_at),"
            "careers_jobs!left(title)"
        )
        params = {
            "select": select_fields,
            "id": f"eq.{application_id.strip()}",
            "limit": "1",
        }
        result = self._request("GET", "careers_applications", params=params)
        if not isinstance(result, list) or not result:
            return None

        item = result[0]
        analysis = item.get("careers_application_analysis") or {}
        job = item.get("careers_jobs") or {}

        # Flatten for API compatibility
        return {
            "id": item.get("id"),
            "reference_id": item.get("reference_id"),
            "job_id": item.get("job_id"),
            "job_title": job.get("title") if isinstance(job, dict) else None,
            "full_name": item.get("full_name"),
            "email": item.get("email"),
            "phone": item.get("phone"),
            "linkedin_url": item.get("linkedin_url"),
            "years_experience": item.get("years_experience"),
            "cover_note": item.get("cover_note"),
            "resume_blob_path": item.get("resume_blob_path"),
            "resume_original_name": item.get("resume_original_name"),
            "resume_content_type": item.get("resume_content_type"),
            "resume_size_bytes": item.get("resume_size_bytes"),
            "submission_status": item.get("submission_status"),
            "hr_email_sent": item.get("hr_email_sent"),
            "hr_email_sent_at": item.get("hr_email_sent_at"),
            "applicant_email_sent_at": item.get("applicant_email_sent_at"),
            "created_at": item.get("created_at"),
            "submitted_at": item.get("submitted_at"),
            "updated_at": item.get("updated_at"),
            "analysis_status": analysis.get("analysis_status") if isinstance(analysis, dict) else None,
            "match_score": analysis.get("match_score") if isinstance(analysis, dict) else None,
            "matched_skills_json": analysis.get("matched_skills_json") if isinstance(analysis, dict) else None,
            "missing_skills_json": analysis.get("missing_skills_json") if isinstance(analysis, dict) else None,
            "strengths_summary": analysis.get("strengths_summary") if isinstance(analysis, dict) else None,
            "gaps_summary": analysis.get("gaps_summary") if isinstance(analysis, dict) else None,
            "recommendation": analysis.get("recommendation") if isinstance(analysis, dict) else None,
            "analyzed_by": analysis.get("analyzed_by") if isinstance(analysis, dict) else None,
            "analyzed_at": analysis.get("analyzed_at") if isinstance(analysis, dict) else None,
        }

    def update_application_status(self, *, application_id: str, status: str) -> bool:
        if not self._available:
            return False
        now_iso = _now_iso()
        result = self._request(
            "PATCH",
            "careers_applications",
            body={"submission_status": status.strip(), "updated_at": now_iso},
            params={"id": f"eq.{application_id.strip()}"},
            prefer="return=representation",
        )
        return bool(isinstance(result, list) and result)

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

        now_iso = _now_iso()
        normalized_application_id = application_id.strip()

        body: dict[str, Any] = {
            "application_id": normalized_application_id,
            "analysis_status": analysis_status.strip(),
            "updated_at": now_iso,
        }
        if analyzed_by:
            body["analyzed_by"] = analyzed_by.strip()
        if recommendation:
            body["recommendation"] = recommendation.strip()
        if match_score is not None:
            body["match_score"] = match_score
        if matched_skills_json:
            body["matched_skills_json"] = matched_skills_json
        if missing_skills_json:
            body["missing_skills_json"] = missing_skills_json
        if strengths_summary:
            body["strengths_summary"] = strengths_summary
        if gaps_summary:
            body["gaps_summary"] = gaps_summary
        body["analyzed_at"] = now_iso

        existing = self._request(
            "GET",
            "careers_application_analysis",
            params={
                "select": "id",
                "application_id": f"eq.{normalized_application_id}",
                "limit": "1",
            },
        )

        if isinstance(existing, list) and existing:
            existing_id = str(existing[0].get("id") or "").strip()
            if not existing_id:
                return False
            self._request(
                "PATCH",
                "careers_application_analysis",
                body=body,
                params={"id": f"eq.{existing_id}"},
                prefer="return=representation",
            )
            return True

        insert_body = {
            **body,
            "id": f"ana_{uuid.uuid4().hex}",
            "created_at": now_iso,
        }
        self._request(
            "POST",
            "careers_application_analysis",
            body=insert_body,
            prefer="return=representation",
        )
        return True

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
        body = {
            "id": f"act_{uuid.uuid4().hex}",
            "admin_user_id": admin_user_id.strip() or "unknown",
            "action_type": action_type.strip(),
            "entity_type": entity_type.strip(),
            "entity_id": entity_id.strip(),
            "action_detail": (action_detail or "").strip() or None,
            "created_at": _now_iso(),
        }
        try:
            self._request("POST", "careers_admin_action_log", body=body)
        except Exception as exc:
            _logger.warning("Failed to log admin action: %s", exc)

    def mark_stale_drafts_upload_failed(self, *, older_than_hours: int = 24) -> int:
        if not self._available:
            return 0
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=max(1, int(older_than_hours)))).isoformat()
        now_iso = _now_iso()
        # PostgREST PATCH with filter
        result = self._request(
            "PATCH",
            "careers_applications",
            body={"submission_status": "upload_failed", "updated_at": now_iso},
            params={
                "submission_status": "eq.draft_upload_pending",
                "created_at": f"lt.{cutoff}",
            },
            prefer="return=representation",
        )
        return len(result) if isinstance(result, list) else 0


# ── Singleton ──────────────────────────────────────────────────────────

_supabase_store = CareersSupabaseStore()


def get_careers_supabase_store() -> CareersSupabaseStore:
    return _supabase_store