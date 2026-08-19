/**
 * Expense Export Service
 * Generates GST-compliant expense claim forms in XLSX and PDF formats.
 */

import * as XLSX from "xlsx";
import { STATUS_LABELS } from "./expenseService";

interface ExpenseAttachment {
  file_name: string;
}

interface StatusHistoryEntry {
  from_status: string | null;
  to_status: string;
  comment: string | null;
  changed_at: string;
}

interface ExpenseRecord {
  id: string;
  company_id: string;
  user_id: string;
  amount: number;
  currency: string;
  spend_date: string;
  category: string;
  description: string;
  client_project: string | null;
  has_invoice: boolean;
  supplier_gstin: string | null;
  taxable_value: number | null;
  cgst: number | null;
  sgst: number | null;
  igst: number | null;
  invoice_number: string | null;
  status: string;
  payment_method: string | null;
  payment_reference: string | null;
  admin_comment: string | null;
  created_at: string;
  updated_at: string;
  claimant_name?: string | null;
}

function fmt(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  return String(v);
}

function fmtMoney(v: number | null | undefined, currency = "INR"): string {
  if (v === null || v === undefined) return "—";
  return `${currency} ${Number(v).toFixed(2)}`;
}

/**
 * Download a single expense claim as an XLSX file (GST-compliant format).
 */
export function downloadExpenseAsXlsx(
  expense: ExpenseRecord,
  history: StatusHistoryEntry[] = [],
  attachments: ExpenseAttachment[] = []
): void {
  const wb = XLSX.utils.book_new();

  // --- Sheet 1: Expense Claim Form ---
  const claimRows: (string | number)[][] = [
    ["OFSTRIDE — EXPENSE REIMBURSEMENT CLAIM"],
    [""],
    ["Claim ID", expense.id],
    ["Status", STATUS_LABELS[expense.status] || expense.status],
    ["Created At", fmt(expense.created_at)],
    ["Last Updated", fmt(expense.updated_at)],
    [""],
    ["--- Claimant Details ---"],
    ["Claimant Name", fmt(expense.claimant_name)],
    ["Employee ID", fmt(expense.user_id)],
    [""],
    ["--- Expense Details ---"],
    ["Category", fmt(expense.category)],
    ["Spend Date", fmt(expense.spend_date)],
    ["Description", fmt(expense.description)],
    ["Client / Project", fmt(expense.client_project)],
    ["Currency", fmt(expense.currency)],
    ["Amount", Number(expense.amount).toFixed(2)],
    [""],
    ["--- GST / Invoice Details ---"],
    ["Has Invoice", expense.has_invoice ? "Yes" : "No"],
    ["Invoice Number", fmt(expense.invoice_number)],
    ["Supplier GSTIN", fmt(expense.supplier_gstin)],
    ["Taxable Value", expense.taxable_value != null ? Number(expense.taxable_value).toFixed(2) : "—"],
    ["CGST", expense.cgst != null ? Number(expense.cgst).toFixed(2) : "—"],
    ["SGST", expense.sgst != null ? Number(expense.sgst).toFixed(2) : "—"],
    ["IGST", expense.igst != null ? Number(expense.igst).toFixed(2) : "—"],
    [""],
    ["--- Payment Details ---"],
    ["Payment Method", fmt(expense.payment_method)],
    ["Payment Reference", fmt(expense.payment_reference)],
    ["Admin Comment", fmt(expense.admin_comment)],
  ];

  const ws1 = XLSX.utils.aoa_to_sheet(claimRows);
  ws1["!cols"] = [{ wch: 28 }, { wch: 50 }];
  // Merge title row
  ws1["!merges"] = [{ s: { r: 0, c: 0 }, e: { r: 0, c: 1 } }];
  XLSX.utils.book_append_sheet(wb, ws1, "Claim Form");

  // --- Sheet 2: GST Summary ---
  const gstRows: (string | number)[][] = [
    ["GST SUMMARY"],
    [""],
    ["Description", "Amount"],
    ["Taxable Value", expense.taxable_value != null ? Number(expense.taxable_value).toFixed(2) : 0],
    ["CGST", expense.cgst != null ? Number(expense.cgst).toFixed(2) : 0],
    ["SGST", expense.sgst != null ? Number(expense.sgst).toFixed(2) : 0],
    ["IGST", expense.igst != null ? Number(expense.igst).toFixed(2) : 0],
    ["Total Tax", ((expense.cgst || 0) + (expense.sgst || 0) + (expense.igst || 0)).toFixed(2)],
    ["Total Claim Amount", Number(expense.amount).toFixed(2)],
  ];
  const ws2 = XLSX.utils.aoa_to_sheet(gstRows);
  ws2["!cols"] = [{ wch: 28 }, { wch: 20 }];
  ws2["!merges"] = [{ s: { r: 0, c: 0 }, e: { r: 0, c: 1 } }];
  XLSX.utils.book_append_sheet(wb, ws2, "GST Summary");

  // --- Sheet 3: Status History ---
  const historyRows: (string | number)[][] = [
    ["STATUS HISTORY"],
    [""],
    ["From Status", "To Status", "Comment", "Changed At"],
    ...history.map((h) => [
      h.from_status ? STATUS_LABELS[h.from_status] || h.from_status : "—",
      STATUS_LABELS[h.to_status] || h.to_status,
      h.comment || "—",
      fmt(h.changed_at),
    ]),
  ];
  const ws3 = XLSX.utils.aoa_to_sheet(historyRows);
  ws3["!cols"] = [{ wch: 20 }, { wch: 20 }, { wch: 40 }, { wch: 28 }];
  ws3["!merges"] = [{ s: { r: 0, c: 0 }, e: { r: 0, c: 3 } }];
  XLSX.utils.book_append_sheet(wb, ws3, "Status History");

  // --- Sheet 4: Attachments ---
  const attachRows: (string | number)[][] = [
    ["ATTACHMENTS"],
    [""],
    ["File Name"],
    ...attachments.map((a) => [a.file_name]),
  ];
  const ws4 = XLSX.utils.aoa_to_sheet(attachRows);
  ws4["!cols"] = [{ wch: 50 }];
  ws4["!merges"] = [{ s: { r: 0, c: 0 }, e: { r: 0, c: 0 } }];
  XLSX.utils.book_append_sheet(wb, ws4, "Attachments");

  const fileName = `expense-claim-${expense.id.slice(0, 8)}.xlsx`;
  XLSX.writeFile(wb, fileName);
}

