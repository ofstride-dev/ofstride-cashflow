import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useParams } from "react-router-dom";
import { UploadCloud, ChevronDown, Trash2 } from "lucide-react";
import { useCashflowAuth } from "../../context/CashflowAuthContext";
import { createExpense, getExpense, updateExpenseClaim, deleteExpense, EXPENSE_CATEGORIES } from "../../services/expenseService";
import { extractReceiptData, uploadReceipt } from "../../services/attachmentService";

const MAX_RECEIPT_SIZE = 10 * 1024 * 1024; // 10 MB before compression
const ALLOWED_TYPES = ["image/jpeg", "image/png", "image/webp", "application/pdf"];

const inputClass =
  "w-full px-4 py-3 rounded-xl border border-slate-200 focus:border-secondary focus:ring-2 focus:ring-secondary/20 outline-none";

function SubmitExpense() {
  const { user, profile } = useCashflowAuth();
  const navigate = useNavigate();
  const { id } = useParams();
  const isEditing = Boolean(id);

  const [formData, setFormData] = useState({
    amount: "",
    spend_date: "",
    category: EXPENSE_CATEGORIES[0],
    description: "",
    client_project: "",
    has_invoice: false,
    // GST / invoice fields — only relevant when has_invoice is true
    supplier_gstin: "",
    invoice_number: "",
    taxable_value: "",
    cgst: "",
    sgst: "",
    igst: "",
  });
  const [receiptFile, setReceiptFile] = useState(null);
  const [submitError, setSubmitError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [loadingClaim, setLoadingClaim] = useState(isEditing);
  const [deleting, setDeleting] = useState(false);
  const [editableClaim, setEditableClaim] = useState(false);

  useEffect(() => {
    if (!id) return;
    getExpense(id).then((claim) => {
      if (claim.user_id !== user?.id || !["draft", "pending", "submitted"].includes(String(claim.status || "").toLowerCase())) {
        setSubmitError("This claim can no longer be edited.");
        return;
      }
      setEditableClaim(true);
      setFormData((previous) => ({ ...previous, ...Object.fromEntries(Object.keys(previous).map((key) => [key, claim[key] ?? previous[key]])) }));
    }).catch((error) => setSubmitError(error?.message || "Could not load this claim."))
      .finally(() => setLoadingClaim(false));
  }, [id, user?.id]);

  const handleDelete = async () => {
    if (!editableClaim || !window.confirm("Are you sure you want to delete this claim? This action cannot be undone.")) return;
    setDeleting(true);
    setSubmitError("");
    try {
      await deleteExpense(id);
      navigate("/cashflow/expense");
    } catch (error) {
      setSubmitError(error?.message || "Could not delete this claim.");
      setDeleting(false);
    }
  };

  const handleChange = (event) => {
    const { name, value, type, checked } = event.target;
    setFormData((prev) => {
      const next = { ...prev, [name]: type === "checkbox" ? checked : value };
      // When the invoice checkbox is turned off, clear the GST fields so we
      // never submit stale invoice data for a non-invoiced expense.
      if (name === "has_invoice" && !checked) {
        next.supplier_gstin = "";
        next.invoice_number = "";
        next.taxable_value = "";
        next.cgst = "";
        next.sgst = "";
        next.igst = "";
      }
      return next;
    });
  };

  const handleFileChange = (event) => {
    const file = event.target.files?.[0] ?? null;
    setSubmitError("");
    if (!file) {
      setReceiptFile(null);
      return;
    }
    if (!ALLOWED_TYPES.includes(file.type)) {
      setSubmitError("Only JPG, PNG, WEBP, or PDF receipts are allowed.");
      setReceiptFile(null);
      return;
    }
    if (file.size <= 0 || file.size > MAX_RECEIPT_SIZE) {
      setSubmitError("Receipt file must be under 10 MB.");
      setReceiptFile(null);
      return;
    }
    setReceiptFile(file);
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setSubmitError("");

    if (!user?.id) {
      setSubmitError("Your session has expired. Please sign in again.");
      return;
    }
    if (!formData.amount && !receiptFile) {
      setSubmitError("Please enter a valid amount.");
      return;
    }
    if (!formData.spend_date && !receiptFile) {
      setSubmitError("Please select the spend date.");
      return;
    }
    if (!formData.description.trim() && !receiptFile) {
      setSubmitError("Please add a short description for this expense.");
      return;
    }

    const companyId = profile?.company_id;
    if (!companyId) {
      alert("Complete workspace onboarding before submitting expenses.");
      return;
    }

    try {
      setSubmitting(true);

      const receiptData = receiptFile ? await extractReceiptData(receiptFile) : {};
      const amount = Number(formData.amount || receiptData.amount || 0);
      const spendDate = formData.spend_date || receiptData.bill_date || "";
      const description = formData.description.trim() || receiptData.vendor_name || "Receipt expense";
      if (amount <= 0 || !spendDate) {
        throw new Error("Azure Document Intelligence could not extract a valid amount and date from the receipt.");
      }

      const payload = {
        user_id: user.id,
        company_id: companyId,
        amount,
        currency: "INR",
        spend_date: spendDate,
        category: formData.category,
        description,
        client_project: formData.client_project.trim() || null,
        has_invoice: formData.has_invoice,
      };

      // Only include GST/invoice fields when the user said they have an invoice.
      if (formData.has_invoice) {
        payload.supplier_gstin = formData.supplier_gstin.trim() || receiptData.vendor_gstin || null;
        payload.invoice_number = formData.invoice_number.trim() || receiptData.bill_number || null;
        payload.taxable_value = formData.taxable_value ? Number(formData.taxable_value) : Number(receiptData.amount_before_gst || 0) || null;
        payload.cgst = formData.cgst ? Number(formData.cgst) : null;
        payload.sgst = formData.sgst ? Number(formData.sgst) : null;
        payload.igst = formData.igst ? Number(formData.igst) : Number(receiptData.gst_amount || 0) || null;
      } else {
        payload.supplier_gstin = null;
        payload.invoice_number = null;
        payload.taxable_value = null;
        payload.cgst = null;
        payload.sgst = null;
        payload.igst = null;
      }

      const expense = isEditing ? await updateExpenseClaim(id, payload) : await createExpense(payload);

      if (receiptFile) {
        await uploadReceipt(receiptFile, user.id, expense.id, companyId);
      }

      navigate(`/cashflow/expense/${expense?.id || id}`);
    } catch (error) {
      setSubmitError(error?.message || "Submission failed. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="bg-surface">
      <section className="py-2 sm:py-3 lg:py-4">
        <div className="max-w-2xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="mb-6 flex items-center justify-between gap-4">
            <h1 className="text-2xl font-semibold text-primary">{isEditing ? "Edit Expense Claim" : "Submit Expense Claim"}</h1>
            {isEditing && editableClaim && (
              <button type="button" onClick={handleDelete} disabled={deleting || submitting} className="btn-ui btn-ui-danger">
                <Trash2 className="w-4 h-4" />
                {deleting ? "Deleting..." : "Delete"}
              </button>
            )}
          </div>

          {loadingClaim && <p className="text-sm text-muted mb-4">Loading claim...</p>}

          <div className="bg-white rounded-2xl p-6 shadow-sm">
            {submitError && (
              <div className="rounded-xl border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800 mb-5">
                {submitError}
              </div>
            )}

            <form className="space-y-5" onSubmit={handleSubmit}>
              <div className="grid sm:grid-cols-2 gap-5">
                <div>
                  <label className="block text-sm font-medium text-primary mb-1">Amount (INR) *</label>
                  <input
                    name="amount"
                    type="number"
                    step="0.01"
                    min="0"
                    required
                    value={formData.amount}
                    onChange={handleChange}
                    className={inputClass}
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-primary mb-1">Spend Date *</label>
                  <input
                    name="spend_date"
                    type="date"
                    required
                    value={formData.spend_date}
                    onChange={handleChange}
                    className={inputClass}
                  />
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-primary mb-1">Category *</label>
                <select
                  name="category"
                  required
                  value={formData.category}
                  onChange={handleChange}
                  className={`${inputClass} bg-white`}
                >
                  {EXPENSE_CATEGORIES.map((category) => (
                    <option key={category} value={category}>
                      {category}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-primary mb-1">Description *</label>
                <textarea
                  name="description"
                  rows={3}
                  required
                  value={formData.description}
                  onChange={handleChange}
                  className={inputClass}
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-primary mb-1">Client / Project</label>
                <input
                  name="client_project"
                  type="text"
                  value={formData.client_project}
                  onChange={handleChange}
                  className={inputClass}
                />
              </div>

              {/* Invoice / GST section — only visible when the user has an invoice */}
              <div className="rounded-xl border border-slate-200 overflow-hidden">
                <label className="flex items-center gap-3 text-sm text-text px-4 py-3 cursor-pointer select-none hover:bg-surface transition-colors">
                  <input
                    type="checkbox"
                    name="has_invoice"
                    checked={formData.has_invoice}
                    onChange={handleChange}
                    className="mt-0"
                  />
                  <span className="font-medium text-primary">I have an invoice for this expense</span>
                  <ChevronDown
                    className={`w-4 h-4 ml-auto text-muted transition-transform duration-200 ${
                      formData.has_invoice ? "rotate-180" : ""
                    }`}
                  />
                </label>

                {formData.has_invoice && (
                  <div className="px-4 pb-4 pt-2 space-y-5 border-t border-slate-200 bg-slate-50/50">
                    <p className="text-xs text-muted">
                      Fill in the supplier GST details from your invoice. CGST/SGST apply for
                      intra-state supplies; IGST applies for inter-state.
                    </p>

                    <div className="grid sm:grid-cols-2 gap-5">
                      <div>
                        <label className="block text-sm font-medium text-primary mb-1">
                          Supplier GSTIN
                        </label>
                        <input
                          name="supplier_gstin"
                          type="text"
                          value={formData.supplier_gstin}
                          onChange={handleChange}
                          placeholder="15-digit GSTIN"
                          className={inputClass}
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-primary mb-1">
                          Invoice Number
                        </label>
                        <input
                          name="invoice_number"
                          type="text"
                          value={formData.invoice_number}
                          onChange={handleChange}
                          className={inputClass}
                        />
                      </div>
                    </div>

                    <div>
                      <label className="block text-sm font-medium text-primary mb-1">
                        Taxable Value (INR)
                      </label>
                      <input
                        name="taxable_value"
                        type="number"
                        step="0.01"
                        min="0"
                        value={formData.taxable_value}
                        onChange={handleChange}
                        className={inputClass}
                      />
                    </div>

                    <div className="grid sm:grid-cols-3 gap-5">
                      <div>
                        <label className="block text-sm font-medium text-primary mb-1">CGST (INR)</label>
                        <input
                          name="cgst"
                          type="number"
                          step="0.01"
                          min="0"
                          value={formData.cgst}
                          onChange={handleChange}
                          className={inputClass}
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-primary mb-1">SGST (INR)</label>
                        <input
                          name="sgst"
                          type="number"
                          step="0.01"
                          min="0"
                          value={formData.sgst}
                          onChange={handleChange}
                          className={inputClass}
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-primary mb-1">IGST (INR)</label>
                        <input
                          name="igst"
                          type="number"
                          step="0.01"
                          min="0"
                          value={formData.igst}
                          onChange={handleChange}
                          className={inputClass}
                        />
                      </div>
                    </div>
                  </div>
                )}
              </div>

              <div>
                <label className="block text-sm font-medium text-primary mb-1 flex items-center gap-2">
                  <UploadCloud className="w-4 h-4" /> Receipt
                </label>
                <input
                  type="file"
                  accept="image/jpeg,image/png,image/webp,application/pdf"
                  onChange={handleFileChange}
                  className="w-full px-4 py-3 rounded-xl border border-slate-200 bg-white"
                />
                <p className="text-xs text-muted mt-2">
                  JPG, PNG, WEBP, or PDF. Images are compressed automatically.
                </p>
              </div>

              <button
                type="submit"
                disabled={submitting}
                className="w-full btn-ui btn-ui-primary"
              >
                {submitting ? "Submitting..." : "Submit Claim"}
              </button>
            </form>
          </div>
        </div>
      </section>
    </div>
  );
}

export default SubmitExpense;