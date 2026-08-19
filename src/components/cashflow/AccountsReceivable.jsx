import React, { useState, useEffect, useRef } from 'react';
import { cashflowFetch, parseCashflowResponse } from '../../services/cashflowApi';
import { exportRowsAsCsv } from '../../services/csvExport';
import { useCashflowAuth } from '../../context/CashflowAuthContext';

export default function AccountsReceivable() {
  const { isAdmin, session, profile } = useCashflowAuth();
  const authIdentityKey = `${session?.user?.id || ''}:${profile?.company_id || ''}`;
  const activeIdentityKeyRef = useRef(authIdentityKey);
  const [invoices, setInvoices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [approvingId, setApprovingId] = useState('');
  
  const [formData, setFormData] = useState({
    customer_name: '', customer_gstin: '', invoice_number: '', 
    invoice_date: new Date().toISOString().split('T')[0], 
    amount: '', gst_amount: '', irn_number: '', is_proforma: false, notes: '', item_services: ['']
  });

  const normalizeItemServices = (value) => {
    if (Array.isArray(value)) return value.map((v) => String(v || '').trim()).filter(Boolean);
    if (typeof value === 'string') return value.split('\n').map((v) => v.trim()).filter(Boolean);
    return [];
  };

  const parseItemsFromNotes = (notes) => {
    const text = String(notes || '');
    const marker = 'Items/Services:';
    const markerIndex = text.indexOf(marker);
    if (markerIndex === -1) return [];
    const block = text.slice(markerIndex + marker.length);
    return block
      .split('\n')
      .map((line) => line.replace(/^[-•]\s*/, '').trim())
      .filter(Boolean);
  };

  const getInvoiceItems = (invoice) => {
    const direct = normalizeItemServices(invoice?.item_services);
    if (direct.length) return direct;
    return parseItemsFromNotes(invoice?.notes);
  };

  const downloadInvoice = (invoice) => {
    const subtotal = Number(invoice?.amount || 0);
    const gst = Number(invoice?.gst_amount || 0);
    const total = subtotal + gst;
    const items = getInvoiceItems(invoice);
    const customer = invoice?.cashflow_entities?.name || 'N/A';

    const html = `<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>Invoice ${invoice?.invoice_number || ''}</title>
    <style>
      body { font-family: Arial, sans-serif; margin: 24px; color: #0f172a; }
      h1 { margin: 0 0 8px 0; }
      .muted { color: #64748b; font-size: 12px; }
      table { width: 100%; border-collapse: collapse; margin-top: 16px; }
      th, td { border: 1px solid #e2e8f0; padding: 8px; text-align: left; }
      th { background: #f8fafc; }
    </style>
  </head>
  <body>
    <h1>Invoice ${invoice?.invoice_number || ''}</h1>
    <div class="muted">Date: ${invoice?.invoice_date || ''}</div>
    <div class="muted">Customer: ${customer}</div>
    <div class="muted">Customer GSTIN: ${invoice?.cashflow_entities?.gstin || ''}</div>

    <table>
      <thead>
        <tr>
          <th>Item / Service</th>
        </tr>
      </thead>
      <tbody>
        ${(items.length ? items : ['General Service']).map((item) => `<tr><td>${item}</td></tr>`).join('')}
      </tbody>
    </table>

    <table>
      <tbody>
        <tr><th>Subtotal (Before GST)</th><td>₹${subtotal.toFixed(2)}</td></tr>
        <tr><th>GST</th><td>₹${gst.toFixed(2)}</td></tr>
        <tr><th>Total</th><td><strong>₹${total.toFixed(2)}</strong></td></tr>
      </tbody>
    </table>
  </body>
</html>`;

    const blob = new Blob([html], { type: 'text/html;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${invoice?.invoice_number || 'invoice'}.html`;
    a.click();
    URL.revokeObjectURL(url);
  };

  useEffect(() => {
    let isCurrent = true;
    activeIdentityKeyRef.current = authIdentityKey;
    setInvoices([]);
    setLoading(true);
    fetchInvoices(() => isCurrent);

    return () => {
      isCurrent = false;
      if (activeIdentityKeyRef.current === authIdentityKey) {
        activeIdentityKeyRef.current = '';
      }
    };
  }, [authIdentityKey]);

  const fetchInvoices = async (isRequestCurrent = () => true) => {
    try {
      const res = await cashflowFetch('/cashflow/ar/list');
      const parsed = await parseCashflowResponse(res);
      if (!isRequestCurrent()) return;
      if (parsed.ok) setInvoices(parsed.data || []);
      else throw new Error(parsed.error || `Server returned ${parsed.status}`);
    } catch (err) {
      if (isRequestCurrent()) console.error("Fetch invoices failed:", err);
    } finally {
      if (isRequestCurrent()) setLoading(false);
    }
  };

  const handleInputChange = (e) => {
    const { name, value, type, checked } = e.target;
    setFormData({ ...formData, [name]: type === 'checkbox' ? checked : value });
  };

  const handleCreateInvoice = async (e) => {
    e.preventDefault();
    const requestIdentityKey = authIdentityKey;
    setSaving(true);
    try {
      const res = await cashflowFetch('/cashflow/ar/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData)
      });
      const parsed = await parseCashflowResponse(res);
      if (activeIdentityKeyRef.current !== requestIdentityKey) return;
      if (parsed.ok) {
        setInvoices((previousInvoices) => [parsed.data, ...previousInvoices]);
        setFormData({ 
          customer_name: '', customer_gstin: '', invoice_number: '', 
          invoice_date: new Date().toISOString().split('T')[0], 
          amount: '', gst_amount: '', irn_number: '', is_proforma: false, notes: '', item_services: ['']
        });
      } else {
        throw new Error(parsed.error || `Server error ${parsed.status}`);
      }
    } catch (err) {
      console.error("Save Failed:", err);
      alert("Failed to create invoice.");
    } finally {
      if (activeIdentityKeyRef.current === requestIdentityKey) setSaving(false);
    }
  };

  const handleRecordPayment = async (invoice) => {
    const paymentAmount = window.prompt(
      `Record payment for ${invoice.invoice_number}\nEnter amount (Total: ₹${(invoice.amount + invoice.gst_amount)}):`, 
      invoice.amount + invoice.gst_amount
    );
    if (!paymentAmount) return;
    const requestIdentityKey = authIdentityKey;

    try {
      const res = await cashflowFetch('/cashflow/ar/collect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          invoice_id: invoice.id,
          amount: parseFloat(paymentAmount),
          payment_mode: 'bank_transfer'
        })
      });
      const parsed = await parseCashflowResponse(res);
      if (activeIdentityKeyRef.current !== requestIdentityKey) return;
      if (parsed.ok) {
        alert("Payment recorded successfully!");
        fetchInvoices(() => activeIdentityKeyRef.current === requestIdentityKey);
      } else {
        throw new Error(parsed.error || `Server error ${parsed.status}`);
      }
    } catch (err) {
      console.error("Payment Failed:", err);
      alert("Failed to record payment.");
    }
  };

  const handleApproveInvoice = async (invoiceId) => {
    if (!invoiceId) return;
    const requestIdentityKey = authIdentityKey;
    setApprovingId(invoiceId);
    try {
      const res = await cashflowFetch('/cashflow/ar/approve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ invoice_id: invoiceId }),
      });
      const parsed = await parseCashflowResponse(res);
      if (activeIdentityKeyRef.current !== requestIdentityKey) return;
      if (parsed.ok && parsed.data) {
        setInvoices((prev) => prev.map((inv) => (inv.id === invoiceId ? parsed.data : inv)));
      } else {
        throw new Error(parsed.error || `Server error ${parsed.status}`);
      }
    } catch (err) {
      console.error("Approve Failed:", err);
      alert("Failed to approve invoice.");
    } finally {
      if (activeIdentityKeyRef.current === requestIdentityKey) setApprovingId('');
    }
  };

  const handleDownloadReport = () => {
    const now = new Date().toISOString().slice(0, 10);
    const rows = (invoices || []).map((inv) => {
      const amount = Number(inv.amount || 0);
      const gst = Number(inv.gst_amount || 0);
      const total = amount + gst;
      return {
        customer: inv.cashflow_entities?.name || 'N/A',
        customer_gstin: inv.cashflow_entities?.gstin || '',
        invoice_number: inv.invoice_number || '',
        invoice_date: inv.invoice_date || '',
        due_date: inv.due_date || '',
        amount: amount.toFixed(2),
        gst_amount: gst.toFixed(2),
        total_invoice_value: total.toFixed(2),
        status: inv.status || '',
        is_proforma: inv.is_proforma ? 'Yes' : 'No',
        irn_number: inv.irn_number || '',
      };
    });

    exportRowsAsCsv(
      `ar_report_${now}.csv`,
      [
        { header: 'Customer', key: 'customer' },
        { header: 'Customer GSTIN', key: 'customer_gstin' },
        { header: 'Invoice Number', key: 'invoice_number' },
        { header: 'Invoice Date', key: 'invoice_date' },
        { header: 'Due Date', key: 'due_date' },
        { header: 'Amount', key: 'amount' },
        { header: 'GST Amount', key: 'gst_amount' },
        { header: 'Total Invoice Value', key: 'total_invoice_value' },
        { header: 'Status', key: 'status' },
        { header: 'Is Proforma', key: 'is_proforma' },
        { header: 'IRN Number', key: 'irn_number' },
      ],
      rows
    );
  };

  const totalOutstanding = invoices
    .filter(inv => inv.status !== 'paid' && !inv.is_proforma)
    .reduce((acc, curr) => acc + (parseFloat(curr.amount || 0) + parseFloat(curr.gst_amount || 0)), 0);

  // --- PREMIUM STYLES ---
  const styles = {
    container: { maxWidth: '1200px', margin: '0 auto', padding: '0.25rem 0.5rem 1.25rem', fontFamily: 'system-ui, -apple-system, sans-serif' },
    headerRow: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '2rem' },
    title: { margin: 0, color: '#0f172a', fontSize: '1.75rem', fontWeight: '700', letterSpacing: '-0.025em' },
    metricCard: { padding: '1rem 1.5rem', background: 'linear-gradient(165deg, #ffffff, #f2f9ff)', borderRadius: '14px', boxShadow: '0 10px 24px rgba(15,23,42,0.06)', border: '1px solid #dbeafe' },
    metricText: { color: '#64748b', fontSize: '0.875rem', fontWeight: '600', textTransform: 'uppercase', letterSpacing: '0.05em', margin: '0 0 0.25rem 0' },
    metricValue: { color: '#0ea5e9', fontSize: '1.5rem', fontWeight: '700', margin: 0 },
    card: { background: 'linear-gradient(165deg, #ffffff, #f8fbff)', padding: '2rem', borderRadius: '16px', boxShadow: '0 12px 28px rgba(15, 23, 42, 0.06)', marginBottom: '2.5rem', border: '1px solid #e2e8f0' },
    cardTitle: { marginTop: 0, fontSize: '1.25rem', color: '#1e293b', fontWeight: '600', marginBottom: '1.5rem' },
    formGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '1.5rem', alignItems: 'end' },
    label: { display: 'block', fontSize: '0.875rem', color: '#475569', fontWeight: '500', marginBottom: '0.5rem' },
    input: { width: '100%', padding: '0.75rem 1rem', borderRadius: '8px', border: '1px solid #e2e8f0', backgroundColor: '#f8fafc', fontSize: '0.95rem', color: '#0f172a', transition: 'border-color 0.15s ease', boxSizing: 'border-box' },
    checkboxLabel: { display: 'flex', alignItems: 'center', fontSize: '0.9rem', color: '#475569', fontWeight: '500', cursor: 'pointer', height: '45px' },
    button: { padding: '0.75rem 1.5rem', backgroundColor: '#0f172a', color: '#fff', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: '600', fontSize: '0.95rem', height: '45px', transition: 'background-color 0.2s', boxShadow: '0 4px 6px -1px rgba(15, 23, 42, 0.2)' },
    tableContainer: { backgroundColor: '#fff', borderRadius: '16px', boxShadow: '0 12px 28px rgba(15, 23, 42, 0.06)', overflow: 'hidden', border: '1px solid #e2e8f0' },
    table: { width: '100%', borderCollapse: 'collapse', textAlign: 'left', whiteSpace: 'nowrap' },
    th: { padding: '1rem 1.5rem', backgroundColor: '#f8fafc', color: '#64748b', fontSize: '0.75rem', fontWeight: '600', textTransform: 'uppercase', letterSpacing: '0.05em', borderBottom: '1px solid #e2e8f0' },
    td: { padding: '1rem 1.5rem', color: '#334155', fontSize: '0.95rem', borderBottom: '1px solid #f1f5f9' },
    badgeProforma: { marginLeft: '8px', fontSize: '0.7rem', backgroundColor: '#fef08a', color: '#854d0e', padding: '0.25rem 0.5rem', borderRadius: '9999px', fontWeight: '600' },
    badgePaid: { backgroundColor: '#dcfce7', color: '#166534', padding: '0.35rem 0.75rem', borderRadius: '9999px', fontSize: '0.8rem', fontWeight: '600', textTransform: 'capitalize' },
    badgePending: { backgroundColor: '#f1f5f9', color: '#475569', padding: '0.35rem 0.75rem', borderRadius: '9999px', fontSize: '0.8rem', fontWeight: '600', textTransform: 'capitalize' },
    actionBtn: { padding: '0.4rem 1rem', backgroundColor: '#f8fafc', color: '#0ea5e9', border: '1px solid #e0f2fe', borderRadius: '6px', cursor: 'pointer', fontSize: '0.85rem', fontWeight: '600' }
  };

  return (
    <div style={styles.container}>
      
      <div style={styles.headerRow}>
        <h2 style={styles.title}>Accounts Receivable</h2>
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
          <div style={styles.metricCard}>
            <p style={styles.metricText}>Total Outstanding</p>
            <p style={styles.metricValue}>₹{totalOutstanding.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</p>
          </div>
        </div>
      </div>

      <div style={styles.card}>
        <h3 style={styles.cardTitle}>Create New Invoice</h3>
        <form onSubmit={handleCreateInvoice} style={styles.formGrid}>
          <div>
            <label style={styles.label}>Customer Name</label>
            <input type="text" name="customer_name" value={formData.customer_name} onChange={handleInputChange} required style={styles.input} />
          </div>
          <div>
            <label style={styles.label}>Invoice #</label>
            <input type="text" name="invoice_number" value={formData.invoice_number} onChange={handleInputChange} placeholder="Auto-generated" style={styles.input} />
          </div>
          <div>
            <label style={styles.label}>Invoice Date</label>
            <input type="date" name="invoice_date" value={formData.invoice_date} onChange={handleInputChange} required style={styles.input} />
          </div>
          <div>
            <label style={styles.label}>Amount (₹)</label>
            <input type="number" name="amount" value={formData.amount} onChange={handleInputChange} required style={styles.input} />
          </div>
          <div>
            <label style={styles.label}>GST Amount (₹)</label>
            <input type="number" name="gst_amount" value={formData.gst_amount} onChange={handleInputChange} style={styles.input} />
          </div>
          <div>
            <label style={styles.label}>IRN Number</label>
            <input type="text" name="irn_number" value={formData.irn_number} onChange={handleInputChange} placeholder="Optional" style={styles.input} />
          </div>
          <div style={{ gridColumn: '1 / -1' }}>
            <label style={styles.label}>Item / Service</label>
            <div style={{ display: 'grid', gap: '0.5rem' }}>
              {formData.item_services.map((item, index) => (
                <div key={`item-${index}`} style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                  <input
                    type="text"
                    value={item}
                    onChange={(e) => {
                      const nextItems = [...formData.item_services];
                      nextItems[index] = e.target.value;
                      setFormData({ ...formData, item_services: nextItems });
                    }}
                    placeholder={`Item/Service ${index + 1}`}
                    style={styles.input}
                  />
                  {formData.item_services.length > 1 && (
                    <button
                      type="button"
                      onClick={() => {
                        const nextItems = formData.item_services.filter((_, idx) => idx !== index);
                        setFormData({ ...formData, item_services: nextItems.length ? nextItems : [''] });
                      }}
                      style={{ ...styles.actionBtn, border: '1px solid #fecaca', color: '#b91c1c' }}
                    >
                      Remove
                    </button>
                  )}
                </div>
              ))}
            </div>
            <button
              type="button"
              onClick={() => setFormData({ ...formData, item_services: [...formData.item_services, ''] })}
              style={{ ...styles.actionBtn, marginTop: '0.6rem' }}
            >
              Add Another Item
            </button>
          </div>
          <div style={styles.checkboxLabel}>
            <label style={{ display: 'flex', alignItems: 'center', cursor: 'pointer' }}>
              <input type="checkbox" name="is_proforma" checked={formData.is_proforma} onChange={handleInputChange} style={{ marginRight: '0.75rem', width: '18px', height: '18px' }} />
              Is Proforma Invoice?
            </label>
          </div>
          <button type="submit" disabled={saving} style={styles.button}>
            {saving ? 'Creating...' : 'Create Invoice'}
          </button>
        </form>
      </div>

      <div style={styles.tableContainer}>
        <table style={styles.table}>
          <thead>
            <tr>
              <th style={styles.th}>Customer</th>
              <th style={styles.th}>Invoice #</th>
              <th style={styles.th}>Date</th>
              <th style={styles.th}>Amount</th>
              <th style={styles.th}>Total (w/ GST)</th>
              <th style={styles.th}>Status</th>
              <th style={styles.th}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {invoices.map((inv) => {
              const total = parseFloat(inv.amount || 0) + parseFloat(inv.gst_amount || 0);
              
              return (
                <tr key={inv.id}>
                  <td style={{...styles.td, fontWeight: '500', color: '#0f172a'}}>
                    {inv.cashflow_entities?.name || 'N/A'}
                    {inv.is_proforma && <span style={styles.badgeProforma}>PROFORMA</span>}
                  </td>
                  <td style={styles.td}>
                    <div style={{ fontWeight: '600' }}>{inv.invoice_number}</div>
                    {inv.irn_number && <div style={{ fontSize: '0.75rem', color: '#94a3b8', marginTop: '4px' }}>IRN: {inv.irn_number.substring(0, 10)}...</div>}
                  </td>
                  <td style={styles.td}>{inv.invoice_date}</td>
                  <td style={styles.td}>₹{parseFloat(inv.amount || 0).toLocaleString('en-IN')}</td>
                  <td style={{...styles.td, fontWeight: '600', color: '#0f172a'}}>₹{total.toLocaleString('en-IN')}</td>
                  <td style={styles.td}>
                    <span style={inv.status === 'paid' ? styles.badgePaid : styles.badgePending}>
                      {inv.status}
                    </span>
                  </td>
                  <td style={styles.td}>
                    {inv.status === 'pending' && !inv.is_proforma && isAdmin && (
                      <button
                        onClick={() => handleApproveInvoice(inv.id)}
                        disabled={approvingId === inv.id}
                        style={{
                          ...styles.actionBtn,
                          marginRight: '0.5rem',
                          color: '#ffffff',
                          border: '1px solid #2563eb',
                          backgroundColor: approvingId === inv.id ? '#94a3b8' : '#2563eb',
                          cursor: approvingId === inv.id ? 'not-allowed' : 'pointer',
                        }}
                      >
                        {approvingId === inv.id ? 'Approving...' : 'Approve'}
                      </button>
                    )}

                    {inv.status !== 'paid' && !inv.is_proforma && (
                      <button onClick={() => handleRecordPayment(inv)} style={styles.actionBtn}>
                        Collect
                      </button>
                    )}
                    <button onClick={() => downloadInvoice(inv)} style={{ ...styles.actionBtn, marginLeft: '0.5rem' }}>
                      Download
                    </button>
                  </td>
                </tr>
              );
            })}
            {!loading && invoices.length === 0 && (
              <tr>
                <td colSpan="7" style={{ padding: '3rem', textAlign: 'center', color: '#94a3b8' }}>No invoices created yet.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}