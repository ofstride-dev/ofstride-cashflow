"""Shared API response contract helpers for all HTTP functions."""

from __future__ import annotations

import json
import uuid
from typing import Any

import azure.functions as func

from .settings import get_settings


ERROR_TYPES = {
    "validation",
    "provider",
    "retrieval",
    "guardrail",
    "infra",
}


def get_trace_id(req: func.HttpRequest | None = None) -> str:
    """Reuse incoming trace id when available to keep request correlation stable."""
    if req is None:
        return str(uuid.uuid4())

    incoming = req.headers.get("x-trace-id") if req.headers else None
    if incoming:
        return incoming

    return str(uuid.uuid4())


def _allowed_origins() -> list[str]:
    raw = get_settings().allowed_origins
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    return origins or ["*"]


def _resolve_origin(req: func.HttpRequest | None = None) -> str:
    allowed = _allowed_origins()
    if allowed == ["*"]:
        return "*"

    if req is None or not req.headers:
        return allowed[0]

    origin = req.headers.get("Origin") or req.headers.get("origin")
    if origin and origin in allowed:
        return origin

    return allowed[0]


def build_headers(trace_id: str, req: func.HttpRequest | None = None) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": _resolve_origin(req),
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Trace-Id, X-Ingest-Token, X-MS-CLIENT-PRINCIPAL, X-ADMIN-KEY",
        "X-Trace-Id": trace_id,
        "Vary": "Origin",
    }


def options_response(*, trace_id: str, req: func.HttpRequest | None = None) -> func.HttpResponse:
    return func.HttpResponse(status_code=204, headers=build_headers(trace_id, req))


def ok_response(
    *,
    data: Any,
    trace_id: str,
    status_code: int = 200,
    req: func.HttpRequest | None = None,
    headers: dict[str, str] | None = None,
) -> func.HttpResponse:
    payload = {
        "ok": True,
        "data": data,
        "error": None,
        "trace_id": trace_id,
    }

    merged_headers = build_headers(trace_id, req)
    if headers:
        merged_headers.update(headers)

    return func.HttpResponse(
        json.dumps(payload),
        status_code=status_code,
        headers=merged_headers,
    )


def error_response(
    *,
    error_type: str,
    message: str,
    trace_id: str,
    status_code: int,
    req: func.HttpRequest | None = None,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> func.HttpResponse:
    normalized_error_type = error_type if error_type in ERROR_TYPES else "infra"
    payload = {
        "ok": False,
        "data": None,
        "error": {
            "type": normalized_error_type,
            "message": message,
            "details": details or {},
        },
        "trace_id": trace_id,
    }

    merged_headers = build_headers(trace_id, req)
    if headers:
        merged_headers.update(headers)

    return func.HttpResponse(
        json.dumps(payload),
        status_code=status_code,
        headers=merged_headers,
    )
