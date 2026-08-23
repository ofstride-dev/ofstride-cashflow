"""Azure Communication Services email helper, authenticated via the Function
App's managed identity only (DefaultAzureCredential) -- no connection
strings or API keys stored anywhere.
"""

from __future__ import annotations

import logging
import os

from azure.communication.email import EmailClient
from azure.identity import DefaultAzureCredential

_logger = logging.getLogger("comms.email_client")

_client: EmailClient | None = None


def _get_endpoint() -> str:
    endpoint = (os.environ.get("ACS_ENDPOINT") or "").strip()
    if not endpoint:
        raise RuntimeError("ACS_ENDPOINT app setting is required.")
    return endpoint


def _get_sender_address() -> str:
    sender = (os.environ.get("EMAIL_SENDER_ADDRESS") or "").strip()
    if not sender:
        raise RuntimeError("EMAIL_SENDER_ADDRESS app setting is required.")
    return sender


def get_email_client() -> EmailClient:
    global _client
    if _client is None:
        _client = EmailClient(endpoint=_get_endpoint(), credential=DefaultAzureCredential())
    return _client


def send_email(*, to_addresses: list[str], subject: str, plain_text: str, html: str | None = None) -> None:
    """Send an email via ACS. Raises on failure -- caller decides how to handle it."""
    recipients = [addr.strip() for addr in to_addresses if addr and addr.strip()]
    if not recipients:
        raise ValueError("At least one recipient address is required.")

    content: dict[str, str] = {"subject": subject, "plainText": plain_text}
    if html:
        content["html"] = html

    message = {
        "senderAddress": _get_sender_address(),
        "content": content,
        "recipients": {"to": [{"address": addr} for addr in recipients]},
    }

    client = get_email_client()
    poller = client.begin_send(message)
    poller.result()
