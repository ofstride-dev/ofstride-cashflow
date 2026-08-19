import json
import os
from urllib import error as url_error
from urllib import request as url_request

import azure.functions as func

from shared.admin_auth import identity_can_approve, require_cashflow_tenant


def _response(status_code: int, ok: bool, data=None, error: str | None = None) -> func.HttpResponse:
    body = {"ok": ok, "data": data if ok else None, "error": None if ok else error}
    return func.HttpResponse(json.dumps(body), mimetype="application/json", status_code=status_code)


def _post_json(target: str, payload: dict) -> tuple[bool, str | None]:
    req = url_request.Request(
        target,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with url_request.urlopen(req, timeout=20) as response:
            if 200 <= response.status < 300:
                return True, None
            return False, f"Invite notify failed with status {response.status}"
    except url_error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="ignore")
        return False, f"HTTP {exc.code}: {details[:240]}"
    except Exception as exc:
        return False, str(exc)


def main(req: func.HttpRequest) -> func.HttpResponse:
    action = (req.route_params.get("action") or "notify").strip().lower()
    if req.method != "POST" or action != "notify":
        return _response(404, False, error="Unsupported cashflow invite action")

    auth = require_cashflow_tenant(req)
    if not auth.get("ok"):
        return _response(auth.get("status_code", 401), False, error=auth.get("error") or "Unauthorized")

    identity = auth.get("identity") or {}
    if not identity_can_approve(identity):
        return _response(403, False, error="Only owners or admins can send invites")

    try:
        body = req.get_json()
    except ValueError:
        return _response(400, False, error="Request body must be valid JSON")

    email = str(body.get("email") or "").strip().lower()
    invite_token = str(body.get("invite_token") or "").strip()
    accept_url = str(body.get("accept_url") or "").strip()
    company_name = str(body.get("company_name") or "").strip() or "your workspace"
    role = str(body.get("role") or "admin").strip().lower()

    if not email or not invite_token or not accept_url:
        return _response(400, False, error="email, invite_token, and accept_url are required")

    target = (
        (os.getenv("CASHFLOW_INVITE_NOTIFY_URL") or "").strip()
        or "http://localhost:7072/api/tenant-invite-notify"
    )

    sent, notify_error = _post_json(
        target,
        {
            "email": email,
            "company_name": company_name,
            "role": role,
            "accept_url": accept_url,
            "sent_by": identity.get("full_name") or identity.get("email") or "Workspace Admin",
        },
    )

    if not sent:
        return _response(502, False, error=notify_error or "Invite email failed")

    return _response(200, True, data={"sent": True})
