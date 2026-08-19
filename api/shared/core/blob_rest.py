from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import format_datetime
import os
from urllib import error as url_error
from urllib import parse as url_parse
from urllib import request as url_request


@dataclass(frozen=True)
class BlobRestConfig:
    account_name: str
    account_key: str | None
    shared_sas: str | None
    blob_endpoint: str


def resolve_blob_connection_string() -> str:
    """Resolve blob connection string from careers-specific or host defaults.

    Priority:
    1) CAREERS_BLOB_CONNECTION_STRING
    2) AzureWebJobsStorage
    """
    return (
        (os.getenv("CAREERS_BLOB_CONNECTION_STRING") or "").strip()
        or (os.getenv("AzureWebJobsStorage") or "").strip()
    )


def resolve_blob_config_with_reason() -> tuple[BlobRestConfig | None, dict[str, object]]:
    """Resolve blob config with robust fallback and diagnostics.

    Attempts in order:
    1) CAREERS_BLOB_CONNECTION_STRING
    2) AzureWebJobsStorage
    """
    careers_raw = (os.getenv("CAREERS_BLOB_CONNECTION_STRING") or "").strip()
    host_raw = (os.getenv("AzureWebJobsStorage") or "").strip()

    diagnostics: dict[str, object] = {
        "CAREERS_BLOB_CONNECTION_STRING_set": bool(careers_raw),
        "AzureWebJobsStorage_set": bool(host_raw),
        "selected_source": None,
        "config_reason": None,
        "careers_reason": None,
        "host_reason": None,
    }

    if careers_raw:
        cfg, reason = blob_config_with_reason(careers_raw)
        diagnostics["careers_reason"] = reason
        if cfg is not None:
            diagnostics["selected_source"] = "CAREERS_BLOB_CONNECTION_STRING"
            return cfg, diagnostics

    if host_raw:
        cfg, reason = blob_config_with_reason(host_raw)
        diagnostics["host_reason"] = reason
        if cfg is not None:
            diagnostics["selected_source"] = "AzureWebJobsStorage"
            return cfg, diagnostics

    diagnostics["config_reason"] = diagnostics.get("careers_reason") or diagnostics.get("host_reason") or "missing_connection_string"
    return None, diagnostics


def parse_connection_string(raw: str) -> dict[str, str]:
    parts: dict[str, str] = {}
    for token in (raw or "").split(";"):
        if not token or "=" not in token:
            continue
        key, value = token.split("=", 1)
        parts[key.strip()] = value.strip()
    return parts


def blob_config_from_connection_string(raw: str) -> BlobRestConfig | None:
    config, _ = blob_config_with_reason(raw)
    return config


def blob_config_with_reason(raw: str) -> tuple[BlobRestConfig | None, str | None]:
    raw = (raw or "").strip()
    if not raw:
        return None, "missing_connection_string"

    parsed = parse_connection_string(raw)
    account_name = (parsed.get("AccountName") or "").strip()
    endpoint = (parsed.get("BlobEndpoint") or "").strip()
    account_key = (parsed.get("AccountKey") or "").strip() or None
    shared_sas = (parsed.get("SharedAccessSignature") or "").strip().lstrip("?") or None

    # Support direct SAS URL in app setting value.
    if not parsed and raw.startswith("https://") and "?" in raw:
        parsed_url = url_parse.urlparse(raw)
        endpoint = f"{parsed_url.scheme}://{parsed_url.netloc}"
        path_parts = [part for part in parsed_url.path.split("/") if part]
        host_parts = parsed_url.netloc.split(".")
        account_name = host_parts[0] if host_parts else ""
        shared_sas = parsed_url.query.lstrip("?") or None

    if endpoint and not account_name:
        host = url_parse.urlparse(endpoint).netloc
        host_parts = host.split(".")
        account_name = host_parts[0] if host_parts else ""

    if not account_name:
        return None, "missing_account_name"

    if not endpoint:
        suffix = (parsed.get("EndpointSuffix") or "core.windows.net").strip()
        endpoint = f"https://{account_name}.blob.{suffix}"

    if not account_key and not shared_sas:
        return None, "missing_account_auth"

    return BlobRestConfig(
        account_name=account_name,
        account_key=account_key,
        shared_sas=shared_sas,
        blob_endpoint=endpoint.rstrip("/"),
    ), None


def blob_url(config: BlobRestConfig, container: str, blob_path: str | None = None, query: dict[str, str] | None = None) -> str:
    path = f"/{container.strip('/')}"
    if blob_path:
        path += f"/{blob_path.lstrip('/')}"

    qp: list[tuple[str, str]] = []
    if query:
        qp.extend((k, v) for k, v in query.items() if v is not None)
    if config.shared_sas:
        for key, value in url_parse.parse_qsl(config.shared_sas, keep_blank_values=True):
            qp.append((key, value))

    suffix = f"?{url_parse.urlencode(qp)}" if qp else ""
    return f"{config.blob_endpoint}{path}{suffix}"


