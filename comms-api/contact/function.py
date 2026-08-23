import os
import re
import sys

script_dir = os.path.dirname(os.path.abspath(__file__))
shared_path = os.path.join(script_dir, "..", "shared")
if shared_path not in sys.path:
    sys.path.insert(0, shared_path)

import azure.functions as func

from email_client import send_email
from http_utils import error_response, get_trace_id, ok_response, options_response

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _notify_recipients() -> list[str]:
    raw = os.environ.get("NOTIFY_RECIPIENTS", "support@ofstrideservices.com,ofstride@gmail.com")
    return [addr.strip() for addr in raw.split(",") if addr.strip()]


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

    name = str(body.get("name", "")).strip()
    email = str(body.get("email", "")).strip()
    message = str(body.get("message", "")).strip()
    phone = str(body.get("phone", "")).strip()
    company = str(body.get("company", "")).strip()
    service = str(body.get("service", "")).strip()
    budget = str(body.get("budget", "")).strip()

    if not name or not email or not message:
        return error_response(
            error_type="validation",
            message="'name', 'email', and 'message' are required.",
            trace_id=trace_id,
            req=req,
            status_code=400,
        )

    if not EMAIL_RE.match(email):
        return error_response(
            error_type="validation",
            message="'email' must be a valid email address.",
            trace_id=trace_id,
            req=req,
            status_code=400,
        )

    detail_body = "\n".join(
        [
            f"Name: {name}",
            f"Email: {email}",
            f"Phone: {phone or 'Not provided'}",
            f"Company: {company or 'Not provided'}",
            f"Service Interested In: {service or 'Not provided'}",
            f"Budget: {budget or 'Not provided'}",
            "",
            "Message:",
            message,
        ]
    )

    # Both emails must succeed for this request to be reported as successful
    # (per explicit product decision -- confirmation is not "best effort").
    try:
        send_email(
            to_addresses=[email],
            subject="We've received your message - OfStride",
            plain_text=(
                f"Hi {name},\n\n"
                "Thank you for reaching out to OfStride. We've received your message and "
                "our team will be in touch shortly.\n\n"
                "Regards,\nOfStride Team"
            ),
        )
    except Exception as exc:
        return error_response(
            error_type="infra",
            message="Failed to send confirmation email.",
            trace_id=trace_id,
            req=req,
            status_code=500,
            details={"reason": str(exc)},
        )

    try:
        send_email(
            to_addresses=_notify_recipients(),
            subject=f"New Contact Form Submission: {name}",
            plain_text=detail_body,
        )
    except Exception as exc:
        return error_response(
            error_type="infra",
            message="Failed to send team notification email.",
            trace_id=trace_id,
            req=req,
            status_code=500,
            details={"reason": str(exc)},
        )

    return ok_response(
        data={"confirmation_sent": True, "notification_sent": True},
        trace_id=trace_id,
        req=req,
    )
