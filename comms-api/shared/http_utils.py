"""Lightweight JSON envelope + CORS helpers for func-ofs-comms-001.

Mirrors the response contract used by func-ofs-carrer-001
(api/shared/core/api_contract.py) so both backends behave consistently for
the frontend, but kept self-contained since this app has its own,
independent deployment source folder (comms-api/).
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

import azure.functions as func


def get_trace_id(req: func.HttpRequest | None = None) -> str:
    if req is not None and req.headers:
        incoming = req.headers.get("x-trace-id")
        if incoming:
            return incoming
    return str(uuid.uuid4())


def _allowed_origins() -> list[str]:
    raw = os.environ.get("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:4280")
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    return origins or ["*"]


def _resolve_origin(req: func.HttpRequest | None) -> str:
    allowed = _allowed_origins()
    if allowed == ["*"]:
        return "*"

    origin = None
    if req is not None and req.headers:
        origin = req.headers.get("Origin") or req.headers.get("origin")

    if origin and origin in allowed:
        return origin

    return allowed[0]


def build_headers(trace_id: str, req: func.HttpRequest | None = None) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": _resolve_origin(req),
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, X-Trace-Id",
        "X-Trace-Id": trace_id,
        "Vary": "Origin",
    }


def options_response(*, trace_id: str, req: func.HttpRequest | None = None) -> func.HttpResponse:
    return func.HttpResponse(status_code=204, headers=build_headers(trace_id, req))


def ok_response(
    *,
    data: Any,
    trace_id: str,
    req: func.HttpRequest | None = None,
    status_code: int = 200,
) -> func.HttpResponse:
    payload = {"ok": True, "data": data, "error": None, "trace_id": trace_id}
    return func.HttpResponse(
        json.dumps(payload), status_code=status_code, headers=build_headers(trace_id, req)
    )


def error_response(
    *,
    error_type: str,
    message: str,
    trace_id: str,
    req: func.HttpRequest | None = None,
    status_code: int = 500,
    details: dict[str, Any] | None = None,
) -> func.HttpResponse:
    error_payload: dict[str, Any] = {"type": error_type, "message": message}
    if details:
        error_payload["details"] = details

    payload = {"ok": False, "data": None, "error": error_payload, "trace_id": trace_id}
    return func.HttpResponse(
        json.dumps(payload), status_code=status_code, headers=build_headers(trace_id, req)
    )