def _canonicalized_headers(headers: dict[str, str]) -> str:
    items = []
    for key, value in headers.items():
        lower = key.lower().strip()
        if lower.startswith("x-ms-"):
            items.append((lower, " ".join(str(value).strip().split())))
    items.sort(key=lambda item: item[0])
    return "".join(f"{k}:{v}\n" for k, v in items)


def _canonicalized_resource(account_name: str, container: str, blob_path: str | None, query: dict[str, str] | None) -> str:
    resource = f"/{account_name}/{container.strip('/')}"
    if blob_path:
        resource += f"/{blob_path.lstrip('/')}"

    if query:
        for key in sorted(query.keys(), key=lambda value: value.lower()):
            value = query[key]
            if value is None:
                continue
            resource += f"\n{key.lower()}:{value}"
    return resource


def _authorization_header(
    *,
    config: BlobRestConfig,
    method: str,
    container: str,
    blob_path: str | None,
    query: dict[str, str] | None,
    headers: dict[str, str],
    content_length: int,
    content_type: str,
) -> str:
    if not config.account_key:
        raise RuntimeError("Account key is required for SharedKey authorization.")

    canonical_headers = _canonicalized_headers(headers)
    canonical_resource = _canonicalized_resource(config.account_name, container, blob_path, query)
    length_value = str(content_length) if content_length > 0 else ""

    string_to_sign = (
        f"{method}\n"  # VERB
        f"\n"  # Content-Encoding
        f"\n"  # Content-Language
        f"{length_value}\n"  # Content-Length
        f"\n"  # Content-MD5
        f"{content_type}\n"  # Content-Type
        f"\n"  # Date
        f"\n"  # If-Modified-Since
        f"\n"  # If-Match
        f"\n"  # If-None-Match
        f"\n"  # If-Unmodified-Since
        f"\n"  # Range
        f"{canonical_headers}"
        f"{canonical_resource}"
    )

    key = base64.b64decode(config.account_key)
    digest = hmac.new(key, string_to_sign.encode("utf-8"), hashlib.sha256).digest()
    signature = base64.b64encode(digest).decode("utf-8")
    return f"SharedKey {config.account_name}:{signature}"


def _request(
    *,
    config: BlobRestConfig,
    method: str,
    container: str,
    blob_path: str | None = None,
    query: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
) -> tuple[int, dict[str, str], bytes]:
    payload = body or b""
    request_headers = {"x-ms-version": "2021-12-02"}
    request_headers["x-ms-date"] = format_datetime(datetime.now(timezone.utc), usegmt=True)
    if headers:
        request_headers.update(headers)

    content_type = request_headers.get("Content-Type", "")
    if payload:
        request_headers["Content-Length"] = str(len(payload))

    if not config.shared_sas:
        request_headers["Authorization"] = _authorization_header(
            config=config,
            method=method,
            container=container,
            blob_path=blob_path,
            query=query,
            headers=request_headers,
            content_length=len(payload),
            content_type=content_type,
        )

    req = url_request.Request(
        blob_url(config, container, blob_path=blob_path, query=query),
        data=payload if payload else None,
        headers=request_headers,
        method=method,
    )
    try:
        with url_request.urlopen(req, timeout=20) as response:
            return response.status, dict(response.headers.items()), response.read() or b""
    except url_error.HTTPError as exc:
        return exc.code, dict(exc.headers.items()) if exc.headers else {}, exc.read() or b""


def ensure_container(config: BlobRestConfig, container: str) -> None:
    status, _, _ = _request(
        config=config,
        method="PUT",
        container=container,
        query={"restype": "container"},
        headers={"Content-Length": "0"},
        body=b"",
    )
    if status not in (201, 202, 409):
        raise RuntimeError(f"Container create failed with status {status}")


def upload_blob(config: BlobRestConfig, *, container: str, blob_path: str, content: bytes, content_type: str) -> None:
    ensure_container(config, container)
    status, _, body = _request(
        config=config,
        method="PUT",
        container=container,
        blob_path=blob_path,
        headers={
            "x-ms-blob-type": "BlockBlob",
            "Content-Type": content_type,
        },
        body=content,
    )
    if status not in (200, 201):
        raise RuntimeError(f"Blob upload failed with status {status}: {body.decode('utf-8', errors='replace')[:300]}")


def get_blob_properties(config: BlobRestConfig, *, container: str, blob_path: str) -> dict[str, str] | None:
    status, headers, _ = _request(
        config=config,
        method="HEAD",
        container=container,
        blob_path=blob_path,
    )
    if status == 404:
        return None
    if status not in (200,):
        raise RuntimeError(f"Blob HEAD failed with status {status}")
    return headers
