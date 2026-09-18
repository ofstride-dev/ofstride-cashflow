// AccountsPayable.jsx
// NOTE: Business logic (fetching, OCR, save, approve, export) is unchanged
// from the original implementation. Only the presentation layer has been
// restyled onto the shared design system.

import { useState, useEffect, useRef } from 'react';
import { Download, Edit2, FileUp, Plus, ShieldCheck, Trash2 } from 'lucide-react';
import { cashflowFetch, parseCashflowResponse } from '../../services/cashflowApi';
import { exportRowsAsCsv } from '../../services/csvExport';
import { useCashflowAuth } from '../../context/CashflowAuthContext';
import CollectAmountModal from './CollectAmountModal';
import { parseInvoiceSpreadsheet } from '../../services/invoiceDocumentParser';
import DuplicateDocumentModal from './DuplicateDocumentModal';
import AdminMutationModal from './AdminMutationModal';

const GST_SERVICE_RATES = [
  { value: '0', label: 'GST-exempt service (0%)' },
  { value: '5', label: 'Restaurant / transport service (5%)' },
  { value: '12', label: 'Specified service (12%)' },
  { value: '18', label: 'Professional / business service (18%)' },
  { value: '28', label: 'Luxury / specified service (28%)' },
];

const FIELD_ROWS = [
  ['Vendor Name', 'vendor_name', 'text'],
  ['Vendor GSTIN', 'vendor_gstin', 'text'],
  ['Invoice #', 'bill_number', 'text'],
  ['Invoice Date', 'bill_date', 'date'],
  ['Payment Terms (Days)', 'payment_terms_days', 'number'],
  ['Total Amount Before GST', 'amount_before_gst', 'number'],
  ['GST Total', 'gst_amount', 'number'],
  ['Gross Total (Net + GST)', 'total_amount', 'number'],
];

const emptyLineItem = { itemName: '', description: '', unitPrice: 0, quantity: 1, discount: 0, lineTotal: 0 };

const calculateLineTotal = (item) => {
  const subtotal = Number(item.unitPrice || 0) * Number(item.quantity || 0);
  const discount = Math.min(100, Math.max(0, Number(item.discount || 0)));
  return Number((subtotal - (subtotal * discount / 100)).toFixed(3));
};

