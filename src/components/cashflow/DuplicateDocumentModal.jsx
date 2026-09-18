import { AlertTriangle, ExternalLink, X } from 'lucide-react';

function money(value) {
  return `₹${Number(value || 0).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;
}

export default function DuplicateDocumentModal({ duplicate, onClose, onViewExisting, onForceSave, saving = false }) {
  if (!duplicate) return null;
  const existing = duplicate.existing || {};
  const party = existing.cashflow_entities?.name || duplicate.partyName || 'the same party';
  const number = existing.bill_number || existing.invoice_number;
  const amount = duplicate.kind === 'bill'
    ? Number(existing.amount || 0)
    : Number(existing.amount || 0) + Number(existing.gst_amount || 0);
  const date = existing.bill_date || existing.invoice_date || 'the same date';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4" role="dialog" aria-modal="true" aria-labelledby="duplicate-document-title">
      <div className="card-ui w-full max-w-lg p-6">
        <div className="flex items-start justify-between gap-4">
          <div className="flex gap-3">
            <AlertTriangle className="mt-0.5 h-6 w-6 shrink-0 text-amber-500" />
            <div>
              <h2 id="duplicate-document-title" className="text-lg font-semibold text-primary">Potential Duplicate Detected</h2>
              <p className="mt-2 text-sm leading-6 text-slate-700">
                A {duplicate.kind === 'invoice' ? 'invoice' : 'bill'} for <strong>{money(amount)}</strong> from <strong>{party}</strong> on <strong>{date}</strong> already exists{number ? ` as ${number}` : ''}.
              </p>
            </div>
          </div>
          <button type="button" onClick={onClose} aria-label="Close duplicate warning" className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100"><X className="h-4 w-4" /></button>
        </div>
        <div className="mt-5 flex flex-wrap justify-end gap-2">
          <button type="button" onClick={onViewExisting} className="btn-ui btn-ui-neutral"><ExternalLink className="h-4 w-4" />View Existing</button>
          <button type="button" onClick={onForceSave} disabled={saving} className="btn-ui btn-ui-primary">{saving ? 'Saving…' : 'Force Save'}</button>
        </div>
      </div>
    </div>
  );
}
