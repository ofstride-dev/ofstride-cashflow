import React, { useState, useEffect } from 'react';
import { cashflowFetch, parseCashflowResponse } from '../../services/cashflowApi';
import { exportRowsAsCsv } from '../../services/csvExport';
import { useCashflowAuth } from '../../context/CashflowAuthContext';

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

  const headerStyles = {
    headerRow: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '2rem', gap: '1rem', flexWrap: 'wrap' },
    title: { margin: 0, color: '#0f172a', fontSize: '1.75rem', fontWeight: '700', letterSpacing: '-0.025em' },
    metricCard: { padding: '1rem 1.5rem', backgroundColor: '#fff', borderRadius: '12px', boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03)', border: '1px solid #f1f5f9' },
    metricText: { color: '#64748b', fontSize: '0.875rem', fontWeight: '600', textTransform: 'uppercase', letterSpacing: '0.05em', margin: '0 0 0.25rem 0' },
    metricValue: { color: '#0ea5e9', fontSize: '1.5rem', fontWeight: '700', margin: 0 }
  };

  return (
    <div style={{ width: '100%', maxWidth: '1200px', margin: '0 auto', padding: '0.25rem 0.5rem 1.25rem' }}>
      
      <div style={headerStyles.headerRow}>
        <h2 style={headerStyles.title}>Petty Cash</h2>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          <button
            type="button"
            onClick={handleDownloadReport}
            style={{
              border: '1px solid #bfdbfe',
              background: '#eff6ff',
              color: '#1d4ed8',
              fontWeight: 700,
              borderRadius: 10,
              padding: '9px 14px',
              cursor: 'pointer',
            }}
          >
            Download Report
          </button>
          <div style={headerStyles.metricCard}>
            <p style={headerStyles.metricText}>Available Balance</p>
            <p style={headerStyles.metricValue}>₹{balance.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</p>
          </div>
        </div>
      </div>

      {/* Entry Form Container */}
      <div style={{ background: 'linear-gradient(165deg, #ffffff, #f8fbff)', padding: '1.5rem', borderRadius: '14px', border: '1px solid #e2e8f0', marginBottom: '2rem', boxShadow: '0 12px 26px rgba(15,23,42,0.05)' }}>
        <h3 style={{ marginTop: 0, fontSize: '1.1rem', marginBottom: '1rem', color: '#1e293b' }}>New Cash Entry</h3>
        <form onSubmit={handleSubmit} style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '1rem', alignItems: 'end' }}>
          
          <div>
            <label style={{ display: 'block', fontSize: '0.85rem', marginBottom: '0.25rem', color: '#475569', fontWeight: 500 }}>Type</label>
            <select name="type" value={formData.type} onChange={handleInputChange} style={{ width: '100%', padding: '0.6rem', borderRadius: '6px', border: '1px solid #cbd5e1', backgroundColor: '#fff' }}>
              <option value="OUT">Cash Out (Expense)</option>
              <option value="IN">Cash In (Withdrawal)</option>
            </select>
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '0.85rem', marginBottom: '0.25rem', color: '#475569', fontWeight: 500 }}>Date</label>
            <input type="date" name="date" value={formData.date} onChange={handleInputChange} required style={{ width: '100%', padding: '0.6rem', borderRadius: '6px', border: '1px solid #cbd5e1' }} />
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '0.85rem', marginBottom: '0.25rem', color: '#475569', fontWeight: 500 }}>Amount (₹)</label>
            <input type="number" name="amount" value={formData.amount} onChange={handleInputChange} required min="1" placeholder="e.g. 500" style={{ width: '100%', padding: '0.6rem', borderRadius: '6px', border: '1px solid #cbd5e1' }} />
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '0.85rem', marginBottom: '0.25rem', color: '#475569', fontWeight: 500 }}>Description</label>
            <input type="text" name="description" value={formData.description} onChange={handleInputChange} required placeholder="e.g. Office snacks" style={{ width: '100%', padding: '0.6rem', borderRadius: '6px', border: '1px solid #cbd5e1' }} />
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '0.85rem', marginBottom: '0.25rem', color: '#475569', fontWeight: 500 }}>Category (Optional)</label>
            <input type="text" name="category" value={formData.category} onChange={handleInputChange} placeholder="Leave blank for AI" style={{ width: '100%', padding: '0.6rem', borderRadius: '6px', border: '1px solid #cbd5e1' }} />
          </div>

          <button type="submit" disabled={saving} style={{ padding: '0.65rem 1.25rem', backgroundColor: '#2563eb', color: '#fff', border: 'none', borderRadius: '6px', cursor: 'pointer', fontWeight: 600, height: '42px' }}>
            {saving ? 'Saving...' : 'Log Entry'}
          </button>
        </form>
      </div>

      {/* Ledger Table */}
      <div style={{ backgroundColor: '#fff', borderRadius: '14px', border: '1px solid #e2e8f0', overflowX: 'auto', boxShadow: '0 12px 26px rgba(15,23,42,0.05)' }}>
        {loading ? (
          <div style={{ padding: '2rem', textAlign: 'center', color: '#64748b' }}>Loading ledger entries...</div>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
            <thead style={{ backgroundColor: '#f8fafc', borderBottom: '1px solid #e2e8f0' }}>
              <tr>
                <th style={{ padding: '0.85rem 1rem', color: '#475569', fontWeight: 600 }}>Date</th>
                <th style={{ padding: '0.85rem 1rem', color: '#475569', fontWeight: 600 }}>Description</th>
                <th style={{ padding: '0.85rem 1rem', color: '#475569', fontWeight: 600 }}>Category</th>
                <th style={{ padding: '0.85rem 1rem', color: '#475569', fontWeight: 600 }}>Cash In</th>
                <th style={{ padding: '0.85rem 1rem', color: '#475569', fontWeight: 600 }}>Cash Out</th>
                <th style={{ padding: '0.85rem 1rem', color: '#475569', fontWeight: 600 }}>Status</th>
                <th style={{ padding: '0.85rem 1rem', color: '#475569', fontWeight: 600 }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => (
                <tr key={entry.id} style={{ borderBottom: '1px solid #e2e8f0' }}>
                  <td style={{ padding: '0.85rem 1rem', whiteSpace: 'nowrap' }}>{entry.entry_date}</td>
                  <td style={{ padding: '0.85rem 1rem' }}>{entry.description}</td>
                  <td style={{ padding: '0.85rem 1rem' }}>
                    <span style={{ 
                      backgroundColor: entry.auto_categorized ? '#eff6ff' : '#f1f5f9', 
                      color: entry.auto_categorized ? '#1d4ed8' : '#334155',
                      padding: '0.25rem 0.5rem', 
                      borderRadius: '4px', 
                      fontSize: '0.85rem',
                      fontWeight: 500
                    }}>
                      {entry.category} {entry.auto_categorized ? '✨ (AI)' : ''}
                    </span>
                  </td>
                  <td style={{ padding: '0.85rem 1rem', color: '#16a34a', fontWeight: 600 }}>
                    {parseFloat(entry.cash_in) > 0 ? `₹${parseFloat(entry.cash_in).toLocaleString('en-IN')}` : '-'}
                  </td>
                  <td style={{ padding: '0.85rem 1rem', color: '#dc2626', fontWeight: 600 }}>
                    {parseFloat(entry.cash_out) > 0 ? `₹${parseFloat(entry.cash_out).toLocaleString('en-IN')}` : '-'}
                  </td>
                  <td style={{ padding: '0.85rem 1rem' }}>
                    <span
                      style={{
                        backgroundColor: String(entry.status || 'pending') === 'approved' ? '#dcfce7' : '#fef3c7',
                        color: String(entry.status || 'pending') === 'approved' ? '#166534' : '#92400e',
                        padding: '0.25rem 0.5rem',
                        borderRadius: '4px',
                        fontSize: '0.8rem',
                        fontWeight: 600,
                        textTransform: 'capitalize',
                      }}
                    >
                      {String(entry.status || 'pending')}
                    </span>
                  </td>
                  <td style={{ padding: '0.85rem 1rem' }}>
                    {String(entry.status || 'pending') === 'pending' && isAdmin ? (
                      <button
                        type="button"
                        onClick={() => handleApproveEntry(entry.id)}
                        disabled={approvingId === entry.id}
                        style={{
                          border: 'none',
                          borderRadius: 8,
                          padding: '8px 12px',
                          fontWeight: 700,
                          cursor: approvingId === entry.id ? 'not-allowed' : 'pointer',
                          background: approvingId === entry.id ? '#94a3b8' : '#2563eb',
                          color: '#fff',
                        }}
                      >
                        {approvingId === entry.id ? 'Approving...' : 'Approve'}
                      </button>
                    ) : (
                      <span style={{ color: '#64748b', fontSize: 13 }}>-</span>
                    )}
                  </td>
                </tr>
              ))}
              {entries.length === 0 && (
                <tr>
                  <td colSpan="7" style={{ padding: '2rem', textAlign: 'center', color: '#64748b' }}>
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