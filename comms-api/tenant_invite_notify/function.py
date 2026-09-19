import os
import re
import sys
import hashlib
import hmac
import time

import azure.functions as func

script_dir = os.path.dirname(os.path.abspath(__file__))
shared_path = os.path.join(script_dir, "..", "shared")
if shared_path not in sys.path:
    sys.path.insert(0, shared_path)

from email_client import send_email
from http_utils import error_response, get_trace_id, ok_response, options_response
from supabase import create_client
from rate_limit import allow

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_SIGNATURE_AGE_SECONDS = 300


def _delivery_client():
    url = (os.environ.get("SUPABASE_URL") or "").strip()
    key = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SERVICE_KEY") or "").strip()
    return create_client(url, key) if url and key else None


def _verify_request(req: func.HttpRequest, body: bytes) -> bool:
    secret = (os.environ.get("CASHFLOW_INVITE_SHARED_SECRET") or "").encode()
    timestamp = req.headers.get("x-cashflow-timestamp", "")
    supplied = req.headers.get("x-cashflow-signature", "")
    if not secret or not timestamp or not supplied:
        return False
    try:
        timestamp_value = int(timestamp)
    except ValueError:
        return False
    if abs(int(time.time()) - timestamp_value) > MAX_SIGNATURE_AGE_SECONDS:
        return False
    expected = hmac.new(secret, f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, supplied)


def _support_recipients() -> list[str]:
    raw = (
        os.environ.get("CAREER_NOTIFY_RECIPIENTS")
        or os.environ.get("NOTIFY_RECIPIENTS")
        or "ofstride@gmail.com,i@ofstrideservices.com"
    )
    return [addr.strip() for addr in raw.split(",") if addr and addr.strip()]


def _invite_subject(company_name: str) -> str:
    return f"Admin Invite - {company_name or 'OfStride Workspace'}"


def _invite_body(company_name: str, role: str, accept_url: str, sent_by: str) -> str:
    workspace = company_name or "your OfStride workspace"
    return (
        f"Hello,\n\n"
        f"{sent_by or 'An admin'} invited you to join {workspace} as an {role or 'admin'}.\n\n"
        f"Open this link to accept the invite:\n{accept_url}\n\n"
        "If you are new to OfStride, the link will ask for your name and a password, create your account, and take you directly into the workspace. Existing users can sign in or continue with Google.\n\n"
        "Regards,\nOfStride Team"
    )


def _mark_delivery(db, idempotency_key: str, status: str, last_error: str | None = None) -> None:
    try:
        db.table("email_deliveries").update(
            {"status": status, "last_error": last_error}
        ).eq("idempotency_key", idempotency_key).execute()
    except Exception:
        return


async def main(req: func.HttpRequest) -> func.HttpResponse:
    trace_id = get_trace_id(req)
    if req.method == "OPTIONS":
        return options_response(trace_id=trace_id, req=req)
    if not _verify_request(req, req.get_body()):
        return error_response(error_type="auth", message="Request authentication failed.", trace_id=trace_id, req=req, status_code=401)
    allowed, retry_after = allow("invite")
    if not allowed:
        return error_response(error_type="infra", message=f"Too many email requests. Try again in {retry_after} seconds.", trace_id=trace_id, req=req, status_code=429, details={"retry_after": retry_after})

    try:
        body = req.get_json()
    except ValueError:
        return error_response(
            error_type="validation",
            message="Request body must be valid JSON.",
            trace_id=trace_id,
            req=req,
            status_code=400,
        )

    if not isinstance(body, dict):
        return error_response(
            error_type="validation",
            message="Request body must be a JSON object.",
            trace_id=trace_id,
            req=req,
            status_code=400,
        )

    email = str(body.get("email") or "").strip().lower()
    accept_url = str(body.get("accept_url") or "").strip()
    idempotency_key = str(body.get("idempotency_key") or "").strip()
    company_name = str(body.get("company_name") or "").strip()
    role = str(body.get("role") or "admin").strip().lower() or "admin"
    sent_by = str(body.get("sent_by") or "Workspace Admin").strip()

    if not email or not EMAIL_RE.match(email):
        return error_response(
            error_type="validation",
            message="A valid email is required.",
            trace_id=trace_id,
            req=req,
            status_code=400,
        )

    if not accept_url:
        return error_response(
            error_type="validation",
            message="accept_url is required.",
            trace_id=trace_id,
            req=req,
            status_code=400,
        )
    if not idempotency_key:
        return error_response(error_type="validation", message="idempotency_key is required.", trace_id=trace_id, req=req, status_code=400)

    try:
        db = _delivery_client()
    except Exception as exc:
        return error_response(
            error_type="infra",
            message="Email delivery service could not connect to Supabase.",
            trace_id=trace_id,
            req=req,
            status_code=503,
            details={"stage": "supabase_client", "reason": str(exc)},
        )
    if not db:
        return error_response(error_type="infra", message="Email delivery service is not configured.", trace_id=trace_id, req=req, status_code=503)
    try:
        claimed = db.rpc("claim_email_delivery", {"p_idempotency_key": idempotency_key}).execute().data or []
        existing = db.table("email_deliveries").select("status").eq("idempotency_key", idempotency_key).limit(1).execute().data or []
    except Exception as exc:
        return error_response(
            error_type="infra",
            message="Email delivery state could not be read from Supabase.",
            trace_id=trace_id,
            req=req,
            status_code=503,
            details={"stage": "supabase_delivery_state", "reason": str(exc)},
        )
    if not existing:
        return error_response(error_type="validation", message="Unknown email delivery.", trace_id=trace_id, req=req, status_code=409)
    if existing[0].get("status") == "sent":
        return ok_response(data={"invite_sent": True, "idempotent": True}, trace_id=trace_id, req=req)
    if not claimed:
        return ok_response(data={"invite_sent": True, "delivery_pending": True}, trace_id=trace_id, req=req, status_code=202)

    try:
        send_email(
            to_addresses=[email],
            subject=_invite_subject(company_name),
            plain_text=_invite_body(company_name, role, accept_url, sent_by),
        )
        _mark_delivery(db, idempotency_key, "sent")
    except Exception as exc:
        _mark_delivery(db, idempotency_key, "unknown", "provider_send_failed")
        return error_response(
            error_type="infra",
            message="Failed to send admin invite email.",
            trace_id=trace_id,
            req=req,
            status_code=500,
            details={"stage": "acs_send", "reason": str(exc)},
        )

    support_error = None
    support_sent = False
    recipients = _support_recipients()
    if recipients:
        try:
            send_email(
                to_addresses=recipients,
                subject=f"Admin Invite Sent - {company_name or 'OfStride Workspace'}",
                plain_text=f"Invitee: {email}\nRole: {role}\nCompany: {company_name}\nSent by: {sent_by}\nAccept URL: {accept_url}",
            )
            support_sent = True
        except Exception as exc:
            support_error = str(exc)

    return ok_response(
        data={"invite_sent": True, "support_sent": support_sent, "support_error": support_error},
        trace_id=trace_id,
        req=req,
    )
