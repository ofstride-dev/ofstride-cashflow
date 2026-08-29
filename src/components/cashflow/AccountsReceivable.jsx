// AccountsReceivable.jsx
// NOTE: Business logic (invoice CRUD, payments, approvals, HTML/CSV export)
// is unchanged from the original implementation. Only the presentation layer
// has been restyled onto the shared design system.

import { useState, useEffect, useRef } from 'react';
import { Download, Plus, Trash2 } from 'lucide-react';
import { cashflowFetch, parseCashflowResponse } from '../../services/cashflowApi';
import { exportRowsAsCsv } from '../../services/csvExport';
import { useCashflowAuth } from '../../context/CashflowAuthContext';
import { supabase } from '../../services/supabase';

const GST_SERVICE_RATES = [
  { value: '0', label: 'GST-exempt service (0%)' },
  { value: '5', label: 'Restaurant / transport service (5%)' },
  { value: '12', label: 'Specified service (12%)' },
  { value: '18', label: 'Professional / business service (18%)' },
  { value: '28', label: 'Luxury / specified service (28%)' },
];

function TableSkeleton() {
  return (
    <div className="p-6 space-y-3" aria-busy="true" aria-live="polite">
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} className="skeleton-ui h-12" />
      ))}
      <span className="sr-only">Loading accounts receivable…</span>
    </div>
  );
}

