from datetime import date, datetime, timedelta

import azure.functions as func

from shared.admin_auth import require_cashflow_tenant
from shared.api_contract import create_response
from shared.db import get_supabase_client
from shared.tenant import TenantContext
from cashflow.dashboard import DashboardRepository


def _safe_float(value) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _to_date(raw_value):
    if isinstance(raw_value, date):
        return raw_value
    if not raw_value:
        return None

    text = str(raw_value)
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _resolve_range(period: str, start_date_raw: str, end_date_raw: str):
    today = date.today()
    period_key = (period or "").strip().lower() or "month"

    if start_date_raw and end_date_raw:
        start_date = _to_date(start_date_raw)
        end_date = _to_date(end_date_raw)
        if not start_date or not end_date:
            raise ValueError("Invalid date format. Use YYYY-MM-DD")
        if start_date > end_date:
            raise ValueError("start_date must be <= end_date")
        return start_date, end_date, "custom"

    if period_key == "1d":
        return today, today, "1d"
    if period_key == "7d":
        return today - timedelta(days=6), today, "7d"
    if period_key == "30d":
        return today - timedelta(days=29), today, "30d"

    # default window: current month
    month_start = today.replace(day=1)
    return month_start, today, "month"


def _sum_amount(rows, include_gst: bool = False) -> float:
    total = 0.0
    for row in rows or []:
        amount = _safe_float(row.get("amount"))
        if include_gst:
            amount += _safe_float(row.get("gst_amount"))
        total += amount
    return round(total, 2)


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _next_month_start(d: date) -> date:
    year = d.year + (1 if d.month == 12 else 0)
    month = 1 if d.month == 12 else d.month + 1
    return date(year, month, 1)


def _is_missing_table_error(exc: Exception) -> bool:
    text = str(exc or "")
    lowered = text.lower()
    return "pgrst205" in lowered or "could not find the table" in lowered


def _empty_dashboard(start_date, end_date, applied_period) -> dict:
    """Return a zero-filled dashboard payload so new/empty workspaces render cleanly."""
    try:
        days = max((end_date - start_date).days + 1, 1)
    except Exception:
        days = 0
    return {
        "period": {
            "key": applied_period,
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
            "days": days,
        },
        "summary": {
            "cash_received": 0,
            "cash_pending": 0,
            "cash_payable": 0,
            "cash_inflow": 0,
            "cash_outflow": 0,
            "net_cash_position": 0,
            "petty_cash_balance": 0,
            "runway_months": None,
            "inflow_from_customers": 0,
            "inflow_from_petty_cash": 0,
            "outflow_to_vendors": 0,
            "outflow_from_petty_cash": 0,
        },
        "msme_alerts": [],
        "trend": {"monthly": []},
    }


