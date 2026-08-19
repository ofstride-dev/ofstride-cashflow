import { useCallback, useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { FileText, Paperclip, Download, FileSpreadsheet } from "lucide-react";
import { useCashflowAuth } from "../../context/CashflowAuthContext";
import {
  getExpense,
  getExpenseHistory,
  updateExpenseStatus,
  STATUS_LABELS,
  STATUS_BADGE_CLASSES,
  VALID_STATUS_TRANSITIONS,
} from "../../services/expenseService";
import { listAttachments, getSignedUrl } from "../../services/attachmentService";
import { downloadExpenseAsXlsx, downloadExpenseAsPdf } from "../../services/expenseExport";

const ACTION_LABELS = {
  approved: "Approve",
  rejected: "Reject",
  ready_for_payment: "Mark Ready for Payment",
  paid: "Mark Paid",
};

function StatusBadge({ status }) {
  const classes = STATUS_BADGE_CLASSES[status] || "bg-slate-100 text-slate-700 border-slate-200";
  return (
    <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium border ${classes}`}>
      {STATUS_LABELS[status] || status}
    </span>
  );
}

const DETAIL_FIELDS = [
  ["Amount", (e) => `${e.currency} ${Number(e.amount).toFixed(2)}`],
  ["Spend Date", (e) => e.spend_date],
  ["Category", (e) => e.category],
  ["Description", (e) => e.description || "—"],
  ["Client / Project", (e) => e.client_project || "—"],
  ["Has Invoice", (e) => (e.has_invoice ? "Yes" : "No")],
  ["Supplier GSTIN", (e) => e.supplier_gstin || "—"],
  ["Taxable Value", (e) => (e.taxable_value != null ? e.taxable_value : "—")],
  ["CGST", (e) => (e.cgst != null ? e.cgst : "—")],
  ["SGST", (e) => (e.sgst != null ? e.sgst : "—")],
  ["IGST", (e) => (e.igst != null ? e.igst : "—")],
  ["Invoice Number", (e) => e.invoice_number || "—"],
  ["Payment Method", (e) => e.payment_method || "—"],
  ["Payment Reference", (e) => e.payment_reference || "—"],
  ["Admin Comment", (e) => e.admin_comment || "—"],
];

function ExpenseDetail() {
  const { id } = useParams();
  const { profile, isAdmin } = useCashflowAuth();

  const [expense, setExpense] = useState(null);
  const [attachments, setAttachments] = useState([]);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [actionComment, setActionComment] = useState("");
  const [actingStatus, setActingStatus] = useState("");
  const [actionError, setActionError] = useState("");

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [expenseData, historyData, attachmentRows] = await Promise.all([
        getExpense(id),
        getExpenseHistory(id),
        listAttachments(id),
      ]);
      setExpense(expenseData);
      setHistory(historyData);

      const withUrls = await Promise.all(
        attachmentRows.map(async (attachment) => {
          try {
            const url = await getSignedUrl(attachment.storage_path);
            return { ...attachment, signedUrl: url };
          } catch {
            return { ...attachment, signedUrl: null };
          }
        })
      );
      setAttachments(withUrls);
    } catch (e) {
      setError(e?.message || "Could not load this expense claim.");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  const handleTransition = async (toStatus) => {
    if (!expense) return;
    setActionError("");
    setActingStatus(toStatus);
    try {
      await updateExpenseStatus(expense.id, expense.status, toStatus, actionComment.trim(), profile.id);
      setActionComment("");
      await loadAll();
    } catch (e) {
      setActionError(e?.message || "Could not update status. Please try again.");
    } finally {
      setActingStatus("");
    }
  };

  if (loading) {
    return (
      <div className="bg-surface flex items-center justify-center py-10">
        <p className="text-sm text-muted">Loading claim...</p>
      </div>
    );
  }

  if (error || !expense) {
    return (
      <div className="bg-surface">
        <div className="max-w-2xl mx-auto px-4 sm:px-6 lg:px-8 py-3 sm:py-4">
          <div className="rounded-xl border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800">
            {error || "Expense claim not found."}
          </div>
          <Link to="/cashflow/expense" className="inline-block mt-4 text-sm text-secondary font-medium">
            ← Back to my claims
          </Link>
        </div>
      </div>
    );
  }

  const availableTransitions = VALID_STATUS_TRANSITIONS[expense.status] || [];

  return (
    <div className="bg-surface">
      <section className="py-2 sm:py-3 lg:py-4">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 space-y-6">
          <Link to="/cashflow/expense" className="text-sm text-secondary font-medium">
            ← Back to my claims
          </Link>

          <div className="bg-white rounded-2xl p-6 shadow-sm">
            <div className="flex items-center justify-between gap-4 mb-6">
              <h1 className="text-2xl font-semibold text-primary">Expense Claim</h1>
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={() => downloadExpenseAsXlsx(expense, history, attachments)}
                  className="btn-ui btn-ui-sm btn-ui-success"
                >
                  <FileSpreadsheet className="w-4 h-4" />
                  Excel
                </button>
                <button
                  type="button"
                  onClick={() => downloadExpenseAsPdf(expense, history, attachments)}
                  className="btn-ui btn-ui-sm btn-ui-danger"
                >
                  <Download className="w-4 h-4" />
                  PDF
                </button>
                <StatusBadge status={expense.status} />
              </div>
            </div>

            <dl className="grid sm:grid-cols-2 gap-x-8 gap-y-4">
              {DETAIL_FIELDS.map(([label, getValue]) => (
                <div key={label}>
                  <dt className="text-xs font-semibold uppercase tracking-wider text-slate-400">{label}</dt>
                  <dd className="text-sm text-text mt-0.5">{getValue(expense)}</dd>
                </div>
              ))}
            </dl>
          </div>

          <div className="bg-white rounded-2xl p-6 shadow-sm">
            <h2 className="text-lg font-semibold text-primary mb-4 flex items-center gap-2">
              <Paperclip className="w-4 h-4" /> Attachments
            </h2>
            {attachments.length === 0 && <p className="text-sm text-muted">No receipts attached.</p>}
            <ul className="space-y-2">
              {attachments.map((attachment) => (
                <li key={attachment.id} className="flex items-center gap-2 text-sm">
                  <FileText className="w-4 h-4 text-muted" />
                  {attachment.signedUrl ? (
                    <a
                      href={attachment.signedUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-secondary font-medium hover:underline"
                    >
                      {attachment.file_name}
                    </a>
                  ) : (
                    <span className="text-muted">{attachment.file_name} (link unavailable)</span>
                  )}
                </li>
              ))}
            </ul>
          </div>

          <div className="bg-white rounded-2xl p-6 shadow-sm">
            <h2 className="text-lg font-semibold text-primary mb-4">Status History</h2>
            {history.length === 0 && <p className="text-sm text-muted">No status changes yet.</p>}
            <ul className="space-y-3">
              {history.map((entry) => (
                <li key={entry.id} className="text-sm border-l-2 border-slate-200 pl-3">
                  <p className="text-text">
                    {entry.from_status ? `${STATUS_LABELS[entry.from_status] || entry.from_status} → ` : ""}
                    {STATUS_LABELS[entry.to_status] || entry.to_status}
                  </p>
                  {entry.comment && <p className="text-muted">{entry.comment}</p>}
                  <p className="text-xs text-muted">{entry.changed_at}</p>
                </li>
              ))}
            </ul>
          </div>

          {isAdmin && availableTransitions.length > 0 && (
            <div className="bg-white rounded-2xl p-6 shadow-sm">
              <h2 className="text-lg font-semibold text-primary mb-4">Admin Actions</h2>
              {actionError && (
                <div className="rounded-xl border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800 mb-4">
                  {actionError}
                </div>
              )}
              <label className="block text-sm font-medium text-primary mb-1">Comment (optional)</label>
              <textarea
                rows={2}
                value={actionComment}
                onChange={(e) => setActionComment(e.target.value)}
                className="w-full px-4 py-3 rounded-xl border border-slate-200 focus:border-secondary focus:ring-2 focus:ring-secondary/20 outline-none mb-4"
              />
              <div className="flex flex-wrap gap-3">
                {availableTransitions.map((toStatus) => (
                  <button
                    key={toStatus}
                    type="button"
                    disabled={actingStatus !== ""}
                    onClick={() => handleTransition(toStatus)}
                    className={`btn-ui ${
                      toStatus === "approved" || toStatus === "paid"
                        ? "btn-ui-success"
                        : toStatus === "rejected"
                        ? "btn-ui-danger"
                        : "btn-ui-warning"
                    }`}
                  >
                    {actingStatus === toStatus ? "Saving..." : ACTION_LABELS[toStatus] || toStatus}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

export default ExpenseDetail;