const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character]));

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
  const [duplicateCandidate, setDuplicateCandidate] = useState(null);
  const [adminTarget, setAdminTarget] = useState(null);
  const [editingId, setEditingId] = useState('');
  const [lineItems, setLineItems] = useState([{ ...emptyLineItem }]);
  const subTotal = Number(lineItems.reduce((total, item) => total + Number(item.lineTotal || 0), 0).toFixed(3));

  const [formData, setFormData] = useState({
    vendor_name: '',
    vendor_gstin: '',
    vendor_address: '',
    bill_number: '',
    bill_date: '',
    payment_terms_days: '30',
    amount_before_gst: '',
    gst_amount: '',
    gst_mode: 'percentage',
    gst_rate: '',
    total_amount: '',
    tds_section: 'NONE'
  });

  useEffect(() => {
    setFormData((previous) => {
      const gstAmount = previous.gst_rate !== ''
        ? Number((subTotal * Number(previous.gst_rate || 0) / 100).toFixed(3))
        : Number(previous.gst_amount || 0);
      return {
        ...previous,
        amount_before_gst: subTotal.toFixed(3),
        gst_amount: gstAmount.toFixed(3),
        total_amount: (subTotal + gstAmount).toFixed(3),
      };
    });
  }, [subTotal, formData.gst_rate]);

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
      'application/vnd.ms-excel',
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    ];
    const maxBytes = 15 * 1024 * 1024;

    if (!allowedTypes.includes((file.type || '').toLowerCase())) {
      setOcrStatus({
        type: 'warning',
        message: 'Unsupported file type. Please upload PDF, Excel, JPG, PNG, TIFF, or BMP.',
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
    if (['application/vnd.ms-excel', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'].includes((file.type || '').toLowerCase()) || /\.(xlsx|xls)$/i.test(file.name)) {
      parseInvoiceSpreadsheet(file).then((payload) => {
        setLineItems(payload.parsedLineItems?.length ? payload.parsedLineItems : [{ ...emptyLineItem }]);
        setFormData((previous) => ({
          ...previous,
          vendor_name: payload.vendor_name || previous.vendor_name,
          vendor_gstin: payload.vendor_gstin || previous.vendor_gstin,
          bill_number: payload.bill_number || previous.bill_number,
          bill_date: payload.bill_date || previous.bill_date,
        }));
        setOcrStatus({ type: 'success', message: 'Excel invoice uploaded. Please review the extracted details.' });
      }).catch((error) => setOcrStatus({ type: 'error', message: error instanceof Error ? error.message : 'Could not read the Excel invoice.' })).finally(() => setOcrLoading(false));
      return;
    }
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
            vendor_gstin: payload.vendor_gstin || '',
            vendor_address: payload.vendor_address || '',
            bill_number: payload.bill_number || '',
            bill_date: payload.bill_date || '',
            payment_terms_days: payload.payment_terms_days ?? '30',
            amount_before_gst: payload.amount_before_gst ?? Math.max((Number(payload.amount || 0) - Number(payload.gst_amount || 0)), 0),
            gst_amount: payload.gst_amount || 0,
            total_amount: payload.total_amount ?? (payload.amount || 0),
            amount: payload.total_amount ?? (payload.amount || 0),
          };
          setLineItems(payload.parsedLineItems?.length ? payload.parsedLineItems : [{ ...emptyLineItem }]);
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

      return next;
    });
  };

  const updateLineItem = (index, field, value) => {
    setLineItems((previousItems) => previousItems.map((item, itemIndex) => {
      if (itemIndex !== index) return item;
      const updated = { ...item, [field]: field === 'itemName' || field === 'description' ? value : Number(value || 0) };
      return { ...updated, lineTotal: calculateLineTotal(updated) };
    }));
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
        await fetchInvoices(() => activeIdentityKeyRef.current === requestIdentityKey);
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

  const handleSaveInvoice=async(e, forceSave = false)=>{
    e.preventDefault();
    const requestIdentityKey = authIdentityKey;
    try {
      const res=await cashflowFetch(editingId ? '/cashflow/ap/update' : '/cashflow/ap/save',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({
          ...formData,
          ...(editingId ? { bill_id: editingId, reason: 'Manual edit', comment: 'Edited from Accounts Payable' } : { force_save: forceSave }),
          amount: formData.total_amount,
          line_items: lineItems,
          party_details: { vendor_name: formData.vendor_name, vendor_gstin: formData.vendor_gstin, vendor_address: formData.vendor_address || '' },
        })
      });
      const parsed = await parseCashflowResponse(res);
      if (activeIdentityKeyRef.current !== requestIdentityKey) return;
      if(parsed.ok){
        setInvoices((previousInvoices) => editingId ? previousInvoices.map((item) => item.id === editingId ? parsed.data : item) : [parsed.data, ...previousInvoices]);
        setEditingId('');
        setFormData({vendor_name:'',vendor_gstin:'',vendor_address:'',bill_number:'',bill_date:'',payment_terms_days:'30',amount_before_gst:'',gst_amount:'',gst_mode:'percentage',gst_rate:'',total_amount:'',tds_section:'NONE'});
        setLineItems([{ ...emptyLineItem }]);
      } else {
        const msg = String(parsed.error || 'Unable to save bill.');
        if (parsed.status === 409 && parsed.data?.existing) {
          setDuplicateCandidate({ ...parsed.data, partyName: formData.vendor_name });
          return;
        }
        setOcrStatus({ type: 'error', message: msg });
        console.error('AP save failed:', msg);
      }
    } catch (error) {
      console.error('AP save failed:', error instanceof Error ? error.message : 'Unable to save bill.');
    }
  };

  const startEditBill = (bill) => {
    setEditingId(bill.id);
    setFormData((previous) => ({ ...previous, vendor_name: bill.cashflow_entities?.name || bill.party_details?.vendor_name || '', vendor_gstin: bill.cashflow_entities?.gstin || bill.party_details?.vendor_gstin || '', bill_number: bill.bill_number || '', bill_date: bill.bill_date || '', payment_terms_days: String(bill.payment_terms_days ?? 30), amount_before_gst: String(bill.amount_before_gst ?? Math.max(Number(bill.amount || 0) - Number(bill.gst_amount || 0), 0)), gst_amount: String(bill.gst_amount || 0), total_amount: String(bill.amount || 0) }));
    setLineItems(Array.isArray(bill.line_items) && bill.line_items.length ? bill.line_items : [{ ...emptyLineItem }]);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const confirmAdminAction = async ({ reason, comment }) => {
    if (!adminTarget) return;
    const response = await cashflowFetch(`/cashflow/ap/${adminTarget.action}`, { method: 'POST', body: JSON.stringify({ bill_id: adminTarget.id, reason, comment }) });
    const parsed = await parseCashflowResponse(response);
    if (!parsed.ok) throw new Error(parsed.error || `Could not ${adminTarget.action} bill.`);
    setAdminTarget(null);
    await fetchInvoices(() => activeIdentityKeyRef.current === authIdentityKey);
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

      const items = Array.isArray(inv.line_items) && inv.line_items.length
        ? inv.line_items
        : [];
      return items.length ? items.map((item) => ({
        vendor,
        vendor_gstin: inv.cashflow_entities?.gstin || inv.party_details?.vendor_gstin || '',
        vendor_address: inv.party_details?.vendor_address || '',
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
        item_name: item.itemName || '',
        description: item.description || '',
        quantity: item.quantity ?? '',
        unit_price: item.unitPrice ?? '',
        line_total: item.lineTotal ?? '',
      })) : [{
        vendor,
        vendor_gstin: inv.cashflow_entities?.gstin || inv.party_details?.vendor_gstin || '',
        vendor_address: inv.party_details?.vendor_address || '',
        bill_number: inv.bill_number || '', bill_date: inv.bill_date || '', due_date: inv.due_date || '', payment_terms_days: inv.payment_terms_days ?? '', balance_due: Number(inv.balance_due || 0).toFixed(2), gross_amount: gross.toFixed(2), gst_amount: gst.toFixed(2), tds_amount: tds.toFixed(2), net_amount: netBeforeGst.toFixed(2), status: inv.status || '', item_name: '', description: '', quantity: '', unit_price: '', line_total: ''
      }];
    }).flat();

    exportRowsAsCsv(
      `ap_report_${now}.csv`,
      [
        { header: 'Vendor', key: 'vendor' },
        { header: 'Vendor GSTIN', key: 'vendor_gstin' },
        { header: 'Vendor Address', key: 'vendor_address' },
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
        { header: 'Item Name', key: 'item_name' },
        { header: 'Description', key: 'description' },
        { header: 'Quantity', key: 'quantity' },
        { header: 'Unit Price', key: 'unit_price' },
        { header: 'Line Total', key: 'line_total' },
      ],
      rows
    );
  };

  const downloadBill = (bill) => {
    const gst = Number(bill.gst_amount || 0);
    const gross = Number(bill.amount || 0);
    const net = Number(bill.amount_before_gst || Math.max(gross - gst, 0));
    const items = Array.isArray(bill.line_items) && bill.line_items.length
      ? bill.line_items
      : [{ itemName: '', description: '', quantity: '', unitPrice: '', lineTotal: net }];
    const rows = items.map((item, index) => `<tr><td>${index + 1}</td><td>${escapeHtml(item.itemName || item.description)}</td><td>${escapeHtml(item.quantity)}</td><td>${escapeHtml(item.unitPrice)}</td><td>${Number(item.discount || 0).toFixed(2)}%</td><td>₹${Number(item.lineTotal || 0).toFixed(3)}</td></tr>`).join('');
    const html = `<!doctype html><html><head><title>Bill ${escapeHtml(bill.bill_number)}</title><style>body{font-family:Arial,sans-serif;color:#172033;padding:28px}h1{margin:0 0 18px}.meta{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:24px}.party{margin-bottom:20px}table{width:100%;border-collapse:collapse}th,td{border:1px solid #172033;padding:8px;text-align:left}th{background:#eef2f7}.right{text-align:right}.totals{margin:20px 0 0 auto;width:300px}.total{font-weight:bold;font-size:16px}</style></head><body><h1>TAX BILL</h1><div class="meta"><div><b>Bill No:</b> ${escapeHtml(bill.bill_number)}</div><div><b>Bill Date:</b> ${escapeHtml(bill.bill_date)}</div><div><b>Due Date:</b> ${escapeHtml(bill.due_date)}</div><div><b>Payment Terms:</b> ${escapeHtml(bill.payment_terms_days)} days</div></div><div class="party"><b>Vendor:</b> ${escapeHtml(bill.cashflow_entities?.name || bill.party_details?.vendor_name)}<br><b>GSTIN:</b> ${escapeHtml(bill.cashflow_entities?.gstin || bill.party_details?.vendor_gstin)}<br><b>Address:</b> ${escapeHtml(bill.party_details?.vendor_address)}</div><table><thead><tr><th>Sl. No.</th><th>Particulars</th><th>Quantity</th><th>Rate</th><th>Discount</th><th>Amount (₹)</th></tr></thead><tbody>${rows}</tbody></table><div class="totals"><div>Net Amount: ₹${net.toFixed(3)}</div><div>GST Amount: ₹${gst.toFixed(3)}</div><div class="total">Gross Total: ₹${gross.toFixed(3)}</div></div><script>window.print()</script></body></html>`;
    const printWindow = window.open('', '_blank', 'width=1000,height=800');
    if (!printWindow) return;
    printWindow.document.open();
    printWindow.document.write(html);
    printWindow.document.close();
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
            <p className="mt-1 text-sm text-muted">Upload PDF, image, or Excel. AI extracts everything automatically.</p>
          <label className="mt-4 inline-block">
            <span className="sr-only">Upload invoice file</span>
            <input
              type="file"
              accept=".pdf,.xls,.xlsx,image/*"
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
                  readOnly={['amount_before_gst', 'gst_amount', 'total_amount'].includes(name)}
                  className={`input-ui h-12 ${['amount_before_gst', 'gst_amount', 'total_amount'].includes(name) ? 'bg-slate-50' : ''}`}
                />
              </div>
            ))}
            <div>
              <label className="label-ui" htmlFor="ap-vendor_address">Vendor Address</label>
              <input id="ap-vendor_address" type="text" name="vendor_address" value={formData.vendor_address} onChange={handleInputChange} placeholder="Optional" className="input-ui h-12" />
            </div>
            <div className="col-span-full">
              <label className="label-ui">Invoice Line Items</label>
              <div className="hidden items-center gap-2 px-1 text-xs font-semibold uppercase tracking-wide text-muted md:grid md:grid-cols-[1.2fr_1.5fr_0.8fr_0.6fr_0.8fr_0.9fr_auto]">
                <span>Item Name</span><span>Description</span><span>Price (₹)</span><span>Qty</span><span>Discount (%)</span><span>Total</span><span aria-hidden="true" />
              </div>
              <div className="grid gap-2">
                {lineItems.map((item, index) => (
                  <div key={`ap-line-item-${index}`} className="grid items-end gap-2 md:grid-cols-[1.2fr_1.5fr_0.8fr_0.6fr_0.8fr_0.9fr_auto]">
                    <input type="text" value={item.itemName} onChange={(e) => updateLineItem(index, 'itemName', e.target.value)} placeholder="Item name" className="input-ui" />
                    <input type="text" value={item.description} onChange={(e) => updateLineItem(index, 'description', e.target.value)} placeholder="Description" className="input-ui" />
                    <input type="number" min="0" step="0.001" value={item.unitPrice || ''} onChange={(e) => updateLineItem(index, 'unitPrice', e.target.value)} placeholder="Price" className="input-ui" />
                    <input type="number" min="0" step="0.001" value={item.quantity || ''} onChange={(e) => updateLineItem(index, 'quantity', e.target.value)} placeholder="Qty" className="input-ui" />
                    <input type="number" min="0" max="100" step="0.01" value={item.discount || ''} onChange={(e) => updateLineItem(index, 'discount', e.target.value)} placeholder="Discount %" className="input-ui" />
                    <input type="number" value={item.lineTotal} readOnly placeholder="Total" className="input-ui bg-slate-50" />
                    {lineItems.length > 1 && <button type="button" onClick={() => setLineItems((previous) => previous.filter((_, itemIndex) => itemIndex !== index))} aria-label={`Remove item ${index + 1}`} className="btn-ui btn-ui-sm btn-ui-danger shrink-0"><Trash2 className="h-3.5 w-3.5" /></button>}
                  </div>
                ))}
              </div>
              <button type="button" onClick={() => setLineItems((previous) => [...previous, { ...emptyLineItem }])} className="btn-ui btn-ui-sm btn-ui-neutral mt-2.5"><Plus className="h-3.5 w-3.5" />Add Another Item</button>
              <div className="mt-4 border-t border-slate-200 pt-3 text-right text-base font-bold text-primary">Subtotal: ₹{subTotal.toFixed(3)}</div>
            </div>
            <div>
              <label className="label-ui" htmlFor="ap-gst_mode">GST Calculation</label>
              <select id="ap-gst_mode" name="gst_mode" value={formData.gst_mode} onChange={handleInputChange} className="input-ui h-12">
                <option value="percentage">Enter GST percentage</option>
                <option value="service">Select service category</option>
              </select>
            </div>
            <div>
              <label className="label-ui" htmlFor="ap-gst_rate">GST Rate (%)</label>
              {formData.gst_mode === 'service' ? (
                <select id="ap-gst_rate" name="gst_rate" value={formData.gst_rate} onChange={handleInputChange} className="input-ui h-12">
                  {GST_SERVICE_RATES.map((rate) => <option key={rate.value} value={rate.value}>{rate.label}</option>)}
                </select>
              ) : (
                <input id="ap-gst_rate" type="number" name="gst_rate" min="0" max="100" step="0.01" value={formData.gst_rate} onChange={handleInputChange} placeholder="Optional" className="input-ui h-12" />
              )}
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

            <div className="col-span-full rounded-xl border-2 border-amber-300 bg-amber-50 px-4 py-3 text-sm font-semibold text-amber-950">Confirm every vendor, invoice number, date, tax field, line item, and total before saving this bill.</div>
            <button type="submit" className="btn-ui btn-ui-primary col-span-full h-12">
              <ShieldCheck className="h-4 w-4" />
              Approve &amp; Save Bill
            </button>
          </form>
        </div>
      </div>

      <div id="ap-bill-list" className="scroll-ui overflow-x-auto rounded-2xl border border-slate-200 bg-white shadow-card">
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
                      <button type="button" onClick={() => downloadBill(inv)} aria-label={`Download bill ${inv.bill_number || inv.id}`} title="Download bill" className="btn-ui btn-ui-sm btn-ui-info">
                        <Download className="h-3.5 w-3.5" />
                      </button>
                      {isAdmin && <><button type="button" onClick={() => startEditBill(inv)} aria-label="Edit bill" title="Edit bill" className="btn-ui btn-ui-sm btn-ui-secondary"><Edit2 className="h-3.5 w-3.5" /></button><button type="button" onClick={() => setAdminTarget({ id: inv.id, action: 'delete' })} aria-label="Delete bill" title="Delete bill" className="btn-ui btn-ui-sm btn-ui-danger"><Trash2 className="h-3.5 w-3.5" /></button></>}
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
                       {['approved', 'overdue'].includes(String(inv.status || '').toLowerCase()) && Number(inv.balance_due ?? gross) > 0 && (
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
        paymentAction="Pay"
        documentLabel="Bill"
        documentNumber={payBill?.bill_number}
        grossAmount={payBill ? Number(payBill.amount || 0) : 0}
        remainingBalance={payBill ? Number(payBill.balance_due ?? payBill.amount ?? 0) : 0}
      />
      <DuplicateDocumentModal
        duplicate={duplicateCandidate}
        onClose={() => setDuplicateCandidate(null)}
        onViewExisting={() => {
          setDuplicateCandidate(null);
          document.getElementById('ap-bill-list')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }}
        onForceSave={async () => {
          setDuplicateCandidate(null);
          await handleSaveInvoice({ preventDefault() {} }, true);
        }}
      />
      <AdminMutationModal action={adminTarget?.action} documentLabel="Bill" onClose={() => setAdminTarget(null)} onConfirm={confirmAdminAction} />
    </div>
  );
}