def main(req: func.HttpRequest) -> func.HttpResponse:
    auth = require_cashflow_tenant(req)
    if not auth["ok"]:
        return create_response(auth["status_code"], False, error=auth["error"])
    identity = auth.get("identity") or {}
    company_id = str(identity.get("company_id") or "").strip()
    if not company_id:
        return create_response(403, False, error="Complete workspace onboarding before using the cashflow dashboard.")

    try:
        start_date, end_date, applied_period = _resolve_range(
            req.params.get("period") or "",
            req.params.get("start_date") or "",
            req.params.get("end_date") or "",
        )

        start_key = start_date.isoformat()
        end_key = end_date.isoformat()
        days_in_window = max((end_date - start_date).days + 1, 1)

        context = TenantContext(
            user_id=str(identity.get("user_id") or ""),
            company_id=company_id,
            role=str(identity.get("role") or ""),
            email=identity.get("email"),
            full_name=identity.get("full_name"),
        )
        repository = DashboardRepository(get_supabase_client())
        try:
            window = repository.read_window(context, start_date, end_date)
        except Exception as exc:
            if _is_missing_table_error(exc):
                return create_response(200, True, data=_empty_dashboard(start_date, end_date, applied_period))
            raise
        tx_rows = window["transactions"]
        petty_rows = window["petty_cash"]
        pending_ar_rows = window["pending_invoices"]
        payable_rows = window["payable_bills"]
        msme_candidates = window["msme_candidates"]

        # Last 6 months trend for dashboard charts.
        current_month = _month_start(date.today())
        trend_start = _month_start(current_month - timedelta(days=150))
        trend_start_key = trend_start.isoformat()
        trend_end_key = end_key

        try:
            trend = repository.read_trend(context, trend_start, end_date)
        except Exception as exc:
            if _is_missing_table_error(exc):
                return create_response(200, True, data=_empty_dashboard(start_date, end_date, applied_period))
            raise
        trend_tx_rows = trend["transactions"]
        trend_petty_rows = trend["petty_cash"]

        tx_data = tx_rows.data or []
        cash_received = round(sum(_safe_float(r.get("amount")) for r in tx_data if r.get("invoice_id")), 2)
        ap_paid = round(sum(_safe_float(r.get("amount")) for r in tx_data if r.get("bill_id")), 2)

        petty_cash_in = round(sum(_safe_float(r.get("cash_in")) for r in (petty_rows.data or [])), 2)
        petty_cash_out = round(sum(_safe_float(r.get("cash_out")) for r in (petty_rows.data or [])), 2)

        cash_inflow = round(cash_received + petty_cash_in, 2)
        cash_outflow = round(ap_paid + petty_cash_out, 2)
        net_cash_position = round(cash_inflow - cash_outflow, 2)

        cash_pending = _sum_amount(pending_ar_rows.data or [], include_gst=True)
        cash_payable = _sum_amount(payable_rows.data or [], include_gst=True)
        petty_cash_balance = round(petty_cash_in - petty_cash_out, 2)

        avg_daily_outflow = (cash_outflow / days_in_window) if days_in_window else 0.0
        runway_months = round((cash_pending / (avg_daily_outflow * 30.0)), 2) if avg_daily_outflow > 0 else None

        alerts = []
        for row in msme_candidates.data or []:
            vendor = (row.get("cashflow_entities") or {})
            category = str(vendor.get("msme_category") or "none")
            if category == "none":
                continue
            due = _to_date(row.get("due_date"))
            if not due:
                continue
            alerts.append(
                {
                    "vendor": vendor.get("name") or "Unknown Vendor",
                    "amount": round(_safe_float(row.get("amount")) + _safe_float(row.get("gst_amount")), 2),
                    "days_remaining": (due - date.today()).days,
                    "deadline": due.isoformat(),
                }
            )

        # Build last-6-month series: inflow, outflow, net
        series_by_month = {}
        cursor = trend_start
        while cursor <= current_month:
            key = cursor.strftime("%Y-%m")
            series_by_month[key] = {
                "month": key,
                "label": cursor.strftime("%b %Y"),
                "inflow": 0.0,
                "outflow": 0.0,
                "net": 0.0,
            }
            cursor = _next_month_start(cursor)

        for row in (trend_tx_rows.data or []):
            tx_date = _to_date(row.get("transaction_date"))
            if not tx_date:
                continue
            key = tx_date.strftime("%Y-%m")
            if key not in series_by_month:
                continue
            amt = _safe_float(row.get("amount"))
            if row.get("invoice_id"):
                series_by_month[key]["inflow"] += amt
            if row.get("bill_id"):
                series_by_month[key]["outflow"] += amt

        for row in (trend_petty_rows.data or []):
            tx_date = _to_date(row.get("entry_date"))
            if not tx_date:
                continue
            key = tx_date.strftime("%Y-%m")
            if key not in series_by_month:
                continue
            series_by_month[key]["inflow"] += _safe_float(row.get("cash_in"))
            series_by_month[key]["outflow"] += _safe_float(row.get("cash_out"))

        monthly_series = []
        for key in sorted(series_by_month.keys()):
            point = series_by_month[key]
            point["inflow"] = round(point["inflow"], 2)
            point["outflow"] = round(point["outflow"], 2)
            point["net"] = round(point["inflow"] - point["outflow"], 2)
            monthly_series.append(point)

        dashboard_data = {
            "period": {
                "key": applied_period,
                "start_date": start_key,
                "end_date": end_key,
                "days": days_in_window,
            },
            "summary": {
                "cash_received": cash_received,
                "cash_pending": cash_pending,
                "cash_payable": cash_payable,
                "cash_inflow": cash_inflow,
                "cash_outflow": cash_outflow,
                "net_cash_position": net_cash_position,
                "petty_cash_balance": petty_cash_balance,
                "runway_months": runway_months,
                "inflow_from_customers": cash_received,
                "inflow_from_petty_cash": petty_cash_in,
                "outflow_to_vendors": ap_paid,
                "outflow_from_petty_cash": petty_cash_out,
            },
            "msme_alerts": alerts[:5],
            "trend": {
                "monthly": monthly_series,
            },
        }

        return create_response(200, True, data=dashboard_data)
    except ValueError as err:
        return create_response(400, False, error=str(err))
    except Exception as err:
        # If anything else goes wrong, still return an empty dashboard so the
        # user always lands on a clean page instead of a hard error.
        logging = __import__("logging")
        logging.error(f"Dashboard aggregation failed: {str(err)}")
        return create_response(200, True, data=_empty_dashboard(start_date if 'start_date' in locals() else date.today(), end_date if 'end_date' in locals() else date.today(), applied_period if 'applied_period' in locals() else "month"))