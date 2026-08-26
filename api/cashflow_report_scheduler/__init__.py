"""Monday 09:00 IST opt-in weekly cashflow report dispatcher."""

from datetime import date, timedelta
import logging
import os

import azure.functions as func

from cashflow_analyst import _build_evidence, _send_report_email
from shared.db import get_supabase_client
from shared.tenant import TenantContext

LOGGER = logging.getLogger("ofstride.cashflow.report_scheduler")


def main(timer: func.TimerRequest) -> None:
    client = get_supabase_client()
    today = date.today()
    this_monday = today - timedelta(days=today.weekday())
    start, end = this_monday - timedelta(days=7), this_monday - timedelta(days=1)
    settings = client.table("company_report_settings").select("company_id,last_weekly_period_end").eq("weekly_reports_enabled", True).execute().data or []
    for setting in settings:
        company_id = str(setting.get("company_id") or "")
        if not company_id or str(setting.get("last_weekly_period_end") or "") == end.isoformat():
            continue
        owner = client.table("profiles").select("id,role,email,full_name").eq("company_id", company_id).eq("role", "owner").limit(1).execute().data or []
        if not owner:
            LOGGER.warning("Skipping scheduled report without owner: %s", company_id)
            continue
        tenant = TenantContext(user_id=str(owner[0]["id"]), company_id=company_id, role="owner", email=owner[0].get("email"), full_name=owner[0].get("full_name"))
        try:
            evidence = _build_evidence(client, tenant, start, end)
            _send_report_email(client, tenant, evidence, "weekly")
            client.table("company_report_settings").update({"last_weekly_period_end": end.isoformat()}).eq("company_id", company_id).eq("weekly_reports_enabled", True).execute()
        except Exception:
            LOGGER.exception("Scheduled report failed for company %s", company_id)