import { useState } from "react";

export default function CollectAmountModal({
  open,
  onClose,
  onConfirm,
  documentLabel = "Invoice",
  documentNumber,
  grossAmount,
  remainingBalance,
  title = "Collect Payment",
}) {
  const [value, setValue] = useState("");

  if (!open) return null;

  const remaining = Number(remainingBalance);
  const amount = Number(value);
  const error = !value
    ? "Enter an amount to continue."
    : !Number.isFinite(amount) || amount <= 0
      ? "Amount must be greater than 0."
      : amount > remaining
        ? `Amount cannot exceed the remaining balance of ₹${remaining.toFixed(2)}.`
        : "";

  const submit = (event) => {
    event.preventDefault();
    if (error) return;
    onConfirm(amount);
  };

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-slate-950/50 px-4 py-6" role="presentation">
      <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl" role="dialog" aria-modal="true" aria-labelledby="collect-modal-title">
        <h2 id="collect-modal-title" className="text-xl font-semibold text-primary">{title}</h2>
        <p className="mt-2 text-sm text-muted">
          {documentLabel} <strong className="text-primary">{documentNumber || "—"}</strong> · Gross amount due <strong className="text-primary">₹{Number(grossAmount).toFixed(2)}</strong>
        </p>
        <p className="mt-1 text-sm text-muted">Remaining balance: ₹{remaining.toFixed(2)}</p>
        <form onSubmit={submit} className="mt-5 space-y-4">
          <div>
            <label htmlFor="collect-amount" className="mb-1 block text-sm font-medium text-primary">Amount to Collect</label>
            <input
              id="collect-amount"
              type="number"
              inputMode="decimal"
              min="0.01"
              max={remaining}
              step="0.01"
              value={value}
              onChange={(event) => setValue(event.target.value.replace(/[^0-9.]/g, "").replace(/(\..*)\./g, "$1"))}
              className="input-ui w-full"
              autoFocus
              aria-invalid={Boolean(error)}
              aria-describedby="collect-amount-error"
            />
            <p id="collect-amount-error" className="mt-1 min-h-5 text-sm text-red-700" role="alert">{error}</p>
          </div>
          <div className="flex justify-end gap-3">
            <button type="button" onClick={onClose} className="btn-ui btn-ui-neutral">Cancel</button>
            <button type="submit" disabled={Boolean(error)} className="btn-ui btn-ui-primary">Collect</button>
          </div>
        </form>
      </div>
    </div>
  );
}