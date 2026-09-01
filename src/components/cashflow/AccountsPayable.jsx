// AccountsPayable.jsx
// NOTE: Business logic (fetching, OCR, save, approve, export) is unchanged
// from the original implementation. Only the presentation layer has been
// restyled onto the shared design system.

import { useState, useEffect, useRef } from 'react';
import { Download, FileUp, ShieldCheck } from 'lucide-react';
import { cashflowFetch, parseCashflowResponse } from '../../services/cashflowApi';
import { exportRowsAsCsv } from '../../services/csvExport';
import { useCashflowAuth } from '../../context/CashflowAuthContext';
import CollectAmountModal from './CollectAmountModal';

const FIELD_ROWS = [
  ['Vendor Name', 'vendor_name', 'text'],
  ['Invoice #', 'bill_number', 'text'],
  ['Invoice Date', 'bill_date', 'date'],
  ['Payment Terms (Days)', 'payment_terms_days', 'number'],
  ['Total Amount Before GST', 'amount_before_gst', 'number'],
  ['GST Total', 'gst_amount', 'number'],
  ['Gross Total (Net + GST)', 'total_amount', 'number'],
];

function TableSkeleton() {
  return (
    <div className="p-6 space-y-3" aria-busy="true" aria-live="polite">
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} className="skeleton-ui h-12" />
      ))}
      <span className="sr-only">Loading accounts payable…</span>
    </div>
  );
}