/**
 * Download a single expense claim as a PDF using the browser's print engine.
 * Opens a new window with a print-friendly layout and triggers print-to-PDF.
 */
export function downloadExpenseAsPdf(
  expense: ExpenseRecord,
  history: StatusHistoryEntry[] = [],
  attachments: ExpenseAttachment[] = []
): void {
  const printWindow = window.open("", "_blank", "width=900,height=700");
  if (!printWindow) {
    alert("Please allow pop-ups to download the PDF.");
    return;
  }

  const totalTax = (expense.cgst || 0) + (expense.sgst || 0) + (expense.igst || 0);

  const html = `<!DOCTYPE html>
<html>
<head>
  <title>Expense Claim - ${expense.id.slice(0, 8)}</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: 'Segoe UI', Arial, sans-serif; color: #1e293b; padding: 40px; }
    .header { text-align: center; margin-bottom: 30px; border-bottom: 3px solid #2563eb; padding-bottom: 20px; }
    .header h1 { font-size: 24px; color: #1e293b; }
    .header p { font-size: 13px; color: #64748b; margin-top: 4px; }
    .section { margin-bottom: 25px; }
    .section-title { font-size: 14px; font-weight: 700; color: #2563eb; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 10px; border-bottom: 1px solid #e2e8f0; padding-bottom: 5px; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 30px; }
    .field { display: flex; flex-direction: column; }
    .field-label { font-size: 11px; font-weight: 600; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.3px; }
    .field-value { font-size: 14px; color: #1e293b; margin-top: 2px; }
    .gst-table { width: 100%; border-collapse: collapse; margin-top: 10px; }
    .gst-table th, .gst-table td { border: 1px solid #cbd5e1; padding: 8px 12px; text-align: left; font-size: 13px; }
    .gst-table th { background: #f1f5f9; font-weight: 600; }
    .gst-table .total-row { font-weight: 700; background: #f8fafc; }
    .status-badge { display: inline-block; padding: 4px 12px; border-radius: 20px; font-size: 12px; font-weight: 600; background: #e0e7ff; color: #3730a3; }
    .history-item { padding: 8px 0; border-left: 3px solid #e2e8f0; padding-left: 12px; margin-bottom: 6px; }
    .history-item p { font-size: 13px; }
    .history-item .time { font-size: 11px; color: #94a3b8; }
    .footer { margin-top: 40px; text-align: center; font-size: 11px; color: #94a3b8; border-top: 1px solid #e2e8f0; padding-top: 15px; }
    @media print { body { padding: 20px; } .no-print { display: none; } }
  </style>
</head>
<body>
  <div class="header">
    <h1>OFSTRIDE — Expense Reimbursement Claim</h1>
    <p>Claim ID: ${expense.id} &nbsp;|&nbsp; Generated: ${new Date().toLocaleString("en-IN")}</p>
  </div>

  <div class="section">
    <div class="section-title">Claimant & Status</div>
    <div class="grid">
      <div class="field"><span class="field-label">Claimant Name</span><span class="field-value">${fmt(expense.claimant_name)}</span></div>
      <div class="field"><span class="field-label">Status</span><span class="field-value"><span class="status-badge">${STATUS_LABELS[expense.status] || expense.status}</span></span></div>
    </div>
  </div>

  <div class="section">
    <div class="section-title">Expense Details</div>
    <div class="grid">
      <div class="field"><span class="field-label">Category</span><span class="field-value">${fmt(expense.category)}</span></div>
      <div class="field"><span class="field-label">Spend Date</span><span class="field-value">${fmt(expense.spend_date)}</span></div>
      <div class="field"><span class="field-label">Currency</span><span class="field-value">${fmt(expense.currency)}</span></div>
      <div class="field"><span class="field-label">Amount</span><span class="field-value">${fmtMoney(expense.amount, expense.currency)}</span></div>
      <div class="field"><span class="field-label">Client / Project</span><span class="field-value">${fmt(expense.client_project)}</span></div>
      <div class="field"><span class="field-label">Description</span><span class="field-value">${fmt(expense.description)}</span></div>
    </div>
  </div>

  <div class="section">
    <div class="section-title">GST / Invoice Details</div>
    <table class="gst-table">
      <tr><th>Field</th><th>Value</th></tr>
      <tr><td>Has Invoice</td><td>${expense.has_invoice ? "Yes" : "No"}</td></tr>
      <tr><td>Invoice Number</td><td>${fmt(expense.invoice_number)}</td></tr>
      <tr><td>Supplier GSTIN</td><td>${fmt(expense.supplier_gstin)}</td></tr>
      <tr><td>Taxable Value</td><td>${expense.taxable_value != null ? fmtMoney(expense.taxable_value, expense.currency) : "—"}</td></tr>
      <tr><td>CGST</td><td>${expense.cgst != null ? fmtMoney(expense.cgst, expense.currency) : "—"}</td></tr>
      <tr><td>SGST</td><td>${expense.sgst != null ? fmtMoney(expense.sgst, expense.currency) : "—"}</td></tr>
      <tr><td>IGST</td><td>${expense.igst != null ? fmtMoney(expense.igst, expense.currency) : "—"}</td></tr>
      <tr class="total-row"><td>Total Tax</td><td>${fmtMoney(totalTax, expense.currency)}</td></tr>
      <tr class="total-row"><td>Total Claim Amount</td><td>${fmtMoney(expense.amount, expense.currency)}</td></tr>
    </table>
  </div>

  <div class="section">
    <div class="section-title">Payment Details</div>
    <div class="grid">
      <div class="field"><span class="field-label">Payment Method</span><span class="field-value">${fmt(expense.payment_method)}</span></div>
      <div class="field"><span class="field-label">Payment Reference</span><span class="field-value">${fmt(expense.payment_reference)}</span></div>
      <div class="field"><span class="field-label">Admin Comment</span><span class="field-value">${fmt(expense.admin_comment)}</span></div>
    </div>
  </div>

  ${
    history.length > 0
      ? `<div class="section">
    <div class="section-title">Status History</div>
    ${history
      .map(
        (h) => `<div class="history-item">
      <p>${h.from_status ? `${STATUS_LABELS[h.from_status] || h.from_status} → ` : ""}${STATUS_LABELS[h.to_status] || h.to_status}</p>
      ${h.comment ? `<p style="color:#64748b">${h.comment}</p>` : ""}
      <p class="time">${fmt(h.changed_at)}</p>
    </div>`
      )
      .join("")}
  </div>`
      : ""
  }

  ${
    attachments.length > 0
      ? `<div class="section">
    <div class="section-title">Attachments</div>
    <ul style="list-style:none; padding:0;">
      ${attachments.map((a) => `<li style="font-size:13px; padding:4px 0;">• ${a.file_name}</li>`).join("")}
    </ul>
  </div>`
      : ""
  }

  <div class="footer">
    <p>This is a system-generated expense claim form for GST/accounting purposes.</p>
    <p>OfStride Technologies &nbsp;|&nbsp; Generated on ${new Date().toLocaleString("en-IN")}</p>
  </div>

  <script>
    window.onload = function() { window.print(); }
  </script>
</body>
</html>`;

  printWindow.document.write(html);
  printWindow.document.close();
}