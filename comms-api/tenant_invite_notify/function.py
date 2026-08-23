import os
import re
import sys

import azure.functions as func

script_dir = os.path.dirname(os.path.abspath(__file__))
shared_path = os.path.join(script_dir, "..", "shared")
if shared_path not in sys.path:
    sys.path.insert(0, shared_path)

from email_client import send_email
from http_utils import error_response, get_trace_id, ok_response, options_response

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


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


async def main(req: func.HttpRequest) -> func.HttpResponse:
    trace_id = get_trace_id(req)
    if req.method == "OPTIONS":
        return options_response(trace_id=trace_id, req=req)

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

    try:
        send_email(
            to_addresses=[email],
            subject=_invite_subject(company_name),
            plain_text=_invite_body(company_name, role, accept_url, sent_by),
        )
    except Exception as exc:
        return error_response(
            error_type="infra",
            message="Failed to send admin invite email.",
            trace_id=trace_id,
            req=req,
            status_code=500,
            details={"reason": str(exc)},
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