export default function AccountsPayable() {
  const { isAdmin, session, profile } = useCashflowAuth();
  const authIdentityKey = `${session?.user?.id || ''}:${profile?.company_id || ''}`;
  const activeIdentityKeyRef = useRef(authIdentityKey);
  const [invoices, setInvoices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [ocrLoading, setOcrLoading] = useState(false);
  const [approvingId, setApprovingId] = useState('');
  const [ocrStatus, setOcrStatus] = useState({ type: '', message: '' });
  const [ocrDebugDetail, setOcrDebugDetail] = useState('');
  const [payBill, setPayBill] = useState(null);

  const [formData, setFormData] = useState({
    vendor_name: '',
    bill_number: '',
    bill_date: '',
    payment_terms_days: '30',
    amount_before_gst: '',
    gst_amount: '',
    gst_rate: '',
    total_amount: '',
    tds_section: 'NONE'
  });

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
      const res = await cashflowFetch('/cashflow/ap/list');
      const parsed = await parseCashflowResponse(res);
      if (!isRequestCurrent()) return;
      if (parsed.ok) {
        setInvoices(parsed.data || []);
      } else {
        // For first-time setup or transient API issues, show an empty list.
        setInvoices([]);
        console.warn('AP list failed:', parsed.error);
      }
    } catch (err) {
      if (isRequestCurrent()) setInvoices([]);
      console.warn('AP list error:', err);
    } finally {
      if (isRequestCurrent()) setLoading(false);
    }
  };

  const handleFileUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    const allowedTypes = [
      'application/pdf',
      'image/jpeg',
      'image/jpg',
      'image/png',
      'image/tiff',
      'image/bmp',
    ];
    const maxBytes = 15 * 1024 * 1024;

    if (!allowedTypes.includes((file.type || '').toLowerCase())) {
      setOcrStatus({
        type: 'warning',
        message: 'Unsupported file type. Please upload PDF, JPG, PNG, TIFF, or BMP.',
      });
      setOcrDebugDetail(`Detected type: ${file.type || 'unknown'}`);
      return;
    }

    if (file.size > maxBytes) {
      setOcrStatus({
        type: 'warning',
        message: 'File is too large for stable OCR processing. Please upload a file under 15 MB.',
      });
      setOcrDebugDetail(`Detected size: ${(file.size / (1024 * 1024)).toFixed(2)} MB`);
      return;
    }

    setOcrLoading(true);
    setOcrStatus({ type: '', message: '' });
    setOcrDebugDetail('');
    const requestIdentityKey = authIdentityKey;
    const reader = new FileReader();
    reader.readAsDataURL(file);
    reader.onload = async () => {
      try {
        const res = await cashflowFetch('/cashflow/ap/ocr',{
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({file:reader.result})
        });
        const parsed = await parseCashflowResponse(res);
        if (activeIdentityKeyRef.current !== requestIdentityKey) return;
        if(parsed.ok) {
          const payload = parsed.data || {};
          const scanStatus = String(payload._scan_status || '').toLowerCase();
          const scanMessage = String(payload._scan_message || '').trim();
          const scanDetail = String(payload._scan_error_detail || '').trim();
          const nextValues = {
            vendor_name: payload.vendor_name || '',
            bill_number: payload.bill_number || '',
            bill_date: payload.bill_date || '',
            payment_terms_days: payload.payment_terms_days ?? '30',
            amount_before_gst: payload.amount_before_gst ?? Math.max((Number(payload.amount || 0) - Number(payload.gst_amount || 0)), 0),
            gst_amount: payload.gst_amount || 0,
            total_amount: payload.total_amount ?? (payload.amount || 0),
          };
          setFormData(p=>({...p,...nextValues}));

          if (scanStatus === 'warning') {
            setOcrStatus({
              type: 'warning',
              message: scanMessage || 'Invoice uploaded but scan could not extract fields.',
            });
            setOcrDebugDetail(scanDetail);
          } else {
            setOcrStatus({
              type: 'success',
              message: scanMessage || 'Invoice scanned successfully.',
            });
            setOcrDebugDetail(scanDetail);
          }
        }
        else {
          console.error('AP OCR failed:', parsed.error);
          setOcrStatus({ type: 'error', message: parsed.error || 'Scan failed. Please retry.' });
          setOcrDebugDetail('');
        }
      } finally {
        if (activeIdentityKeyRef.current === requestIdentityKey) setOcrLoading(false);
      }
    };
  };

  const handleInputChange = (e) => {
    const { name, value } = e.target;
    setFormData((prev) => {
      const next = { ...prev, [name]: value };
      const base = Number(next.amount_before_gst || 0);
      const gst = Number(next.gst_amount || 0);
      const total = Number(next.total_amount || 0);

      if (name === 'amount_before_gst' || name === 'gst_rate') {
        const rate = Number(next.gst_rate || 0);
        next.gst_amount = base > 0 ? (base * rate / 100).toFixed(2) : '';
        next.total_amount = String(Math.max(base + Number(next.gst_amount || 0), 0));
      } else if (name === 'gst_amount') {
        next.total_amount = String(Math.max(base + gst, 0));
      } else if (name === 'total_amount' && next.gst_amount !== '') {
        next.amount_before_gst = String(Math.max(total - gst, 0));
      }

      return next;
    });
  };

  const handleApproveBill = async (billId) => {
    if (!billId) return;
    const requestIdentityKey = authIdentityKey;
    setApprovingId(billId);
    try {
      const res = await cashflowFetch('/cashflow/ap/approve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ bill_id: billId }),
      });
      const parsed = await parseCashflowResponse(res);
      if (activeIdentityKeyRef.current !== requestIdentityKey) return;
      if (parsed.ok && parsed.data) {
        setInvoices((prev) => prev.map((bill) => (bill.id === billId ? parsed.data : bill)));
      } else {
        console.error('AP approve failed:', parsed.error);
      }
    } finally {
      if (activeIdentityKeyRef.current === requestIdentityKey) setApprovingId('');
    }
  };

  const handleRecordPayment = async (bill, amount) => {
    const gross = Number(bill.amount || 0);
    const balance = Number(bill.balance_due ?? gross);
    if (balance <= 0) return false;
    try {
      const res = await cashflowFetch('/cashflow/payments/create', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ bill_id: bill.id, amount, payment_mode: 'bank_transfer' }) });
      const parsed = await parseCashflowResponse(res);
      if (parsed.ok) {
        await fetchInvoices(() => activeIdentityKeyRef.current === authIdentityKey);
        return true;
      }
      console.error('AP payment failed:', parsed.error);
      return false;
    } catch (error) { console.error('AP payment failed:', error); return false; }
  };

  const handleSaveInvoice=async(e)=>{
    e.preventDefault();
    const requestIdentityKey = authIdentityKey;
    try {
      const res=await cashflowFetch('/cashflow/ap/save',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({
          ...formData,
          amount: formData.total_amount,
        })
      });
      const parsed = await parseCashflowResponse(res);
      if (activeIdentityKeyRef.current !== requestIdentityKey) return;
      if(parsed.ok){
        setInvoices((previousInvoices) => [parsed.data, ...previousInvoices]);
        setFormData({vendor_name:'',bill_number:'',bill_date:'',payment_terms_days:'30',amount_before_gst:'',gst_amount:'',gst_rate:'',total_amount:'',tds_section:'NONE'});
      } else {
        const msg = String(parsed.error || 'Unable to save bill.');
        console.error('AP save failed:', msg);
      }
    } catch (error) {
      console.error('AP save failed:', error instanceof Error ? error.message : 'Unable to save bill.');
    }
  };

  const handleDownloadReport = () => {
    const now = new Date().toISOString().slice(0, 10);
    const rows = (invoices || []).map((inv) => {
      const gst = Number(inv.gst_amount || 0);
      const storedAmount = Number(inv.amount || 0);
      // AP stores amount as the invoice total. Derive the taxable/net value
      // from that total so Gross is always displayed as Net + GST.
      const netBeforeGst = Number(inv.amount_before_gst || Math.max(storedAmount - gst, 0));
      const gross = netBeforeGst + gst;
      const tds = Number(inv.tds_amount || 0);
      const vendor = inv.cashflow_entities?.name || 'N/A';

      return {
        vendor,
        bill_number: inv.bill_number || '',
        bill_date: inv.bill_date || '',
        due_date: inv.due_date || '',
        payment_terms_days: inv.payment_terms_days ?? '',
        balance_due: Number(inv.balance_due || 0).toFixed(2),
        gross_amount: gross.toFixed(2),
        gst_amount: gst.toFixed(2),
        tds_amount: tds.toFixed(2),
        net_amount: netBeforeGst.toFixed(2),
        status: inv.status || '',
      };
    });

    exportRowsAsCsv(
      `ap_report_${now}.csv`,
      [
        { header: 'Vendor', key: 'vendor' },
        { header: 'Bill Number', key: 'bill_number' },
        { header: 'Bill Date', key: 'bill_date' },
        { header: 'Due Date', key: 'due_date' },
        { header: 'Payment Terms (Days)', key: 'payment_terms_days' },
        { header: 'Gross Amount', key: 'gross_amount' },
        { header: 'GST Amount', key: 'gst_amount' },
        { header: 'TDS Amount', key: 'tds_amount' },
        { header: 'Net Amount', key: 'net_amount' },
        { header: 'Balance Due', key: 'balance_due' },
        { header: 'Status', key: 'status' },
      ],
      rows
    );
  };

  return (
    <div className="max-w-6xl mx-auto">
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-gradient-to-br from-white to-sky-50/60 px-5 py-5 shadow-card sm:px-6">
        <div>
          <h2 className="text-2xl font-bold text-primary sm:text-[1.75rem]">Accounts Payable</h2>
          <p className="mt-1 text-sm text-muted">Capture vendor bills, apply tax rules, and maintain a clean payable register.</p>
        </div>
        <button type="button" onClick={handleDownloadReport} className="btn-ui btn-ui-info">
          <Download className="h-4 w-4" />
          Download Report
        </button>
      </div>

      <div className="mb-7 flex flex-wrap gap-6">
        <div className="flex-1 min-w-[280px] rounded-2xl border-2 border-dashed border-slate-200 bg-white p-8 text-center shadow-card">
          <FileUp className="mx-auto h-8 w-8 text-secondary" aria-hidden="true" />
          <h3 className="mt-3 text-lg font-semibold text-primary">Upload Vendor Invoice</h3>
          <p className="mt-1 text-sm text-muted">Upload PDF or image. AI extracts everything automatically.</p>
          <label className="mt-4 inline-block">
            <span className="sr-only">Upload invoice file</span>
            <input
              type="file"
              accept=".pdf,image/*"
              onChange={handleFileUpload}
              className="mx-auto block text-sm text-text file:mr-3 file:rounded-lg file:border-0 file:bg-primary file:px-3.5 file:py-2 file:text-sm file:font-semibold file:text-white hover:file:bg-primary-hover"
            />
          </label>

          {ocrLoading && (
            <div className="mt-4 inline-flex items-center gap-2 rounded-xl bg-blue-50 px-4 py-2.5 text-sm font-semibold text-secondary">
              <span className="h-2 w-2 animate-pulse rounded-full bg-secondary" />
              Scanning document…
            </div>
          )}
          {!ocrLoading && ocrStatus.message && (
            <div
              className={`mt-3 rounded-xl border px-3 py-2.5 text-left text-[0.8rem] font-semibold ${
                ocrStatus.type === 'success'
                  ? 'border-emerald-300 bg-emerald-50 text-emerald-800'
                  : ocrStatus.type === 'warning'
                  ? 'border-amber-300 bg-amber-50 text-amber-800'
                  : 'border-rose-300 bg-rose-50 text-rose-800'
              }`}
              role="status"
            >
              {ocrStatus.message}
              {ocrDebugDetail && <div className="mt-1.5 text-xs font-medium opacity-90">Detail: {ocrDebugDetail}</div>}
            </div>
          )}
        </div>

        <div className="flex-[2] min-w-[420px] rounded-2xl border border-slate-200 bg-gradient-to-br from-white to-sky-50/60 p-6 shadow-card sm:p-8">
          <h3 className="mb-5 text-lg font-semibold text-primary">Verify &amp; Apply Tax</h3>
          <form onSubmit={handleSaveInvoice} className="grid grid-cols-1 gap-5 sm:grid-cols-2">
            {FIELD_ROWS.map(([label, name, type]) => (
              <div key={name}>
                <label className="label-ui" htmlFor={`ap-${name}`}>{label}</label>
                <input
                  id={`ap-${name}`}
                  type={type}
                  name={name}
                  value={formData[name]}
                  onChange={handleInputChange}
                  className="input-ui h-12"
                />
              </div>
            ))}
            <div>
              <label className="label-ui" htmlFor="ap-gst_rate">GST Rate (%)</label>
              <input id="ap-gst_rate" type="number" name="gst_rate" min="0" max="100" step="0.01" value={formData.gst_rate} onChange={handleInputChange} placeholder="Optional" className="input-ui h-12" />
              <p className="mt-1 text-xs text-muted">GST is calculated on the amount before GST.</p>
            </div>
            <div>
              <label className="label-ui" htmlFor="ap-tds_section">TDS Rule</label>
              <select id="ap-tds_section" name="tds_section" value={formData.tds_section} onChange={handleInputChange} className="input-ui h-12 bg-white">
                <option value="NONE">No TDS</option>
                <option value="194C_IND">194C Individual</option>
                <option value="194C_CORP">194C Corporate</option>
                <option value="194J_TECH">194J Tech</option>
                <option value="194J_PROF">194J Professional</option>
              </select>
            </div>

            <button type="submit" className="btn-ui btn-ui-primary col-span-full h-12">
              <ShieldCheck className="h-4 w-4" />
              Approve &amp; Save Bill
            </button>
          </form>
        </div>
      </div>

      <div className="scroll-ui overflow-x-auto rounded-2xl border border-slate-200 bg-white shadow-card">
        {loading ? (
          <TableSkeleton />
        ) : (
          <table className="table-ui text-sm">
            <thead>
              <tr>
                {['Vendor / Bill #', 'Bill Date', 'Due Date', 'Gross', 'Balance Due', 'Status', 'Actions'].map((h) => (
                  <th key={h}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {invoices.map((inv) => {
                const vendor = inv.cashflow_entities?.name || 'N/A';
                const gst = +inv.gst_amount || 0;
                const storedAmount = +inv.amount || 0;
                const netBeforeGst = +(inv.amount_before_gst || Math.max(storedAmount - gst, 0));
                const gross = netBeforeGst + gst;
                const pending = inv.status === 'pending';
                const approving = approvingId === inv.id;
                return (
                  <tr key={inv.id}>
                    <td className="leading-tight"><span className="block font-semibold text-primary">{vendor}</span><span className="mt-1 block text-xs text-muted">Bill #: {inv.bill_number || '—'}</span></td>
                    <td className="text-xs text-muted">{inv.bill_date || '—'}</td>
                    <td className="text-xs font-semibold text-primary">{inv.due_date || '—'}</td>
                    <td className="font-semibold text-primary tabular-nums"><details><summary className="cursor-pointer">₹{gross.toLocaleString('en-IN')}</summary><span className="block text-xs text-muted">Net ₹{netBeforeGst.toLocaleString('en-IN')} · GST ₹{gst.toLocaleString('en-IN')} · TDS ₹{(+inv.tds_amount || 0).toLocaleString('en-IN')}</span></details></td>
                    <td className="font-bold text-amber-700 tabular-nums">₹{Number(inv.balance_due ?? gross).toLocaleString('en-IN')}</td>
                    <td>
                       <span className={`badge-ui ${inv.status === 'paid' || Number(inv.balance_due ?? gross) <= 0 ? 'badge-ui-success' : inv.aging_category === 'Overdue' ? 'badge-ui-danger' : inv.aging_category === 'Due Soon' ? 'badge-ui-warning' : 'badge-ui-success'}`}>{inv.status === 'paid' || Number(inv.balance_due ?? gross) <= 0 ? 'Paid' : (inv.aging_label || inv.status)}</span>
                    </td>
                    <td className="sticky right-0 bg-white shadow-[-8px_0_12px_-12px_rgba(15,23,42,.35)]">
                      {pending && isAdmin ? (
                        <button
                          type="button"
                          onClick={() => handleApproveBill(inv.id)}
                          disabled={approving}
                          className="btn-ui btn-ui-sm btn-ui-secondary"
                        >
                          {approving ? 'Approving…' : 'Approve'}
                        </button>
                      ) : (
                        <span className="text-xs text-muted">-</span>
                      )}
                      {Number(inv.balance_due ?? gross) > 0 && (
                         <button type="button" onClick={() => setPayBill(inv)} className="btn-ui btn-ui-sm btn-ui-info">Pay</button>
                      )}
                    </td>
                  </tr>
                );
              })}
              {!loading && invoices.length === 0 && (
                <tr>
                  <td colSpan="7" className="py-10 text-center text-muted">
                    No AP bills recorded yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </div>
      <CollectAmountModal
        key={payBill?.id || 'ap-pay'}
        open={Boolean(payBill)}
        onClose={() => setPayBill(null)}
        onConfirm={async (amount) => { if (await handleRecordPayment(payBill, amount)) setPayBill(null); }}
        title="Pay Vendor"
        documentLabel="Bill"
        documentNumber={payBill?.bill_number}
        grossAmount={payBill ? Number(payBill.amount_before_gst || 0) + Number(payBill.gst_amount || 0) : 0}
        remainingBalance={payBill ? Number(payBill.balance_due ?? payBill.amount ?? 0) : 0}
      />
    </div>
  );
}
