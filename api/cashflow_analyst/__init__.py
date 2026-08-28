"""Read-only, tenant-scoped financial analyst endpoint."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from typing import Any

import azure.functions as func

from cashflow.dashboard import DashboardRepository
from shared.admin_auth import require_cashflow_tenant
from shared.api_contract import create_response
from shared.core.llm_factory import LLMProvider, get_llm_factory
from shared.core.settings import get_settings
from shared.db import get_supabase_client
from shared.observability.langfuse_tracer import get_tracer


LOGGER = logging.getLogger("ofstride.cashflow.analyst")
MAX_ROWS = 250
MAX_QUESTION_CHARS = 2000
ALLOWED_INTENTS = {"summary", "report", "explain_metric", "explain_movement", "ask"}
REPORT_EMAIL_INTENT = "report_email"
MUTATION_MARKERS = (
    "approve", "create", "delete", "update", "edit", "send reminder", "pay bill",
    "record payment", "reconcile", "write to", "insert into", "run sql", "drop table",
)

# --- Reasoning-model handling -------------------------------------------------
# GPT-5-family models are "reasoning models": by default they run at
# reasoning_effort=medium, which spends time (and tokens) thinking before
# producing visible output. For a task like this -- formatting already
# computed, deterministic financial metrics into a grounded answer -- that
# default is wasted latency. We detect reasoning models up front (no more
# call-fails-then-retry) and pin effort/verbosity low.
#
# NOTE: reasoning_effort / verbosity are only accepted on Azure OpenAI when
# the GPT-5 deployment was created as a *reasoning-enabled* deployment via
# Azure AI Foundry. A standard gpt-5-chat deployment will reject them. Set
# ANALYST_REASONING_EFFORT="" (empty) in that case to omit the param entirely
# while still keeping the "call it right the first time" latency fix.
REASONING_MODEL_PREFIXES = ("gpt-5", "o1", "o3", "o4")
# Override at deploy/run time with env vars so you can A/B latency vs quality
# without a code change, e.g.:
#   ANALYST_REASONING_EFFORT=minimal
#   ANALYST_VERBOSITY=low
DEFAULT_REASONING_EFFORT = os.environ.get("ANALYST_REASONING_EFFORT", "minimal")
DEFAULT_VERBOSITY = os.environ.get("ANALYST_VERBOSITY", "low")


def _is_reasoning_model(model_name: str | None) -> bool:
    name = (model_name or "").lower()
    return any(name.startswith(prefix) for prefix in REASONING_MODEL_PREFIXES)


def _parse_llm_json(raw: Any) -> dict[str, Any]:
    """Parse JSON returned by chat models, including fenced JSON responses."""
    if isinstance(raw, dict):
        parsed = raw
    else:
        text = str(raw or "").strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1]).strip() if len(lines) >= 3 else ""
        parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("Analyst response was not structured JSON")
    return parsed


def _select_prompt_evidence(intent: str, question: str, evidence: dict[str, Any]) -> dict[str, Any]:
    """Keep the model context small and relevant without dropping authoritative totals."""
    question_lower = question.lower()
    selected = {"period": evidence["period"], "metrics": evidence["metrics"]}
    selected["sources"] = evidence["sources"]
    selected["unavailable"] = evidence["unavailable"]

    if intent == "explain_movement":
        names = ("dashboard", "transactions", "petty_cash")
    elif intent == "explain_metric" and any(term in question_lower for term in ("payable", "ap", "bill", "vendor")):
        names = ("accounts_payable",)
    elif intent == "explain_metric" and any(term in question_lower for term in ("receivable", "ar", "invoice", "customer", "earn", "revenue", "sales")):
        names = ("accounts_receivable",)
    elif intent in {"summary", "report"}:
        names = ("dashboard",)
    else:
        names = ("dashboard", "transactions", "petty_cash", "accounts_payable", "accounts_receivable")

    for name in names:
        if name in evidence:
            # The deterministic metrics are authoritative; rows are supporting evidence only.
            value = evidence[name]
            if isinstance(value, list):
                selected[name] = value[:60]
            elif isinstance(value, dict):
                selected[name] = {
                    key: item[:60] if isinstance(item, list) else item
                    for key, item in value.items()
                }
            else:
                selected[name] = value
    return selected


def _validated_model_fields(parsed: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    """Return only safe response fields, falling back for missing or malformed values."""
    result: dict[str, Any] = {}
    for key in ("headline", "answer"):
        value = parsed.get(key)
        if isinstance(value, str) and value.strip():
            result[key] = value.strip()
    for key in ("findings", "risks", "actions"):
        value = parsed.get(key)
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            result[key] = [item.strip() for item in value if item.strip()]
    return {**fallback, **result}


def _completion_content(completion: Any) -> str:
    """Extract message content across OpenAI SDK response representations."""
    message = completion.choices[0].message
    content = getattr(message, "content", None)
    if isinstance(content, list):
        content = "".join(
            str(item.get("text", "") if isinstance(item, dict) else getattr(item, "text", ""))
            for item in content
        )
    return str(content or "").strip()


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _to_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _resolve_range(payload: dict[str, Any]) -> tuple[date, date, str]:
    today = date.today()
    start_raw, end_raw = payload.get("start_date"), payload.get("end_date")
    if start_raw or end_raw:
        start, end = _to_date(start_raw), _to_date(end_raw)
        if not start or not end:
            raise ValueError("start_date and end_date must use YYYY-MM-DD")
        if start > end:
            raise ValueError("start_date must be <= end_date")
        return start, end, "custom"

    period = str(payload.get("period") or "month").strip().lower()
    if period == "weekly_report":
        # Previous Monday-Sunday, using the server's configured calendar.
        this_monday = today - timedelta(days=today.weekday())
        return this_monday - timedelta(days=7), this_monday - timedelta(days=1), period
    if period == "monthly_report":
        first_this_month = today.replace(day=1)
        last_previous = first_this_month - timedelta(days=1)
        return last_previous.replace(day=1), last_previous, period
    if period == "1d":
        return today, today, period
    if period == "7d":
        return today - timedelta(days=6), today, period
    if period == "30d":
        return today - timedelta(days=29), today, period
    return today.replace(day=1), today, "month"


def _rows(result: Any) -> list[dict[str, Any]]:
    data = getattr(result, "data", None)
    return [row for row in (data or []) if isinstance(row, dict)][:MAX_ROWS]


def _read_table(client: Any, table: str, select: str, company_id: str, *, date_column: str | None = None,
                start: date | None = None, end: date | None = None) -> tuple[list[dict[str, Any]], str | None]:
    try:
        query = client.table(table).select(select).eq("company_id", company_id)
        if date_column and start:
            query = query.gte(date_column, start.isoformat())
        if date_column and end:
            query = query.lte(date_column, end.isoformat())
        return _rows(query.limit(MAX_ROWS).execute()), None
    except Exception as exc:
        # Missing optional tables must produce partial coverage, not a 500.
        LOGGER.warning("Analyst source unavailable: %s", table)
        return [], f"{table}: unavailable"


def _build_evidence(client: Any, tenant: Any, start: date, end: date) -> dict[str, Any]:
    """Fetch all evidence sources concurrently.

    These five reads are independent of each other -- none needs another's
    result -- but were previously issued one after another, so total time
    was the SUM of five network round trips instead of the MAX of them.
    The Supabase python client is synchronous/blocking, so we parallelize
    with a thread pool rather than rewriting the client to be async.
    """
    company_id = tenant.company_id
    sources: list[str] = []
    unavailable: list[str] = []

    def _read_dashboard() -> tuple[str, dict[str, Any]]:
        try:
            dashboard = DashboardRepository(client).read_window(tenant, start, end)
            return "dashboard", {name: _rows(result) for name, result in dashboard.items()}
        except Exception:
            return "dashboard", None

    def _read(table: str, select: str, date_column: str) -> tuple[str, tuple[list[dict[str, Any]], str | None]]:
        return table, _read_table(client, table, select, company_id, date_column=date_column, start=start, end=end)

    jobs = {
        "dashboard": _read_dashboard,
        "transactions": lambda: _read(
            "cashflow_transactions",
            "id,transaction_date,amount,invoice_id,bill_id,transaction_type,payment_mode,reference_no,category",
            "transaction_date",
        ),
        "petty_cash": lambda: _read(
            "cashflow_petty_cash",
            "id,entry_date,cash_in,cash_out,category,description,status",
            "entry_date",
        ),
        "accounts_payable": lambda: _read(
            "cashflow_bills",
            "id,bill_number,bill_date,due_date,amount,gst_amount,tds_amount,status,vendor_id,cashflow_entities(name,msme_category)",
            "bill_date",
        ),
        "accounts_receivable": lambda: _read(
            "cashflow_invoices",
            "id,invoice_number,invoice_date,due_date,amount,gst_amount,status,customer_id,cashflow_entities(name)",
            "invoice_date",
        ),
    }

    results: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = {pool.submit(job): key for key, job in jobs.items()}
        for future in as_completed(futures):
            key = futures[future]
            try:
                name, payload = future.result()
            except Exception:
                unavailable.append(f"{key}: unavailable")
                continue
            if name == "dashboard":
                if payload is None:
                    unavailable.append("dashboard: unavailable")
                else:
                    results["dashboard"] = payload
                    sources.append("dashboard")
            else:
                rows, err = payload
                results[key] = rows
                if err:
                    unavailable.append(err)
                else:
                    sources.append(key)

    source_data = results.get("dashboard", {})
    transactions = results.get("transactions", [])
    petty_cash = results.get("petty_cash", [])
    bills = results.get("accounts_payable", [])
    invoices = results.get("accounts_receivable", [])

    inflow = sum(_safe_float(row.get("amount")) for row in transactions if str(row.get("transaction_type") or ("INFLOW" if row.get("invoice_id") else "OUTFLOW")).upper() == "INFLOW")
    outflow = sum(_safe_float(row.get("amount")) for row in transactions if str(row.get("transaction_type") or ("INFLOW" if row.get("invoice_id") else "OUTFLOW")).upper() == "OUTFLOW")
    petty_in = sum(_safe_float(row.get("cash_in")) for row in petty_cash)
    petty_out = sum(_safe_float(row.get("cash_out")) for row in petty_cash)
    pending_invoices = [row for row in invoices if str(row.get("status") or "").lower() in {"pending", "approved"}]
    open_bills = [row for row in bills if str(row.get("status") or "").lower() in {"pending", "approved"}]
    invoice_revenue = sum(_safe_float(row.get("amount")) + _safe_float(row.get("gst_amount")) for row in invoices)
    collected_revenue = sum(_safe_float(row.get("amount")) for row in transactions if row.get("invoice_id"))
    bill_commitments = sum(_safe_float(row.get("amount")) + _safe_float(row.get("gst_amount")) for row in bills)

    metrics = {
        "cash_inflow": round(inflow + petty_in, 2),
        "cash_outflow": round(outflow + petty_out, 2),
        "net_movement": round(inflow + petty_in - outflow - petty_out, 2),
        "pending_receivables": round(sum(_safe_float(row.get("amount")) + _safe_float(row.get("gst_amount")) for row in pending_invoices), 2),
        "open_payables": round(sum(_safe_float(row.get("amount")) + _safe_float(row.get("gst_amount")) for row in open_bills), 2),
        "invoice_revenue": round(invoice_revenue, 2),
        "collected_revenue": round(collected_revenue, 2),
        "bill_commitments": round(bill_commitments, 2),
        "transaction_count": len(transactions),
        "pending_invoice_count": len(pending_invoices),
        "open_bill_count": len(open_bills),
        "petty_cash_inflow": round(petty_in, 2),
        "petty_cash_outflow": round(petty_out, 2),
    }
    return {
        "period": {"start_date": start.isoformat(), "end_date": end.isoformat()},
        "metrics": metrics,
        "dashboard": source_data,
        "transactions": transactions,
        "petty_cash": petty_cash,
        "accounts_payable": bills,
        "accounts_receivable": invoices,
        "sources": sources,
        "unavailable": unavailable,
    }


def _report_metrics(evidence: dict[str, Any]) -> dict[str, Any]:
    transactions = evidence.get("transactions", [])
    petty = evidence.get("petty_cash", [])
    inflows = [row for row in transactions if str(row.get("transaction_type") or ("INFLOW" if row.get("invoice_id") else "OUTFLOW")).upper() == "INFLOW"]
    outflows = [row for row in transactions if str(row.get("transaction_type") or ("INFLOW" if row.get("invoice_id") else "OUTFLOW")).upper() == "OUTFLOW"]
    inflow = sum(_safe_float(row.get("amount")) for row in inflows)
    outflow = sum(_safe_float(row.get("amount")) for row in outflows)
    petty_total = sum(_safe_float(row.get("cash_in")) + _safe_float(row.get("cash_out")) for row in petty)
    values = [_safe_float(row.get("amount")) for row in transactions] + [_safe_float(row.get("cash_in")) + _safe_float(row.get("cash_out")) for row in petty]
    values = sorted(value for value in values if value >= 0)
    average = sum(values) / len(values) if values else 0
    median = values[len(values) // 2] if values and len(values) % 2 else ((values[len(values)//2 - 1] + values[len(values)//2]) / 2 if values else 0)
    return {"inflow": round(inflow, 2), "outflow": round(outflow, 2), "petty_cash": round(petty_total, 2), "net_movement": round(inflow - outflow, 2), "inflow_count": len(inflows), "outflow_count": len(outflows), "petty_cash_count": len(petty), "average_transaction": round(average, 2), "median_transaction": round(median, 2)}


def _send_report_email(client: Any, tenant: Any, evidence: dict[str, Any], report_type: str) -> dict[str, Any]:
    """Resolve recipients and delegate delivery to the independent comms app."""
    if tenant.role not in {"owner", "admin", "finance"}:
        raise PermissionError("Only owners, admins, and finance users can send reports.")
    recipients_response = client.table("company_memberships").select("user_id").eq("company_id", tenant.company_id).eq("status", "active").execute()
    user_ids = [row.get("user_id") for row in (recipients_response.data or []) if row.get("user_id")]
    if not user_ids:
        raise ValueError("No active workspace members have been found.")
    profiles = client.table("profiles").select("id,email").in_("id", user_ids).execute().data or []
    recipients = sorted({str(row.get("email")).strip().lower() for row in profiles if row.get("email") and "@" in str(row.get("email"))})
    if not recipients:
        raise ValueError("No active workspace members have an email address.")
    metrics = _report_metrics(evidence)
    narrative = (f"During {evidence['period']['start_date']} to {evidence['period']['end_date']}, the workspace recorded "
                 f"{metrics['inflow_count']} inflow transactions totaling INR {metrics['inflow']:,.2f} and "
                 f"{metrics['outflow_count']} outflow transactions totaling INR {metrics['outflow']:,.2f}. "
                 f"Petty cash activity totaled INR {metrics['petty_cash']:,.2f}; net movement was INR {metrics['net_movement']:,.2f}. "
                 f"Average transaction value was INR {metrics['average_transaction']:,.2f}, with a median of INR {metrics['median_transaction']:,.2f}.")
    comms_url = (os.environ.get("REPORT_EMAIL_URL") or "").strip()
    secret = os.environ.get("REPORT_EMAIL_SHARED_SECRET") or ""
    if not comms_url or not secret:
        raise RuntimeError("Report email service is not configured.")
    # The report is a cash-movement report: include actual payment/collection
    # transactions only, rather than repeating invoice and bill master rows.
    # Invoice/bill IDs remain on each transaction so recipients can trace it
    # back to the ledger without receiving duplicate non-cash records.
    inflows = [row for row in evidence.get("transactions", []) if row.get("invoice_id")]
    outflows = [row for row in evidence.get("transactions", []) if row.get("bill_id")]
    payload = {
        "report_type": report_type,
        "period": evidence["period"],
        "metrics": metrics,
        "narrative": narrative,
        "recipients": recipients,
        "inflows": sorted(inflows, key=lambda r: _safe_float(r.get("amount")), reverse=True),
        "outflows": sorted(outflows, key=lambda r: _safe_float(r.get("amount")), reverse=True),
        "petty_cash": evidence.get("petty_cash", []),
    }
    response = requests.post(comms_url, json=payload, headers={"x-report-email-secret": secret}, timeout=120)
    if response.status_code >= 300:
        raise RuntimeError("The communications service could not send the report.")
    return {"sent": len(recipients), "period": evidence["period"], "metrics": metrics}


def _deterministic_answer(intent: str, evidence: dict[str, Any], question: str = "") -> dict[str, Any]:
    metrics = evidence["metrics"]
    net = metrics["net_movement"]
    direction = "positive" if net >= 0 else "negative"
    question_lower = question.lower()
    earnings_question = any(term in question_lower for term in ("earn", "revenue", "sales", "income"))
    if earnings_question or intent == "explain_metric" and "receivable" not in question_lower and "payable" not in question_lower:
        headline = f"Recorded revenue is ₹{metrics['invoice_revenue']:,.2f} for the selected period."
        answer = (
            f"Recorded invoice revenue is ₹{metrics['invoice_revenue']:,.2f} (including GST where present). "
            f"Cash collected against invoices is ₹{metrics['collected_revenue']:,.2f}, while "
            f"₹{metrics['pending_receivables']:,.2f} remains in pending receivables."
        )
    elif intent == "explain_movement":
        headline = f"Net cash movement is {direction} at ₹{abs(net):,.2f}."
        answer = (
            f"Cash inflow was ₹{metrics['cash_inflow']:,.2f} and cash outflow was "
            f"₹{metrics['cash_outflow']:,.2f}, producing net movement of ₹{net:,.2f}."
        )
    elif intent == "report":
        headline = "Executive cashflow report is ready."
        answer = (
            f"The period closed with net cash movement of ₹{net:,.2f}. Revenue recorded was "
            f"₹{metrics['invoice_revenue']:,.2f}; open receivables are ₹{metrics['pending_receivables']:,.2f} "
            f"and open payables are ₹{metrics['open_payables']:,.2f}."
        )
    elif intent == "explain_metric" and any(term in question_lower for term in ("payable", "ap")):
        headline = f"Open payables total ₹{metrics['open_payables']:,.2f}."
        answer = f"There are {metrics['open_bill_count']} pending or approved bills totaling ₹{metrics['open_payables']:,.2f}."
    elif intent == "explain_metric" and any(term in question_lower for term in ("receivable", "ar", "customer")):
        headline = f"Pending receivables total ₹{metrics['pending_receivables']:,.2f}."
        answer = f"There are {metrics['pending_invoice_count']} pending or approved invoices totaling ₹{metrics['pending_receivables']:,.2f}."
    else:
        headline = f"Cash movement is {direction} at ₹{abs(net):,.2f} for the selected period."
        answer = (
            f"Cash inflow was ₹{metrics['cash_inflow']:,.2f} and cash outflow was "
            f"₹{metrics['cash_outflow']:,.2f}. There are {metrics['pending_invoice_count']} open "
            f"receivables worth ₹{metrics['pending_receivables']:,.2f} and "
            f"{metrics['open_bill_count']} open payables worth ₹{metrics['open_payables']:,.2f}."
        )
    return {
        "headline": headline,
        "answer": answer,
        "findings": [
            f"Net movement: ₹{net:,.2f}",
            f"{metrics['transaction_count']} transactions were available, with ₹{metrics['petty_cash_inflow']:,.2f} in petty-cash inflow and ₹{metrics['petty_cash_outflow']:,.2f} in petty-cash outflow.",
        ],
        "risks": (["Outflows exceed inflows in this period."] if net < 0 else []) +
                 (["Receivables remain pending and should be reviewed for collection timing."] if metrics["pending_receivables"] > 0 else []),
        "actions": ["Review the largest pending receivables and upcoming payables.", "Validate the latest reconciliation before making cash commitments."],
    }


def _build_system_prompt() -> str:
    # Specificity fix: the earlier prompt let the model retreat into generic
    # explanation (see the "runway metrics" example) instead of grounding
    # the answer in the exact numbers already computed deterministically.
    # This version forces it to (a) answer the literal question, (b) cite
    # real figures from evidence.metrics rather than re-describing them in
    # the abstract, and (c) say plainly what data is missing instead of a
    # long caveat paragraph.
    return (
        "You are OfStride's read-only financial analyst for a single tenant. "
        "You will be given `evidence` containing deterministic, pre-computed "
        "metrics and supporting rows for one period. Rules:\n"
        "1. Never invent a figure. Every number in your answer must come "
        "directly from evidence.metrics or the supporting rows.\n"
        "2. Answer the user's literal question first, in the first sentence "
        "of `answer`. Do not open with a general definition unless asked "
        "for one.\n"
        "3. If the question requires a figure that is not present in "
        "evidence (e.g. a bank balance needed for a true runway-in-days "
        "calculation), say in one short sentence which figure is missing "
        "and give the closest metric you do have instead of the fields "
        "you don't. Do not write more than one sentence about what's "
        "unavailable.\n"
        "4. Do not give tax or legal certainty, and do not describe or "
        "suggest performing any write action.\n"
        "Return strict JSON: headline (string, <=15 words), answer (string, "
        "2-4 sentences), findings (array of short strings), risks (array, "
        "may be empty), actions (array of concrete next steps, may be empty)."
    )


async def _call_reasoning_model(selection: Any, system_prompt: str, prompt: str) -> str:
    """Call a GPT-5-family (or other reasoning) model with the correct
    parameters on the first attempt -- no failed call, no wasted round trip."""
    raw_client = getattr(selection.client, "client", None)
    model_name = getattr(selection.client, "model", None)
    if raw_client is None or not model_name:
        raise RuntimeError("Reasoning model selected but raw client/model name is not exposed")

    settings = get_settings()
    LOGGER.info(
        "analyst_llm_call_start provider=azure_openai model=%s api_version=%s "
        "reasoning_effort=%s verbosity=%s timeout_seconds=%s",
        model_name,
        settings.azure_openai_api_version,
        DEFAULT_REASONING_EFFORT or "omitted",
        DEFAULT_VERBOSITY or "omitted",
        settings.llm_timeout_seconds,
    )
    kwargs: dict[str, Any] = dict(
        model=model_name,
        max_completion_tokens=max(900, min(get_settings().max_tokens, 1500)),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
    )
    if DEFAULT_REASONING_EFFORT:
        kwargs["reasoning_effort"] = DEFAULT_REASONING_EFFORT
    if DEFAULT_VERBOSITY:
        kwargs["verbosity"] = DEFAULT_VERBOSITY

    completion = await asyncio.wait_for(
        raw_client.chat.completions.create(**kwargs),
        timeout=max(3, settings.llm_timeout_seconds),
    )
    content = _completion_content(completion)
    if not content:
        raise ValueError("Analyst model returned empty content")
    LOGGER.info(
        "analyst_llm_call_success provider=azure_openai model=%s response_chars=%s",
        model_name,
        len(content),
    )
    return content


async def _synthesize(intent: str, question: str, evidence: dict[str, Any]) -> tuple[dict[str, Any], str, str | None]:
    fallback = _deterministic_answer(intent, evidence, question)
    selected_provider = "deterministic_fallback"
    started = time.monotonic()
    try:
        settings = get_settings()
        LOGGER.info(
            "analyst_llm_selection_start provider_override=%s deployment_override=%s "
            "configured_provider=%s endpoint_configured=%s azure_api_key_configured=%s "
            "analyst_reasoning_effort=%s analyst_verbosity=%s",
            settings.analyst_llm_provider or "none",
            settings.analyst_azure_openai_deployment or "none",
            settings.llm_provider,
            bool((settings.azure_openai_endpoint or "").strip()),
            bool((settings.azure_openai_api_key or "").strip()),
            DEFAULT_REASONING_EFFORT or "omitted",
            DEFAULT_VERBOSITY or "omitted",
        )
        selection = await get_llm_factory().get_healthy_llm_with_metadata(
            provider_override=settings.analyst_llm_provider,
            deployment_override=settings.analyst_azure_openai_deployment,
        )
        selected_provider = selection.provider.value
        LOGGER.info(
            "analyst_llm_selected provider=%s model=%s fallback_reason=%s",
            selected_provider,
            getattr(selection.client, "model", None) or "none",
            selection.fallback_reason or "none",
        )
        if selection.provider == LLMProvider.MOCK:
            return fallback, selection.provider.value, None

        prompt_evidence = _select_prompt_evidence(intent, question, evidence)
        prompt = json.dumps({"intent": intent, "question": question, "evidence": prompt_evidence}, default=str)
        system_prompt = _build_system_prompt()
        model_name = getattr(selection.client, "model", None)

        if _is_reasoning_model(model_name):
            # Go straight to the correctly-parameterized call. No agenerate()
            # attempt first -- that call was guaranteed to fail for GPT-5 and
            # was costing a full extra round trip on every single request.
            raw = await _call_reasoning_model(selection, system_prompt, prompt)
        else:
            LOGGER.info(
                "analyst_llm_call_start provider=%s model=%s api_version=%s "
                "reasoning_model=false timeout_seconds=%s",
                selected_provider,
                model_name or "none",
                settings.azure_openai_api_version if selected_provider == "azure_openai" else "n/a",
                settings.llm_timeout_seconds,
            )
            raw = await selection.client.agenerate(
                system_prompt=system_prompt,
                user_prompt=prompt,
                temperature=0.1,
                max_tokens=700,
            )
            LOGGER.info(
                "analyst_llm_call_success provider=%s model=%s response_chars=%s",
                selected_provider,
                model_name or "none",
                len(str(raw or "")),
            )

        parsed = _parse_llm_json(raw)
        LOGGER.info(
            "analyst_llm_response_parsed provider=%s model=%s fields=%s",
            selected_provider,
            model_name or "none",
            ",".join(sorted(parsed.keys())),
        )
        result = _validated_model_fields(parsed, fallback)
        elapsed_ms = round((time.monotonic() - started) * 1000)
        LOGGER.info(
            "analyst_synthesis provider=%s model=%s intent=%s reasoning_effort=%s verbosity=%s elapsed_ms=%s",
            selected_provider, model_name, intent, DEFAULT_REASONING_EFFORT, DEFAULT_VERBOSITY, elapsed_ms,
        )
        return result, selection.provider.value, None
    except Exception as exc:
        reason = f"{type(exc).__name__}: {str(exc)[-400:]}"
        elapsed_ms = round((time.monotonic() - started) * 1000)
        LOGGER.exception(
            "Analyst synthesis exception provider=%s elapsed_ms=%s",
            selected_provider,
            elapsed_ms,
        )
        LOGGER.warning(
            "Analyst synthesis fell back to deterministic response after %sms: %s",
            elapsed_ms, reason,
        )
        return fallback, selected_provider, reason


def main(req: func.HttpRequest) -> func.HttpResponse:
    request_started = time.monotonic()
    auth = require_cashflow_tenant(req)
    auth_ms = round((time.monotonic() - request_started) * 1000)
    if not auth["ok"]:
        return create_response(auth.get("status_code", 403), False, error=auth.get("error"))
    try:
        payload = req.get_json() or {}
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object")
        intent = str(payload.get("intent") or "summary").strip().lower()
        if intent == "report_settings":
            if str(auth["tenant"].role).lower() not in {"owner", "admin"}:
                raise PermissionError("Only owners and admins can change scheduled reports.")
            client = get_supabase_client()
            if "enabled" in payload:
                enabled = bool(payload.get("enabled"))
                client.table("company_report_settings").upsert({"company_id": auth["tenant"].company_id, "weekly_reports_enabled": enabled, "updated_by": auth["tenant"].user_id}).execute()
            rows = client.table("company_report_settings").select("weekly_reports_enabled").eq("company_id", auth["tenant"].company_id).limit(1).execute().data or []
            return create_response(200, True, data={"weekly_reports_enabled": bool(rows[0].get("weekly_reports_enabled")) if rows else False})
        if intent == REPORT_EMAIL_INTENT:
            report_type = str(payload.get("report_type") or "weekly").strip().lower()
            if report_type not in {"weekly", "monthly"}:
                raise ValueError("report_type must be weekly or monthly")
            start, end, period = _resolve_range({"period": "weekly_report" if report_type == "weekly" else "monthly_report"})
            client = get_supabase_client()
            evidence = _build_evidence(client, auth["tenant"], start, end)
            return create_response(200, True, data=_send_report_email(client, auth["tenant"], evidence, report_type))
        if intent not in ALLOWED_INTENTS:
            raise ValueError("Unsupported analyst intent")
        question = str(payload.get("question") or "").strip()[:MAX_QUESTION_CHARS]
        if any(marker in question.lower() for marker in MUTATION_MARKERS):
            raise ValueError("The financial analyst is read-only and cannot perform finance actions or database operations.")
        start, end, period = _resolve_range(payload)

        evidence_started = time.monotonic()
        evidence = _build_evidence(get_supabase_client(), auth["tenant"], start, end)
        evidence_ms = round((time.monotonic() - evidence_started) * 1000)

        synthesis_started = time.monotonic()
        result, provider, llm_error = asyncio.run(_synthesize(intent, question, evidence))
        synthesis_ms = round((time.monotonic() - synthesis_started) * 1000)

        total_ms = round((time.monotonic() - request_started) * 1000)
        LOGGER.info(
            "analyst_request intent=%s auth_ms=%s evidence_ms=%s synthesis_ms=%s total_ms=%s",
            intent, auth_ms, evidence_ms, synthesis_ms, total_ms,
        )

        result.update({
            "period": {**evidence["period"], "key": period},
            "sources": evidence["sources"],
            "coverage": {"available": evidence["sources"], "unavailable": evidence["unavailable"]},
            "provider": provider,
            "llm_fallback_used": bool(llm_error),
            "read_only": True,
        })
        # Temporary, opt-in diagnostics for environments without Application
        # Insights. Never expose this in production unless explicitly enabled.
        if llm_error and get_settings().analyst_debug_errors:
            result["analyst_debug_error"] = llm_error[:500]
        try:
            get_tracer().trace_analyst(
                # Langfuse requires a 32-character lowercase hexadecimal trace ID.
                trace_id=uuid.uuid4().hex,
                tenant_id=getattr(auth.get("tenant"), "company_id", None),
                intent=intent,
                question=question,
                period=result["period"],
                sources=evidence["sources"],
                unavailable=evidence["unavailable"],
                metrics=evidence["metrics"],
                provider=provider,
                model=get_settings().azure_openai_deployment or get_settings().model_name,
                fallback_used=bool(llm_error),
                latency_ms=total_ms,
                llm_error=llm_error,
            )
        except Exception:
            LOGGER.exception("Analyst Langfuse instrumentation failed")
        return create_response(200, True, data=result)
    except ValueError as exc:
        return create_response(400, False, error=str(exc))
    except PermissionError as exc:
        return create_response(403, False, error=str(exc))
    except Exception:
        LOGGER.exception("Financial analyst request failed")
        return create_response(500, False, error="Financial analyst is temporarily unavailable.")