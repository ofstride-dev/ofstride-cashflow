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
    # Priority: dedicated setting -> existing comms notify recipients -> safe fallback.
    raw = (
        os.environ.get("CAREER_NOTIFY_RECIPIENTS")
        or os.environ.get("NOTIFY_RECIPIENTS")
        or "ofstride@gmail.com,i@ofstrideservices.com"
    )
    return [addr.strip() for addr in raw.split(",") if addr and addr.strip()]


def _candidate_subject(job_title: str) -> str:
    title = (job_title or "the role").strip()
    return f"Application Update - Shortlisted for {title}"


def _candidate_body(candidate_name: str, job_title: str) -> str:
    name = (candidate_name or "Candidate").strip()
    title = (job_title or "the role").strip()
    return (
        f"Hi {name},\n\n"
        f"You have been shortlisted for {title}. "
        "Our team will share next steps and interview details soon.\n\n"
        "Please wait for our next notification.\n\n"
        "Regards,\n"
        "OfStride Team"
    )


def _support_body(payload: dict) -> str:
    return "\n".join(
        [
            "Shortlist notification sent.",
            "",
            f"Candidate Name: {str(payload.get('full_name') or '').strip()}",
            f"Candidate Email: {str(payload.get('notify_requester_email') or '').strip()}",
            f"Job Title: {str(payload.get('job_title') or '').strip()}",
            f"Application ID: {str(payload.get('application_id') or '').strip()}",
            f"Reference ID: {str(payload.get('reference_id') or '').strip()}",
            f"Action: {str(payload.get('action') or '').strip()}",
            f"Sent By: {str(payload.get('sent_by_admin') or '').strip()}",
        ]
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

    applicant_email = str(body.get("notify_requester_email") or "").strip().lower()
    candidate_name = str(body.get("full_name") or "").strip()
    job_title = str(body.get("job_title") or "").strip()
    action = str(body.get("action") or "").strip().lower()

    if not applicant_email or not EMAIL_RE.match(applicant_email):
        return error_response(
            error_type="validation",
            message="A valid notify_requester_email is required.",
            trace_id=trace_id,
            req=req,
            status_code=400,
        )

    if action and action != "invite_for_further_discussion":
        return error_response(
            error_type="validation",
            message="Unsupported action for career-notify endpoint.",
            trace_id=trace_id,
            req=req,
            status_code=400,
        )

    support_recipients = _support_recipients()

    try:
        send_email(
            to_addresses=[applicant_email],
            subject=_candidate_subject(job_title),
            plain_text=_candidate_body(candidate_name, job_title),
        )
    except Exception as exc:
        return error_response(
            error_type="infra",
            message="Failed to send shortlisted notification to candidate.",
            trace_id=trace_id,
            req=req,
            status_code=500,
            details={"reason": str(exc)},
        )

    support_error = None
    support_sent = False
    if support_recipients:
        try:
            send_email(
                to_addresses=support_recipients,
                subject=f"Shortlist Notification Sent - {job_title or 'Career Application'}",
                plain_text=_support_body(body),
            )
            support_sent = True
        except Exception as exc:
            # Do not fail candidate notification if support copy fails.
            support_error = str(exc)

    return ok_response(
        data={
            "candidate_sent": True,
            "support_sent": support_sent,
            "support_error": support_error,
        },
        trace_id=trace_id,
        req=req,
    )