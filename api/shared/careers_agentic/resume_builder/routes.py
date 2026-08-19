"""HTTP route handlers for the Resume Builder (``resume-builder/*`` paths).

These are dispatched from ``api/careers_manage/function.py`` so the feature
reuses the existing careers transport (auth, CORS, envelope, blob config)
without introducing a new Function App. All handlers return the shared
``ok_response``/``error_response`` envelope.

Phase 1 surface:
  POST   resume-builder/master-resume            upload + parse a master resume
  GET    resume-builder/master-resume            list master resumes
  GET    resume-builder/master-resume/{id}       get a master resume
  POST   resume-builder/master-resume/{id}/delete  delete a master resume
  POST   resume-builder/tailor                   tailor a master resume to a JD
  GET    resume-builder/versions/{draft_id}      list tailored versions
  GET    resume-builder/versions/{draft_id}/{v}  get a tailored version
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any

import azure.functions as func

from core.api_contract import error_response, ok_response
from core.blob_rest import resolve_blob_config_with_reason, upload_blob
from persistence.careers_store import get_careers_store
from persistence.resume_builder_store import get_resume_builder_store, get_resume_builder_store_for_draft
from .ats_scorer import compute_ats_score
from .resume_parser import parse_resume_document, parse_resume_to_json
from .resume_schema import ResumeData, normalize_resume_data
from .resume_tailor import tailor_resume_to_jd

logger = logging.getLogger("ofstride.resume_builder.routes")

MAX_RESUME_BYTES = 5 * 1024 * 1024
ALLOWED_RESUME_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".md"}
_WS_RE = re.compile(r"\s+")


def _can_access_draft(admin: dict[str, Any], draft: dict[str, Any] | None) -> bool:
    """Allow admins to access all drafts; employers only their own drafts."""
    if not draft:
        return False
    if str(admin.get("role") or "").lower() == "admin":
        return True

    created_by = str(draft.get("created_by") or "").strip()
    if not created_by:
        return False

    user_id = str(admin.get("user_id") or "").strip()
    user_name = str(admin.get("user_name") or "").strip()
    user_email = str(admin.get("user_email") or "").strip()
    return created_by in {user_id, user_name, user_email}


def _log_admin_action_safe(
    admin: dict[str, Any],
    *,
    action_type: str,
    entity_type: str,
    entity_id: str,
    action_detail: str,
) -> None:
    """Best-effort audit logging through the existing careers store."""
    try:
        store = get_careers_store()
        if not store.is_available:
            return
        store.log_admin_action(
            admin_user_id=str(admin.get("user_id") or admin.get("user_name") or "unknown"),
            action_type=action_type,
            entity_type=entity_type,
            entity_id=entity_id,
            action_detail=action_detail,
        )
    except Exception as exc:
        logger.warning("Resume builder audit log failed (%s): %s", action_type, exc)


def _resolve_draft_with_store(draft_id: str):
    """Resolve draft using current route store first, then cross-store fallback."""
    store = get_resume_builder_store()

    if store.is_available:
        try:
            draft = store.get_master_resume(draft_id)
            if draft:
                return store, draft
        except Exception:
            # Let the cross-store helper produce the detailed diagnostic path.
            pass

    return get_resume_builder_store_for_draft(draft_id)


def _master_resume_container() -> str:
    return (os.getenv("CAREERS_MASTER_RESUME_BLOB_CONTAINER") or "careers-master-resumes").strip()


def _tailored_resume_container() -> str:
    return (os.getenv("CAREERS_TAILORED_RESUME_BLOB_CONTAINER") or "careers-tailored-resumes").strip()


def _persist_master_resume_blob(filename: str, content: bytes) -> str | None:
    config, _diag = resolve_blob_config_with_reason()
    if config is None:
        return None

    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", filename)[:120] or "resume.bin"
    blob_path = f"master/{datetime.now(timezone.utc):%Y/%m/%d}/{uuid.uuid4().hex}_{safe_name}"
    upload_blob(
        config,
        container=_master_resume_container(),
        blob_path=blob_path,
        content=content,
        content_type="application/octet-stream",
    )
    return blob_path


def _persist_tailored_resume_blob(*, draft_id: str, version_id: str, resume_data: dict[str, Any]) -> str | None:
    config, _diag = resolve_blob_config_with_reason()
    if config is None:
        return None

    blob_path = f"tailored/{datetime.now(timezone.utc):%Y/%m/%d}/{draft_id}_{version_id}.json"
    payload = json.dumps(resume_data, ensure_ascii=False).encode("utf-8")
    upload_blob(
        config,
        container=_tailored_resume_container(),
        blob_path=blob_path,
        content=payload,
        content_type="application/json",
    )
    return blob_path


def _resume_text(resume: dict[str, Any]) -> str:
    parts: list[str] = []

    def _walk(obj: Any) -> None:
        if isinstance(obj, str):
            parts.append(obj)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)
        elif isinstance(obj, dict):
            for value in obj.values():
                _walk(value)

    _walk(resume)
    return " ".join(parts).lower()


def _keyword_in_text(keyword: str, text_lower: str) -> bool:
    escaped = re.escape((keyword or "").strip().lower())
    if not escaped:
        return False
    return bool(re.search(rf"(?<!\w){escaped}(?!\w)", text_lower))


def _compute_coverage(resume: dict[str, Any], jd_keywords: dict[str, Any]) -> tuple[float, list[str]]:
    jd_skills = list(jd_keywords.get("required_skills", [])) + list(jd_keywords.get("preferred_skills", []))
    if not jd_skills:
        return 100.0, []
    text = _resume_text(resume)
    missing = [s for s in jd_skills if not _keyword_in_text(str(s), text)]
    matched = len(jd_skills) - len(missing)
    return (matched / len(jd_skills)) * 100, missing


def _recompute_ats(
    *,
    master_resume: dict[str, Any],
    tailored_resume: dict[str, Any],
    jd_keywords: dict[str, Any],
) -> dict[str, Any]:
    match_pct, missing = _compute_coverage(tailored_resume, jd_keywords)
    master_text = _resume_text(master_resume)
    injectable = [skill for skill in missing if _keyword_in_text(str(skill), master_text)]
    return compute_ats_score(
        refined_resume=tailored_resume,
        job_keywords=jd_keywords,
        keyword_match_percentage=match_pct,
        missing_keywords=missing,
        injectable_keywords=injectable,
    )


def _decode_base64_content(raw: str) -> bytes:
    cleaned = "".join(raw.split())
    try:
        return base64.b64decode(cleaned, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"Invalid base64 content: {exc}") from exc


def _get_json_body(req: func.HttpRequest) -> dict[str, Any]:
    try:
        return req.get_json() or {}
    except Exception:
        return {}


async def route_resume_builder(
    req: func.HttpRequest,
    *,
    trace_id: str,
    admin: dict[str, Any],
    segments: list[str],
) -> func.HttpResponse:
    """Dispatch a resume-builder/* request to the matching handler."""
    method = req.method.upper()
    primary = segments[0] if segments else ""

    # POST resume-builder/master-resume (upload + parse)
    if method == "POST" and primary == "master-resume" and len(segments) == 1:
        return await _handle_upload_master_resume(req, trace_id, admin)

    # GET resume-builder/master-resume (list)
    if method == "GET" and primary == "master-resume" and len(segments) == 1:
        return _handle_list_master_resumes(trace_id, admin)

    # GET resume-builder/master-resume/{id}
    if method == "GET" and primary == "master-resume" and len(segments) == 2:
        return _handle_get_master_resume(trace_id, admin, segments[1])

    # POST resume-builder/master-resume/{id}/delete
    if method == "POST" and primary == "master-resume" and len(segments) == 3 and segments[2] == "delete":
        return _handle_delete_master_resume(trace_id, admin, segments[1])

    # POST resume-builder/tailor
    if method == "POST" and primary == "tailor" and len(segments) == 1:
        return await _handle_tailor(req, trace_id, admin)

    # GET resume-builder/versions/{draft_id}
    if method == "GET" and primary == "versions" and len(segments) == 2:
        return _handle_list_versions(trace_id, admin, segments[1])

    # GET resume-builder/versions/{draft_id}/{version_id}
    if method == "GET" and primary == "versions" and len(segments) == 3:
        return _handle_get_version(trace_id, admin, segments[1], segments[2])

    # POST resume-builder/versions/{draft_id}/{version_id}/save-edits
    if method == "POST" and primary == "versions" and len(segments) == 4 and segments[3] == "save-edits":
        return _handle_save_version_edits(req, trace_id, admin, segments[1], segments[2])

    return error_response(
        error_type="validation",
        message=f"Unknown resume-builder endpoint: {method} {'/'.join(segments)}",
        trace_id=trace_id,
        req=req,
        status_code=404,
    )


async def _handle_upload_master_resume(req: func.HttpRequest, trace_id: str, admin: dict[str, Any]) -> func.HttpResponse:
    from pathlib import Path

    body = _get_json_body(req)
    filename = str(body.get("filename") or "").strip()
    content_b64 = str(body.get("content_base64") or "").strip()
    title = str(body.get("title") or "").strip()

    if not filename or not content_b64:
        return error_response(
            error_type="validation", message="filename and content_base64 are required.",
            trace_id=trace_id, req=req, status_code=400,
        )

    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_RESUME_EXTENSIONS:
        return error_response(
            error_type="validation",
            message=f"Unsupported resume type '{suffix}'. Allowed: {sorted(ALLOWED_RESUME_EXTENSIONS)}",
            trace_id=trace_id, req=req, status_code=400,
        )

    try:
        content = _decode_base64_content(content_b64)
    except ValueError as exc:
        return error_response(error_type="validation", message=str(exc), trace_id=trace_id, req=req, status_code=400)

    if len(content) == 0:
        return error_response(error_type="validation", message="Resume file is empty.", trace_id=trace_id, req=req, status_code=400)
    if len(content) > MAX_RESUME_BYTES:
        return error_response(error_type="validation", message="Resume file exceeds 5MB limit.", trace_id=trace_id, req=req, status_code=400)

    try:
        markdown = parse_resume_document(content, filename)
        if not markdown.strip():
            return error_response(
                error_type="validation",
                message="Could not extract any text from the resume. It may be a scanned/image-only PDF.",
                trace_id=trace_id, req=req, status_code=422,
            )
        resume_data = await parse_resume_to_json(markdown)
    except ValueError as exc:
        return error_response(error_type="validation", message=str(exc), trace_id=trace_id, req=req, status_code=422)
    except Exception as exc:
        logger.exception("Resume parsing failed: %s", exc)
        return error_response(error_type="provider", message=f"Resume parsing failed: {exc}", trace_id=trace_id, req=req, status_code=502)

    if not title:
        name = (resume_data.get("personalInfo") or {}).get("name") or ""
        title = name.strip() or filename

    store = get_resume_builder_store()
    if not store.is_available:
        return error_response(error_type="infra", message="Resume builder store is unavailable.", trace_id=trace_id, req=req, status_code=503)

    try:
        source_blob_path = _persist_master_resume_blob(filename, content)
    except Exception as exc:
        logger.warning("Master resume blob persistence failed: %s", exc)
        source_blob_path = None

    try:
        draft = store.save_master_resume(
            created_by=admin.get("user_id") or admin.get("user_name"),
            title=title,
            resume_data=resume_data,
            source_filename=filename,
            source_blob_path=source_blob_path,
        )
        _log_admin_action_safe(
            admin,
            action_type="resume_builder_upload_master",
            entity_type="resume_draft",
            entity_id=str(draft.get("id") or "unknown"),
            action_detail=f"filename={filename};chars={len(markdown)};blob={source_blob_path or ''}",
        )
    except Exception as exc:
        logger.exception("Saving master resume failed: %s", exc)
        return error_response(error_type="infra", message=f"Failed to save resume: {exc}", trace_id=trace_id, req=req, status_code=500)

    return ok_response(data={"draft": draft, "extracted_text_chars": len(markdown)}, trace_id=trace_id, req=req)


def _handle_list_master_resumes(trace_id: str, admin: dict[str, Any]) -> func.HttpResponse:
    store = get_resume_builder_store()
    if not store.is_available:
        return error_response(error_type="infra", message="Resume builder store is unavailable.", trace_id=trace_id, status_code=503)

    try:
        drafts = store.list_master_resumes()
    except Exception as exc:
        logger.exception("Listing master resumes failed: %s", exc)
        return error_response(
            error_type="infra",
            message="Failed to list master resumes.",
            trace_id=trace_id,
            status_code=500,
            details={"reason": str(exc)},
        )

    if str(admin.get("role") or "").lower() != "admin":
        drafts = [draft for draft in drafts if _can_access_draft(admin, draft)]

    return ok_response(data={"items": drafts, "count": len(drafts), "requested_by": admin.get("user_id")}, trace_id=trace_id)


def _handle_get_master_resume(trace_id: str, admin: dict[str, Any], draft_id: str) -> func.HttpResponse:
    try:
        _, draft = _resolve_draft_with_store(draft_id)
    except Exception as exc:
        logger.exception("Getting master resume failed (%s): %s", draft_id, exc)
        return error_response(
            error_type="infra",
            message="Failed to load master resume.",
            trace_id=trace_id,
            status_code=500,
            details={"reason": str(exc)},
        )
    if not draft or not _can_access_draft(admin, draft):
        return error_response(error_type="validation", message="Master resume not found.", trace_id=trace_id, status_code=404)
    return ok_response(data={"draft": draft}, trace_id=trace_id)


def _handle_delete_master_resume(trace_id: str, admin: dict[str, Any], draft_id: str) -> func.HttpResponse:
    store = get_resume_builder_store()
    if not store.is_available:
        return error_response(error_type="infra", message="Resume builder store is unavailable.", trace_id=trace_id, status_code=503)

    try:
        target_store, draft = _resolve_draft_with_store(draft_id)
    except Exception as exc:
        logger.exception("Loading master resume before delete failed (%s): %s", draft_id, exc)
        return error_response(
            error_type="infra",
            message="Failed to load master resume.",
            trace_id=trace_id,
            status_code=500,
            details={"reason": str(exc)},
        )
    if not draft or not _can_access_draft(admin, draft):
        return error_response(error_type="validation", message="Master resume not found.", trace_id=trace_id, status_code=404)

    try:
        deleted = target_store.delete_master_resume(draft_id)
    except Exception as exc:
        logger.exception("Deleting master resume failed (%s): %s", draft_id, exc)
        return error_response(
            error_type="infra",
            message="Failed to delete master resume.",
            trace_id=trace_id,
            status_code=500,
            details={"reason": str(exc)},
        )
    if deleted:
        _log_admin_action_safe(
            admin,
            action_type="resume_builder_delete_master",
            entity_type="resume_draft",
            entity_id=draft_id,
            action_detail="deleted=true",
        )
    return ok_response(data={"deleted": deleted, "draft_id": draft_id}, trace_id=trace_id)


async def _handle_tailor(req: func.HttpRequest, trace_id: str, admin: dict[str, Any]) -> func.HttpResponse:
    body = _get_json_body(req)
    draft_id = str(body.get("draft_id") or "").strip()
    jd_text = str(body.get("jd_text") or "").strip()

    if not draft_id or not jd_text:
        return error_response(
            error_type="validation", message="draft_id and jd_text are required.",
            trace_id=trace_id, req=req, status_code=400,
        )

    store = get_resume_builder_store()
    if not store.is_available:
        return error_response(error_type="infra", message="Resume builder store is unavailable.", trace_id=trace_id, req=req, status_code=503)

    target_store, draft = _resolve_draft_with_store(draft_id)
    if not draft or not _can_access_draft(admin, draft):
        return error_response(error_type="validation", message="Master resume not found.", trace_id=trace_id, req=req, status_code=404)
    if not draft.get("resume_data"):
        return error_response(error_type="validation", message="Master resume not found.", trace_id=trace_id, req=req, status_code=404)

    try:
        result = await tailor_resume_to_jd(draft["resume_data"], jd_text)
    except Exception as exc:
        logger.exception("Resume tailoring failed: %s", exc)
        return error_response(error_type="provider", message=f"Tailoring failed: {exc}", trace_id=trace_id, req=req, status_code=502)

    try:
        version = target_store.save_tailored_version(
            draft_id=draft_id,
            jd_text=jd_text[:20000],
            jd_keywords=result.jd_keywords,
            tailored_resume=result.tailored_resume,
            ats_score=result.ats_score,
            applied_changes=result.applied_changes,
            skipped_changes=result.skipped_changes,
            strategy_notes=result.strategy_notes,
            ai_used=result.ai_used,
            ai_provider=result.ai_provider,
            ai_error=result.ai_error,
        )

        tailored_blob_path = None
        try:
            tailored_blob_path = _persist_tailored_resume_blob(
                draft_id=draft_id,
                version_id=str(version.get("id") or ""),
                resume_data=result.tailored_resume,
            )
            if tailored_blob_path:
                version["tailored_blob_path"] = tailored_blob_path
        except Exception as blob_exc:
            logger.warning("Tailored resume blob persistence failed: %s", blob_exc)

        _log_admin_action_safe(
            admin,
            action_type="resume_builder_tailor",
            entity_type="resume_version",
            entity_id=str(version.get("id") or "unknown"),
            action_detail=f"draft_id={draft_id};ai_used={bool(result.ai_used)};blob={tailored_blob_path or ''}",
        )
    except Exception as exc:
        logger.exception("Saving tailored version failed: %s", exc)
        return error_response(error_type="infra", message=f"Failed to save version: {exc}", trace_id=trace_id, req=req, status_code=500)

    return ok_response(
        data={
            "version": version,
            "ats_score": result.ats_score,
            "jd_keywords": result.jd_keywords,
            "tailored_resume": result.tailored_resume,
            "applied_changes": result.applied_changes,
            "skipped_changes": result.skipped_changes,
            "strategy_notes": result.strategy_notes,
            "ai_used": result.ai_used,
            "ai_provider": result.ai_provider,
            "ai_fallback_reason": result.ai_fallback_reason,
            "ai_error": result.ai_error,
        },
        trace_id=trace_id,
        req=req,
    )


def _handle_list_versions(trace_id: str, admin: dict[str, Any], draft_id: str) -> func.HttpResponse:
    store = get_resume_builder_store()
    if not store.is_available:
        return error_response(error_type="infra", message="Resume builder store is unavailable.", trace_id=trace_id, status_code=503)

    try:
        target_store, draft = _resolve_draft_with_store(draft_id)
    except Exception as exc:
        logger.exception("Loading master resume for versions failed (%s): %s", draft_id, exc)
        return error_response(
            error_type="infra",
            message="Failed to load master resume.",
            trace_id=trace_id,
            status_code=500,
            details={"reason": str(exc)},
        )
    if not draft or not _can_access_draft(admin, draft):
        return error_response(error_type="validation", message="Master resume not found.", trace_id=trace_id, status_code=404)

    try:
        versions = target_store.list_versions(draft_id)
    except Exception as exc:
        logger.exception("Listing versions failed (%s): %s", draft_id, exc)
        return error_response(
            error_type="infra",
            message="Failed to list tailored versions.",
            trace_id=trace_id,
            status_code=500,
            details={"reason": str(exc)},
        )
    # Surface overall score at top-level for list rendering.
    for v in versions:
        if isinstance(v.get("ats_score"), dict) and v["ats_score"].get("overall_score") is not None:
            v["overall_score"] = v["ats_score"]["overall_score"]
        elif v.get("overall_score") is None:
            v["overall_score"] = None
    return ok_response(data={"items": versions, "count": len(versions), "draft_id": draft_id}, trace_id=trace_id)


def _handle_get_version(trace_id: str, admin: dict[str, Any], draft_id: str, version_id: str) -> func.HttpResponse:
    try:
        target_store, draft = _resolve_draft_with_store(draft_id)
    except Exception as exc:
        logger.exception("Loading master resume for version failed (%s): %s", draft_id, exc)
        return error_response(
            error_type="infra",
            message="Failed to load master resume.",
            trace_id=trace_id,
            status_code=500,
            details={"reason": str(exc)},
        )
    if not draft or not _can_access_draft(admin, draft):
        return error_response(error_type="validation", message="Master resume not found.", trace_id=trace_id, status_code=404)

    try:
        version = target_store.get_version(draft_id, version_id)
    except Exception as exc:
        logger.exception("Loading tailored version failed (%s/%s): %s", draft_id, version_id, exc)
        return error_response(
            error_type="infra",
            message="Failed to load tailored version.",
            trace_id=trace_id,
            status_code=500,
            details={"reason": str(exc)},
        )
    if not version:
        return error_response(error_type="validation", message="Tailored version not found.", trace_id=trace_id, status_code=404)
    return ok_response(data={"version": version}, trace_id=trace_id)


def _handle_save_version_edits(
    req: func.HttpRequest,
    trace_id: str,
    admin: dict[str, Any],
    draft_id: str,
    version_id: str,
) -> func.HttpResponse:
    body = _get_json_body(req)
    raw_resume = body.get("tailored_resume")
    edit_note = _WS_RE.sub(" ", str(body.get("edit_note") or "").strip())

    if not isinstance(raw_resume, dict):
        return error_response(
            error_type="validation",
            message="tailored_resume object is required.",
            trace_id=trace_id,
            req=req,
            status_code=400,
        )

    try:
        target_store, draft = _resolve_draft_with_store(draft_id)
    except Exception as exc:
        logger.exception("Loading draft for edit-save failed (%s): %s", draft_id, exc)
        return error_response(
            error_type="infra",
            message="Failed to load master resume.",
            trace_id=trace_id,
            req=req,
            status_code=500,
            details={"reason": str(exc)},
        )

    if not draft or not _can_access_draft(admin, draft):
        return error_response(error_type="validation", message="Master resume not found.", trace_id=trace_id, req=req, status_code=404)

    try:
        current_version = target_store.get_version(draft_id, version_id)
    except Exception as exc:
        logger.exception("Loading version for edit-save failed (%s/%s): %s", draft_id, version_id, exc)
        return error_response(
            error_type="infra",
            message="Failed to load tailored version.",
            trace_id=trace_id,
            req=req,
            status_code=500,
            details={"reason": str(exc)},
        )

    if not current_version:
        return error_response(error_type="validation", message="Tailored version not found.", trace_id=trace_id, req=req, status_code=404)

    try:
        normalized = normalize_resume_data(raw_resume)
        edited_resume = ResumeData.model_validate(normalized).model_dump()
    except Exception as exc:
        return error_response(
            error_type="validation",
            message=f"Invalid tailored resume payload: {exc}",
            trace_id=trace_id,
            req=req,
            status_code=400,
        )

    jd_keywords = current_version.get("jd_keywords") if isinstance(current_version.get("jd_keywords"), dict) else {}
    try:
        ats_score = _recompute_ats(
            master_resume=draft.get("resume_data") or {},
            tailored_resume=edited_resume,
            jd_keywords=jd_keywords,
        )
    except Exception as exc:
        logger.warning("ATS recompute failed for edited resume (%s/%s): %s", draft_id, version_id, exc)
        ats_score = current_version.get("ats_score") if isinstance(current_version.get("ats_score"), dict) else {}

    strategy_notes = str(current_version.get("strategy_notes") or "")
    if edit_note:
        strategy_notes = (strategy_notes + "\n" if strategy_notes else "") + f"Manual edit: {edit_note}"
    else:
        strategy_notes = (strategy_notes + "\n" if strategy_notes else "") + "Manual edit saved from Resume Builder"

    try:
        new_version = target_store.save_tailored_version(
            draft_id=draft_id,
            jd_text=str(current_version.get("jd_text") or "")[:20000],
            jd_keywords=jd_keywords,
            tailored_resume=edited_resume,
            ats_score=ats_score,
            applied_changes=current_version.get("applied_changes") or [],
            skipped_changes=current_version.get("skipped_changes") or [],
            strategy_notes=strategy_notes,
            ai_used=False,
            ai_provider="manual_edit",
            ai_error=None,
        )

        tailored_blob_path = None
        try:
            tailored_blob_path = _persist_tailored_resume_blob(
                draft_id=draft_id,
                version_id=str(new_version.get("id") or ""),
                resume_data=edited_resume,
            )
            if tailored_blob_path:
                new_version["tailored_blob_path"] = tailored_blob_path
        except Exception as blob_exc:
            logger.warning("Edited tailored resume blob persistence failed: %s", blob_exc)

        _log_admin_action_safe(
            admin,
            action_type="resume_builder_save_edits",
            entity_type="resume_version",
            entity_id=str(new_version.get("id") or "unknown"),
            action_detail=(
                f"draft_id={draft_id};from_version={version_id};blob={tailored_blob_path or ''}"
            ),
        )
    except Exception as exc:
        logger.exception("Saving edited tailored resume failed: %s", exc)
        return error_response(
            error_type="infra",
            message=f"Failed to save edited tailored resume: {exc}",
            trace_id=trace_id,
            req=req,
            status_code=500,
        )

    return ok_response(data={"version": new_version}, trace_id=trace_id, req=req)


