import { AlertTriangle, X } from 'lucide-react';
import { useState } from 'react';

const REASONS = ['Duplicate Entry', 'Incorrect Billing Amount / Tax Rate', 'Order Cancelled by Customer', 'Other'];

export default function AdminMutationModal({ action, documentLabel, onClose, onConfirm, busy = false }) {
  const [reason, setReason] = useState('');
  const [comment, setComment] = useState('');
  const isOther = reason === 'Other';
  const valid = Boolean(reason) && (!isOther || comment.trim());
  const verb = action === 'void' ? 'Void' : 'Delete';

  if (!action) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4" role="dialog" aria-modal="true" aria-labelledby="admin-mutation-title">
      <div className="card-ui w-full max-w-lg p-6">
        <div className="flex items-start justify-between gap-4"><div className="flex gap-3"><AlertTriangle className="mt-0.5 h-6 w-6 shrink-0 text-amber-500" /><div><h2 id="admin-mutation-title" className="text-lg font-semibold text-primary">{verb} {documentLabel}?</h2><p className="mt-2 text-sm leading-6 text-slate-700">Voiding this transaction will update your Accounts Payable/Receivable aging metrics and Cash Runway models.</p></div></div><button type="button" onClick={onClose} aria-label="Close confirmation" className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100"><X className="h-4 w-4" /></button></div>
        <label className="label-ui mt-5" htmlFor="admin-mutation-reason">Reason *</label>
        <select id="admin-mutation-reason" value={reason} onChange={(event) => setReason(event.target.value)} className="input-ui mt-1 bg-white"><option value="">Select a reason</option>{REASONS.map((item) => <option key={item} value={item}>{item}{item === 'Other' ? ' (requires comment)' : ''}</option>)}</select>
        {isOther && <textarea value={comment} onChange={(event) => setComment(event.target.value)} placeholder="Enter the reason" className="input-ui mt-3 min-h-24" required />}
        <div className="mt-5 flex justify-end gap-2"><button type="button" onClick={onClose} className="btn-ui btn-ui-neutral">Cancel</button><button type="button" disabled={!valid || busy} onClick={() => onConfirm({ reason, comment: comment.trim() })} className="btn-ui btn-ui-danger">{busy ? `${verb}ing…` : `${verb} ${documentLabel}`}</button></div>
      </div>
    </div>
  );
}
