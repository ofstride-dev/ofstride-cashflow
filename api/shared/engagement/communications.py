import logging
import os

try:
    from azure.communication.email import EmailClient
    _EMAIL_IMPORT_ERROR = None
except Exception as exc:
    EmailClient = None
    _EMAIL_IMPORT_ERROR = exc


_logger = logging.getLogger("ofstride.communications")


def _email_sender_address() -> str:
    return (
        os.environ.get("EMAIL_SENDER_ADDRESS")
        or os.environ.get("ACS_EMAIL_SENDER_ADDRESS")
        or os.environ.get("COMMUNICATION_SENDER_ADDRESS")
        or os.environ.get("EMAIL_SERVICES_SENDER")
        or os.environ.get("EMAIL_SERVICES_NAME")
        or ""
    ).strip()


def _normalize_recipient(address: str | None) -> str | None:
    value = (address or "").strip()
    return value or None

def get_email_client():
    if EmailClient is None:
        _logger.warning("Azure Communication Email SDK unavailable: %s", _EMAIL_IMPORT_ERROR)
        return None

    connection_string = os.environ.get("COM_SERVICE_CON_STRING")
    if not connection_string:
        return None
    return EmailClient.from_connection_string(connection_string)


def send_email(*, to_address: str, subject: str, plain_text: str, html: str | None = None) -> tuple[bool, str | None]:
    recipient = _normalize_recipient(to_address)
    if not recipient:
        return False, "recipient_missing"

    sender_address = _email_sender_address()
    if not sender_address or "@" not in sender_address:
        return False, "sender_address_not_configured"

    email_client = get_email_client()
    if not email_client:
        return False, "acs_connection_string_not_configured"

    message = {
        "senderAddress": sender_address,
        "content": {
            "subject": subject,
            "plainText": plain_text,
        },
        "recipients": {"to": [{"address": recipient}]},
    }
    if html:
        message["content"]["html"] = html

    try:
        poller = email_client.begin_send(message)
        result = poller.result()
        status = str((result or {}).get("status") or "").lower() if isinstance(result, dict) else ""
        if status and status not in {"succeeded", "success", "queued", "running", "notstarted"}:
            return False, f"acs_send_status_{status}"
        return True, None
    except Exception as exc:  # pylint: disable=broad-except
        _logger.warning("Failed to send ACS email to %s: %s", recipient, exc)
        return False, str(exc)

def send_admin_notification(veteran_name: str, service: str):
    try:
        send_email(
            to_address=os.environ.get("ADMIN_NOTIFICATION_EMAIL", "admin@ofstrideservices.com"),
            subject=f"New Veteran Profile Registered: {veteran_name}",
            plain_text=f"A new profile has been uploaded for a veteran from the {service}. Review the details in the Supabase dashboard.",
        )
    except Exception as e:
        print(f"Failed to dispatch alert email: {str(e)}")

def send_meeting_alert(booking_data: dict):
    try:
        attendee_name = booking_data.get("attendees", [{"name": "Unknown"}])[0].get("name")
        attendee_email = booking_data.get("attendees", [{"email": "Unknown"}])[0].get("email")
        start_time = booking_data.get("startTime", "TBD")
        meeting_title = booking_data.get("title", "New Meeting")

        send_email(
            to_address=os.environ.get("ADMIN_NOTIFICATION_EMAIL", "admin@ofstrideservices.com"),
            subject=f"New Meeting Booked: {meeting_title}",
            plain_text=f"A new meeting was booked via Cal.com.\n\nAttendee: {attendee_name} ({attendee_email})\nTime: {start_time}",
        )
    except Exception as e:
        print(f"Failed to send meeting alert: {str(e)}")


def send_career_hr_notification(*, to_address: str, candidate_name: str, applicant_email: str, job_title: str, reference_id: str, application_id: str, submitted_at: str) -> tuple[bool, str | None]:
    subject = f"New Career Application: {candidate_name} for {job_title or 'Open Role'}"
    body = (
        "A new career application was submitted on the OfStride website.\n\n"
        f"Candidate: {candidate_name}\n"
        f"Applicant Email: {applicant_email}\n"
        f"Job Title: {job_title or 'Not specified'}\n"
        f"Reference ID: {reference_id}\n"
        f"Application ID: {application_id}\n"
        f"Submitted At: {submitted_at or 'Unknown'}\n"
    )
    return send_email(to_address=to_address, subject=subject, plain_text=body)


def send_career_applicant_ack(*, to_address: str, candidate_name: str, job_title: str, reference_id: str) -> tuple[bool, str | None]:
    subject = f"Application Received: {job_title or 'OfStride Opportunity'}"
    body = (
        f"Hello {candidate_name or 'there'},\n\n"
        "Thank you for applying to OfStride. We have received your application and our team is reviewing it.\n\n"
        f"Role: {job_title or 'OfStride Opportunity'}\n"
        f"Reference ID: {reference_id}\n\n"
        "We will contact you if your profile matches the next step in the process.\n\n"
        "Regards,\nOfStride Hiring Team"
    )
    return send_email(to_address=to_address, subject=subject, plain_text=body)