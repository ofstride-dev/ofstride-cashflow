import base64
import json
import os
import sys

import azure.functions as func

script_dir = os.path.dirname(os.path.abspath(__file__))
shared_path = os.path.join(script_dir, "..", "shared")
if shared_path not in sys.path:
    sys.path.insert(0, shared_path)

from email_client import get_email_client
from http_utils import error_response, get_trace_id, ok_response, options_response


def _escape(value):
    return str(value or "").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")[:180]


def _pdf(title, sections):
    lines = [title, "", *[line for heading, rows in sections for line in ([heading, *rows, ""])]]
    lines = [line[:110] for line in lines]
    stream = "BT /F1 9 Tf 45 760 Td " + " ".join(f"({_escape(line)}) Tj 0 -13 Td" for line in lines) + " ET"
    objects = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>", "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>", f"<< /Length {len(stream.encode())} >>\nstream\n{stream}\nendstream"]
    pdf = "%PDF-1.4\n"; offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(pdf.encode())); pdf += f"{index} 0 obj\n{obj}\nendobj\n"
    xref = len(pdf.encode()); pdf += f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n" + "".join(f"{offset:010d} 00000 n \n" for offset in offsets[1:])
    pdf += f"trailer << /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF"
    return pdf.encode()


def _money(value):
    return f"INR {float(value or 0):,.2f}"


async def main(req: func.HttpRequest) -> func.HttpResponse:
    trace_id = get_trace_id(req)
    if req.method == "OPTIONS":
        return options_response(trace_id=trace_id, req=req)
    expected = os.environ.get("REPORT_EMAIL_SHARED_SECRET", "").strip()
    supplied = req.headers.get("x-report-email-secret", "")
    if not expected or supplied != expected:
        return error_response(error_type="auth", message="Report email authentication failed.", trace_id=trace_id, req=req, status_code=401)
    try:
        body = req.get_json()
        if not isinstance(body, dict):
            raise ValueError("Request body must be a JSON object.")
        recipients = sorted({str(item).strip().lower() for item in body.get("recipients", []) if str(item).strip()})
        if not recipients or len(recipients) > 500:
            raise ValueError("Between 1 and 500 recipients are required.")
        period = body.get("period") or {}
        title = f"OfStride {body.get('report_type', 'weekly').title()} Cashflow Report - {period.get('start_date')} to {period.get('end_date')}"
        sections = []
        for key, label in (("inflows", "INFLOWS"), ("outflows", "OUTFLOWS"), ("petty_cash", "PETTY CASH")):
            rows = body.get(key) or []
            sections.append((label, [json.dumps(row, default=str) for row in rows] or ["No records"]))
        attachment = base64.b64encode(_pdf(title, sections)).decode("ascii")
        metrics = body.get("metrics") or {}
        narrative = body.get("narrative") or "Cashflow report attached."
        plain = f"Hello,\n\n{narrative}\n\nPeriod: {period.get('start_date')} to {period.get('end_date')}\nInflows: {_money(metrics.get('inflow'))} ({metrics.get('inflow_count', 0)} records)\nOutflows: {_money(metrics.get('outflow'))} ({metrics.get('outflow_count', 0)} records)\nPetty cash: {_money(metrics.get('petty_cash'))} ({metrics.get('petty_cash_count', 0)} records)\nNet movement: {_money(metrics.get('net_movement'))}\n\nThe attached PDF contains the complete detail.\n\nRegards,\nOfStride Team"
        client = get_email_client()
        for recipient in recipients:
            poller = client.begin_send({"senderAddress": os.environ["EMAIL_SENDER_ADDRESS"], "content": {"subject": title, "plainText": plain}, "recipients": {"to": [{"address": recipient}]}, "attachments": [{"name": f"ofstride-{body.get('report_type', 'weekly')}-cashflow.pdf", "contentType": "application/pdf", "contentInBase64": attachment}]})
            poller.result()
        return ok_response(data={"sent": len(recipients)}, trace_id=trace_id, req=req)
    except ValueError as exc:
        return error_response(error_type="validation", message=str(exc), trace_id=trace_id, req=req, status_code=400)
    except Exception as exc:
        return error_response(error_type="infra", message="Failed to send report email.", trace_id=trace_id, req=req, status_code=500, details={"reason": str(exc)})