function escapeHtml(value) { return String(value ?? '').replace(/[&<>"']/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character])); }
function amountInWords(value) { return value ? `Rupees ${Number(value).toLocaleString('en-IN', { maximumFractionDigits: 2 })} only` : ''; }

export default function AccountsReceivable() {
  const { isAdmin, session, profile } = useCashflowAuth();
  const authIdentityKey = `${session?.user?.id || ''}:${profile?.company_id || ''}`;
  const activeIdentityKeyRef = useRef(authIdentityKey);
  const [invoices, setInvoices] = useState([]);
  const [companyDetails, setCompanyDetails] = useState({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [approvingId, setApprovingId] = useState('');
  
  const [formData, setFormData] = useState({
    customer_name: '', customer_gstin: '', invoice_number: '', invoice_raised_by: '', discount_percent: '',
    invoice_date: new Date().toISOString().split('T')[0], 
    due_date: '', amount: '', gst_amount: '', gst_mode: 'percentage', gst_rate: '18', irn_number: '', notes: '', item_services: ['']
  });

  useEffect(() => {
    if (!profile?.company_id) return;
    supabase.from('companies').select('name,legal_name,billing_address,phone,gstin,pan,default_hsn_sac,bank_name,bank_account_number,bank_ifsc').eq('id', profile.company_id).maybeSingle().then(({ data }) => { if (data) setCompanyDetails(data); });
  }, [profile?.company_id]);

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
    const customer = invoice?.cashflow_entities?.name || '';
    const seller = companyDetails;
    const sellerName = seller.legal_name || seller.name || profile?.company_name || '';
    const tax = gst;
    const cgst = ''; const sgst = ''; const igst = '';

    const html = `<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>Invoice ${invoice?.invoice_number || ''}</title>
    <style>
      * { box-sizing: border-box; } body { font-family: Arial, sans-serif; margin: 0; padding: 28px; color: #172033; font-size: 12px; } .invoice { max-width: 900px; margin: auto; border: 1px solid #cbd5e1; } .header { display: flex; justify-content: space-between; gap: 24px; padding: 22px; border-bottom: 2px solid #172033; } h1 { margin: 0 0 8px; font-size: 24px; letter-spacing: .08em; } h2 { margin: 0 0 8px; font-size: 17px; } .muted { color: #64748b; line-height: 1.5; } .meta { min-width: 245px; } .meta div, .summary-row { display: flex; justify-content: space-between; gap: 16px; padding: 4px 0; } .section { padding: 16px 22px; border-bottom: 1px solid #cbd5e1; } .parties { display: grid; grid-template-columns: 1fr 1fr; gap: 25px; } table { width: 100%; border-collapse: collapse; } th, td { border: 1px solid #cbd5e1; padding: 9px 8px; vertical-align: top; } th { background: #eef2f7; text-transform: uppercase; font-size: 10px; letter-spacing: .04em; } .right { text-align: right; } .totals { margin-left: auto; width: 360px; } .grand { font-size: 15px; font-weight: bold; background: #eef2f7; } .footer-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 25px; } .sign { min-height: 75px; text-align: center; padding-top: 35px; } @media print { body { padding: 0; } .invoice { border: 0; } }
    </style>
  </head>
  <body><div class="invoice">
    <div class="header"><div><h2>${escapeHtml(sellerName)}</h2><div class="muted">${escapeHtml(seller.billing_address)}</div><div>${escapeHtml(seller.phone)}</div><div>GSTIN: ${escapeHtml(seller.gstin)}</div><div>PAN: ${escapeHtml(seller.pan)}</div></div><div class="meta"><h1>TAX INVOICE</h1><div><b>Invoice No.</b><span>${escapeHtml(invoice?.invoice_number)}</span></div><div><b>Invoice Date</b><span>${escapeHtml(invoice?.invoice_date)}</span></div><div><b>Due Date</b><span>${escapeHtml(invoice?.due_date)}</span></div><div><b>IRN</b><span>${escapeHtml(invoice?.irn_number)}</span></div></div></div>
    <div class="section parties"><div><b>Bill To</b><h2>${escapeHtml(customer)}</h2><div>Address: ${escapeHtml(invoice?.customer_address)}</div><div>GSTIN: ${escapeHtml(invoice?.cashflow_entities?.gstin)}</div></div><div><b>Place of Supply</b><div>State: ${escapeHtml(invoice?.place_of_supply_state)}</div><div>State Code: ${escapeHtml(invoice?.place_of_supply_code)}</div></div></div>
    <div class="section"><table>
      <thead>
        <tr><th>#</th><th>Description</th><th>HSN/SAC Code</th><th>Quantity</th><th>Unit Rate</th><th class="right">Total Amount</th></tr>
      </thead>
      <tbody>
        ${(items.length ? items : ['']).map((item, index) => `<tr><td>${index + 1}</td><td>${escapeHtml(item)}</td><td>${escapeHtml(invoice?.hsn_sac_code || seller.default_hsn_sac)}</td><td>${escapeHtml(invoice?.quantity)}</td><td class="right">${escapeHtml(invoice?.unit_rate)}</td><td class="right">${index === 0 ? `₹${subtotal.toFixed(2)}` : ''}</td></tr>`).join('')}
      </tbody>
    </table></div><div class="section"><div class="totals"><div class="summary-row"><span>Subtotal (Taxable Amount)</span><b>₹${subtotal.toFixed(2)}</b></div><div class="summary-row"><span>CGST</span><span>${cgst ? `₹${cgst}` : ''}</span></div><div class="summary-row"><span>SGST</span><span>${sgst ? `₹${sgst}` : ''}</span></div><div class="summary-row"><span>IGST</span><span>${igst ? `₹${igst}` : ''}</span></div><div class="summary-row"><span>GST Total</span><b>₹${tax.toFixed(2)}</b></div><div class="summary-row grand"><span>Grand Total</span><span>₹${total.toFixed(2)}</span></div></div></div><div class="section footer-grid"><div><b>Total Amount in Words</b><p>${escapeHtml(amountInWords(total))}</p><b>Bank Account Details</b><p class="muted">Bank: ${escapeHtml(seller.bank_name)}<br>Account Number: ${escapeHtml(seller.bank_account_number)}<br>IFSC Code: ${escapeHtml(seller.bank_ifsc)}</p></div><div><b>For ${escapeHtml(sellerName)}</b><div class="sign">Authorized Signatory</div></div></div></div></body>
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
    const next = { ...formData, [name]: type === 'checkbox' ? checked : value };
    if (name === 'amount' || name === 'discount_percent' || name === 'gst_rate' || name === 'gst_mode') {
      const rate = name === 'gst_rate' ? Number(value) : Number(next.gst_rate || 0);
      const grossAmount = Number(name === 'amount' ? value : next.amount) || 0;
      const discount = Number(name === 'discount_percent' ? value : next.discount_percent) || 0;
      const net = grossAmount * Math.max(0, 1 - Math.min(100, discount) / 100);
      if ((name === 'gst_mode' ? value : next.gst_mode) === 'percentage') {
        next.gst_amount = net > 0 ? (net * rate / 100).toFixed(2) : '';
      } else if (name === 'gst_mode') {
        next.gst_amount = net > 0 ? (net * rate / 100).toFixed(2) : '';
      }
    }
    setFormData(next);
  };

  const handleCreateInvoice = async (e) => {
    e.preventDefault();
    const requestIdentityKey = authIdentityKey;
    const invoicePayload = { ...formData };
    delete invoicePayload.gst_mode;
    delete invoicePayload.gst_rate;
    setSaving(true);
    try {
      const res = await cashflowFetch('/cashflow/ar/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(invoicePayload)
      });
      const parsed = await parseCashflowResponse(res);
      if (activeIdentityKeyRef.current !== requestIdentityKey) return;
      if (parsed.ok) {
        setInvoices((previousInvoices) => [parsed.data, ...previousInvoices]);
        setFormData({ 
            customer_name: '', customer_gstin: '', invoice_number: '', invoice_raised_by: '', discount_percent: '',
          invoice_date: new Date().toISOString().split('T')[0], 
            due_date: '', amount: '', gst_amount: '', gst_mode: 'percentage', gst_rate: '18', irn_number: '', notes: '', item_services: ['']
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
        balance_due: Number(inv.balance_due || 0).toFixed(2),
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
        { header: 'Net Amount', key: 'amount' },
        { header: 'Total Invoice Value', key: 'total_invoice_value' },
        { header: 'Balance Due', key: 'balance_due' },
        { header: 'Status', key: 'status' },
        { header: 'Is Proforma', key: 'is_proforma' },
        { header: 'IRN Number', key: 'irn_number' },
      ],
      rows
    );
  };

  const totalOutstanding = invoices
    .filter(inv => inv.status !== 'paid' && !inv.is_proforma)
    .reduce((acc, curr) => acc + Number(curr.balance_due ?? (parseFloat(curr.amount || 0) + parseFloat(curr.gst_amount || 0))), 0);

  return (
    <div className="max-w-6xl mx-auto">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <h2 className="text-2xl font-bold text-primary sm:text-[1.75rem]">Accounts Receivable</h2>
        <div className="flex flex-wrap items-center justify-end gap-3">
          <button type="button" onClick={handleDownloadReport} className="btn-ui btn-ui-info">
            <Download className="h-4 w-4" />
            Download Report
          </button>
          <div className="rounded-2xl border border-sky-100 bg-gradient-to-br from-white to-sky-50 px-6 py-4 shadow-card">
            <p className="text-xs font-bold uppercase tracking-wider text-muted">Total Outstanding</p>
            <p className="mt-0.5 text-2xl font-bold text-info tabular-nums">
              ₹{totalOutstanding.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
            </p>
          </div>
        </div>
      </div>

      <div className="card-ui mb-10 p-6 sm:p-8">
        <h3 className="mb-6 text-lg font-semibold text-primary">Create New Invoice</h3>
        <form onSubmit={handleCreateInvoice} className="grid items-start gap-6" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
          <div>
            <label className="label-ui" htmlFor="ar-customer_name">Customer Name</label>
            <input id="ar-customer_name" type="text" name="customer_name" value={formData.customer_name} onChange={handleInputChange} required className="input-ui" />
          </div>
          <div>
            <label className="label-ui" htmlFor="ar-invoice_number">Invoice #</label>
            <input id="ar-invoice_number" type="text" name="invoice_number" value={formData.invoice_number} onChange={handleInputChange} placeholder="Auto-generated" className="input-ui" />
          </div>
          <div>
            <label className="label-ui" htmlFor="ar-invoice_date">Invoice Date</label>
            <input id="ar-invoice_date" type="date" name="invoice_date" value={formData.invoice_date} onChange={handleInputChange} required className="input-ui" />
          </div>
          <div>
            <label className="label-ui" htmlFor="ar-due_date">Due Date</label>
            <input id="ar-due_date" type="date" name="due_date" value={formData.due_date} onChange={handleInputChange} required className="input-ui" />
          </div>
          <div>
            <label className="label-ui" htmlFor="ar-amount">Amount Before Discount (₹)</label>
            <input id="ar-amount" type="number" name="amount" value={formData.amount} onChange={handleInputChange} required className="input-ui" />
          </div>
          <div>
            <label className="label-ui" htmlFor="ar-discount_percent">Discount (%)</label>
            <input id="ar-discount_percent" type="number" name="discount_percent" min="0" max="100" step="0.01" value={formData.discount_percent} onChange={handleInputChange} placeholder="Optional" className="input-ui" />
            <p className="mt-1 text-xs text-muted">GST is calculated after this discount.</p>
          </div>
          <div>
            <label className="label-ui" htmlFor="ar-gst_mode">GST Calculation</label>
            <select id="ar-gst_mode" name="gst_mode" value={formData.gst_mode} onChange={handleInputChange} className="input-ui">
              <option value="percentage">Enter GST percentage</option>
              <option value="service">Select service category</option>
            </select>
          </div>
          <div>
            <label className="label-ui" htmlFor="ar-gst_rate">{formData.gst_mode === 'service' ? 'Service GST Rate' : 'GST Rate (%)'}</label>
            {formData.gst_mode === 'service' ? (
              <select id="ar-gst_rate" name="gst_rate" value={formData.gst_rate} onChange={handleInputChange} className="input-ui">
                {GST_SERVICE_RATES.map((rate) => <option key={rate.value} value={rate.value}>{rate.label}</option>)}
              </select>
            ) : (
              <input id="ar-gst_rate" type="number" name="gst_rate" min="0" max="100" step="0.01" value={formData.gst_rate} onChange={handleInputChange} className="input-ui" />
            )}
          </div>
          <div>
            <label className="label-ui" htmlFor="ar-gst_amount">GST Amount (₹)</label>
            <input id="ar-gst_amount" type="number" name="gst_amount" value={formData.gst_amount} readOnly className="input-ui bg-slate-50" aria-describedby="ar-gst-help" />
            <p id="ar-gst-help" className="mt-1 text-xs text-muted">Calculated on the amount after discount and before GST.</p>
          </div>
          <div>
            <label className="label-ui" htmlFor="ar-irn_number">IRN Number</label>
            <input id="ar-irn_number" type="text" name="irn_number" value={formData.irn_number} onChange={handleInputChange} placeholder="Optional" className="input-ui" />
          </div>
          <div>
            <label className="label-ui" htmlFor="ar-invoice_raised_by">Invoice raised by</label>
            <input id="ar-invoice_raised_by" type="text" name="invoice_raised_by" value={formData.invoice_raised_by} onChange={handleInputChange} placeholder="Employee / admin name (optional)" className="input-ui" />
          </div>

          <div className="col-span-full">
            <label className="label-ui">Item / Service</label>
            <div className="grid gap-2">
              {formData.item_services.map((item, index) => (
                <div key={`item-${index}`} className="flex items-center gap-2">
                  <input
                    type="text"
                    value={item}
                    onChange={(e) => {
                      const nextItems = [...formData.item_services];
                      nextItems[index] = e.target.value;
                      setFormData({ ...formData, item_services: nextItems });
                    }}
                    placeholder={`Item/Service ${index + 1}`}
                    className="input-ui"
                  />
                  {formData.item_services.length > 1 && (
                    <button
                      type="button"
                      onClick={() => {
                        const nextItems = formData.item_services.filter((_, idx) => idx !== index);
                        setFormData({ ...formData, item_services: nextItems.length ? nextItems : [''] });
                      }}
                      aria-label={`Remove item ${index + 1}`}
                      className="btn-ui btn-ui-sm btn-ui-danger shrink-0"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>
              ))}
            </div>
            <button
              type="button"
              onClick={() => setFormData({ ...formData, item_services: [...formData.item_services, ''] })}
              className="btn-ui btn-ui-sm btn-ui-neutral mt-2.5"
            >
              <Plus className="h-3.5 w-3.5" />
              Add Another Item
            </button>
          </div>

          <button type="submit" disabled={saving} className="btn-ui btn-ui-primary h-[45px]">
            {saving ? 'Creating...' : 'Create Invoice'}
          </button>
        </form>
      </div>

      <div className="scroll-ui overflow-x-auto rounded-2xl border border-slate-200 bg-white shadow-card">
        {loading ? (
          <TableSkeleton />
        ) : (
          <table className="table-ui whitespace-nowrap text-sm">
            <thead>
              <tr>
                <th>Customer / Invoice #</th>
                <th>Invoice Date</th>
                <th>Due Date</th>
                <th>Gross</th>
                <th>Balance Due</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {invoices.map((inv) => {
                const net = parseFloat(inv.amount || 0);
                const gst = parseFloat(inv.gst_amount || 0);
                const total = net + gst;

                return (
                  <tr key={inv.id}>
                    <td className="leading-tight font-medium text-primary">
                      <span className="block">{inv.cashflow_entities?.name || 'N/A'}</span>
                      <span className="mt-1 block text-xs text-muted">Invoice #: {inv.invoice_number || '—'}</span>
                      {inv.irn_number && <span className="mt-1 block text-xs text-muted">IRN: {inv.irn_number.substring(0, 10)}...</span>}
                      {inv.is_proforma && (
                        <span className="badge-ui badge-ui-warning ml-2 align-middle">Proforma</span>
                      )}
                    </td>
                    <td className="text-xs text-muted">{inv.invoice_date || '—'}</td>
                    <td className="text-xs font-semibold text-primary">{inv.due_date || '—'}</td>
                    <td className="font-semibold text-primary tabular-nums"><details><summary className="cursor-pointer">₹{total.toLocaleString('en-IN')}</summary><span className="block text-xs text-muted">Net ₹{net.toLocaleString('en-IN')} · GST ₹{gst.toLocaleString('en-IN')}</span></details></td>
                    <td className="font-semibold text-amber-700 tabular-nums">₹{Number(inv.balance_due ?? total).toLocaleString('en-IN')}</td>
                    <td>
                      <span className={`badge-ui ${inv.status === 'paid' || Number(inv.balance_due ?? total) <= 0 ? 'badge-ui-success' : inv.aging_category === 'Overdue' ? 'badge-ui-danger' : inv.aging_category === 'Due Soon' ? 'badge-ui-warning' : 'badge-ui-success'}`}>
                        {inv.status === 'paid' || Number(inv.balance_due ?? total) <= 0 ? 'Paid' : (inv.aging_label || inv.status)}
                      </span>
                    </td>
                    <td className="sticky right-0 bg-white shadow-[-8px_0_12px_-12px_rgba(15,23,42,.35)]">
                      <div className="flex flex-wrap items-center gap-2">
                        {inv.status === 'pending' && !inv.is_proforma && isAdmin && (
                          <button
                            onClick={() => handleApproveInvoice(inv.id)}
                            disabled={approvingId === inv.id}
                            className="btn-ui btn-ui-sm btn-ui-secondary"
                          >
                            {approvingId === inv.id ? 'Approving...' : 'Approve'}
                          </button>
                        )}
                        {inv.status !== 'paid' && !inv.is_proforma && (
                          <button onClick={() => handleRecordPayment(inv)} className="btn-ui btn-ui-sm btn-ui-info">
                            Collect
                          </button>
                        )}
                        <button onClick={() => downloadInvoice(inv)} className="btn-ui btn-ui-sm btn-ui-neutral">
                          Download
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
              {!loading && invoices.length === 0 && (
                <tr>
                  <td colSpan="7" className="py-12 text-center text-muted">
                    No invoices created yet.
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
