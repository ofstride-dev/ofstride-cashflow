// PettyCash.jsx
// NOTE: Business logic (ledger fetch, entry submit, approval, CSV export) is
// unchanged from the original implementation. Only the presentation layer
// has been restyled onto the shared design system.

import { useState, useEffect } from 'react';
import { Download, Sparkles } from 'lucide-react';
import { cashflowFetch, parseCashflowResponse } from '../../services/cashflowApi';
import { exportRowsAsCsv } from '../../services/csvExport';
import { useCashflowAuth } from '../../context/CashflowAuthContext';

function TableSkeleton() {
  return (
    <div className="p-6 space-y-3" aria-busy="true" aria-live="polite">
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} className="skeleton-ui h-12" />
      ))}
      <span className="sr-only">Loading petty cash ledger…</span>
    </div>
  );
}

export default function PettyCash() {
  const { isAdmin, session, profile } = useCashflowAuth();
  const authIdentityKey = `${session?.user?.id || ''}:${profile?.company_id || ''}`;
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [approvingId, setApprovingId] = useState('');
  
  // Form State
  const [formData, setFormData] = useState({
    date: new Date().toISOString().split('T')[0],
    amount: '',
    type: 'OUT',
    description: '',
    category: ''
  });

  useEffect(() => {
    let isCurrent = true;
    setEntries([]);
    setLoading(true);

    fetchLedger(() => isCurrent);

    return () => {
      isCurrent = false;
    };
  }, [authIdentityKey]);

  const fetchLedger = async (isRequestCurrent = () => true) => {
    try {
      const res = await cashflowFetch('/cashflow/pettycash');
      const parsed = await parseCashflowResponse(res);
      if (!isRequestCurrent()) return;
      if (parsed.ok) setEntries(parsed.data || []);
      else throw new Error(parsed.error || `Server returned ${parsed.status}`);
    } catch (err) {
      if (isRequestCurrent()) console.error("Failed to fetch ledger", err);
    } finally {
      if (isRequestCurrent()) setLoading(false);
    }
  };

  const handleInputChange = (e) => {
    setFormData({ ...formData, [e.target.name]: e.target.value });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const res = await cashflowFetch('/cashflow/pettycash', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData)
      });
      const parsed = await parseCashflowResponse(res);
      if (parsed.ok) {
        setEntries([parsed.data, ...entries]); // Add new entry to top of list
        setFormData({ ...formData, amount: '', description: '', category: '' }); // Reset form
      } else {
        throw new Error(parsed.error || `Server returned ${parsed.status}`);
      }
    } catch (err) {
      console.error("Failed to save entry", err);
    } finally {
      setSaving(false);
    }
  };

  const handleApproveEntry = async (entryId) => {
    if (!entryId) return;
    setApprovingId(entryId);
    try {
      const res = await cashflowFetch('/cashflow/pettycash/approve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ entry_id: entryId }),
      });
      const parsed = await parseCashflowResponse(res);
      if (parsed.ok && parsed.data) {
        setEntries((prev) => prev.map((entry) => (entry.id === entryId ? parsed.data : entry)));
      } else {
        throw new Error(parsed.error || `Server returned ${parsed.status}`);
      }
    } catch (err) {
      console.error("Failed to approve petty cash entry", err);
      alert("Failed to approve entry.");
    } finally {
      setApprovingId('');
    }
  };

  const handleDownloadReport = () => {
    const now = new Date().toISOString().slice(0, 10);
    const rows = (entries || []).map((entry) => {
      const cashIn = Number(entry.cash_in || 0);
      const cashOut = Number(entry.cash_out || 0);
      return {
        entry_date: entry.entry_date || '',
        description: entry.description || '',
        category: entry.category || '',
        auto_categorized: entry.auto_categorized ? 'Yes' : 'No',
        cash_in: cashIn.toFixed(2),
        cash_out: cashOut.toFixed(2),
        net_movement: (cashIn - cashOut).toFixed(2),
        status: entry.status || 'pending',
      };
    });

    exportRowsAsCsv(
      `petty_cash_report_${now}.csv`,
      [
        { header: 'Entry Date', key: 'entry_date' },
        { header: 'Description', key: 'description' },
        { header: 'Category', key: 'category' },
        { header: 'Auto Categorized', key: 'auto_categorized' },
        { header: 'Cash In', key: 'cash_in' },
        { header: 'Cash Out', key: 'cash_out' },
        { header: 'Net Movement', key: 'net_movement' },
        { header: 'Status', key: 'status' },
      ],
      rows
    );
  };

  // Calculate Balance safely using exact DB columns (cash_in - cash_out)
  const balance = entries.reduce((acc, curr) => {
    const cashIn = parseFloat(curr.cash_in || 0);
    const cashOut = parseFloat(curr.cash_out || 0);
    return acc + cashIn - cashOut;
  }, 0);

  return (
    <div className="max-w-6xl mx-auto">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <h2 className="text-2xl font-bold text-primary sm:text-[1.75rem]">Petty Cash</h2>
        <div className="flex flex-wrap items-center justify-end gap-3">
          <button type="button" onClick={handleDownloadReport} className="btn-ui btn-ui-info">
            <Download className="h-4 w-4" />
            Download Report
          </button>
          <div className="rounded-2xl border border-slate-100 bg-white px-6 py-4 shadow-card">
            <p className="text-xs font-bold uppercase tracking-wider text-muted">Available Balance</p>
            <p className="mt-0.5 text-2xl font-bold text-info tabular-nums">
              ₹{balance.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
            </p>
          </div>
        </div>
      </div>

      <div className="card-ui mb-8 bg-gradient-to-br from-white to-sky-50/60 p-6">
        <h3 className="mb-4 text-lg font-semibold text-primary">New Cash Entry</h3>
        <form onSubmit={handleSubmit} className="grid items-end gap-4" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))' }}>
          <div>
            <label className="label-ui" htmlFor="pc-type">Type</label>
            <select id="pc-type" name="type" value={formData.type} onChange={handleInputChange} className="input-ui bg-white">
              <option value="OUT">Cash Out (Expense)</option>
              <option value="IN">Cash In (Deposit)</option>
            </select>
          </div>

          <div>
            <label className="label-ui" htmlFor="pc-date">Date</label>
            <input id="pc-date" type="date" name="date" value={formData.date} onChange={handleInputChange} required className="input-ui" />
          </div>

          <div>
            <label className="label-ui" htmlFor="pc-amount">Amount (₹)</label>
            <input id="pc-amount" type="number" name="amount" value={formData.amount} onChange={handleInputChange} required min="1" placeholder="e.g. 500" className="input-ui" />
          </div>

          <div>
            <label className="label-ui" htmlFor="pc-description">Description</label>
            <input id="pc-description" type="text" name="description" value={formData.description} onChange={handleInputChange} required placeholder="e.g. Office snacks" className="input-ui" />
          </div>

          <div>
            <label className="label-ui" htmlFor="pc-category">Category (Optional)</label>
            <input id="pc-category" type="text" name="category" value={formData.category} onChange={handleInputChange} placeholder="Leave blank for AI" className="input-ui" />
          </div>

          <button type="submit" disabled={saving} className="btn-ui btn-ui-primary h-[42px]">
            {saving ? 'Saving...' : 'Log Entry'}
          </button>
        </form>
      </div>

      <div className="scroll-ui overflow-x-auto rounded-2xl border border-slate-200 bg-white shadow-card">
        {loading ? (
          <TableSkeleton />
        ) : (
          <table className="table-ui">
            <thead>
              <tr>
                <th>Date</th>
                <th>Description</th>
                <th>Category</th>
                <th>Cash In</th>
                <th>Cash Out</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => (
                <tr key={entry.id}>
                  <td className="whitespace-nowrap">{entry.entry_date}</td>
                  <td>{entry.description}</td>
                  <td>
                    <span className={`badge-ui ${entry.auto_categorized ? 'badge-ui-info' : 'badge-ui-neutral'}`}>
                      {entry.category} {entry.auto_categorized ? <Sparkles className="h-3 w-3" aria-hidden="true" /> : ''}
                    </span>
                  </td>
                  <td className="font-semibold text-success tabular-nums">
                    {parseFloat(entry.cash_in) > 0 ? `₹${parseFloat(entry.cash_in).toLocaleString('en-IN')}` : '-'}
                  </td>
                  <td className="font-semibold text-danger tabular-nums">
                    {parseFloat(entry.cash_out) > 0 ? `₹${parseFloat(entry.cash_out).toLocaleString('en-IN')}` : '-'}
                  </td>
                  <td>
                    <span className={`badge-ui ${String(entry.status || 'pending') === 'approved' ? 'badge-ui-success' : 'badge-ui-warning'}`}>
                      {String(entry.status || 'pending')}
                    </span>
                  </td>
                  <td>
                    {String(entry.status || 'pending') === 'pending' && isAdmin ? (
                      <button
                        type="button"
                        onClick={() => handleApproveEntry(entry.id)}
                        disabled={approvingId === entry.id}
                        className="btn-ui btn-ui-sm btn-ui-secondary"
                      >
                        {approvingId === entry.id ? 'Approving...' : 'Approve'}
                      </button>
                    ) : (
                      <span className="text-xs text-muted">-</span>
                    )}
                  </td>
                </tr>
              ))}
              {entries.length === 0 && (
                <tr>
                  <td colSpan="7" className="py-10 text-center text-muted">
                    No cash entries recorded yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
