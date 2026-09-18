// AccountsReceivable.jsx
// NOTE: Business logic (invoice CRUD, payments, approvals, HTML/CSV export)
// is unchanged from the original implementation. Only the presentation layer
// has been restyled onto the shared design system.

import { useState, useEffect, useRef } from 'react';
import { Download, Edit2, FileUp, Plus, Trash2 } from 'lucide-react';
import { cashflowFetch, parseCashflowResponse } from '../../services/cashflowApi';
import { exportRowsAsCsv } from '../../services/csvExport';
import { useCashflowAuth } from '../../context/CashflowAuthContext';
import { supabase } from '../../services/supabase';
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

const emptyLineItem = {
  itemName: '',
  description: '',
  unitPrice: 0,
  quantity: 1,
  discount: 0,
  lineTotal: 0,
};

const calculateLineTotal = (unitPrice, quantity, discountPercent) => {
  const lineSubtotal = Number(unitPrice || 0) * Number(quantity || 0);
  const discount = Math.min(100, Math.max(0, Number(discountPercent || 0)));
  return Number((lineSubtotal - (lineSubtotal * discount / 100)).toFixed(3));
};

const calculateGlobalDiscountAmount = (subtotal, discountValue, discountMode = 'percentage') => {
  const discount = Math.max(0, Number(discountValue || 0));
  if (discountMode === 'flat') return Math.min(subtotal, discount);
  return subtotal * Math.min(100, discount) / 100;
};

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
  const [ocrLoading, setOcrLoading] = useState(false);
  const [ocrStatus, setOcrStatus] = useState('');
  const [approvingId, setApprovingId] = useState('');
  const [collectInvoice, setCollectInvoice] = useState(null);
  const [duplicateCandidate, setDuplicateCandidate] = useState(null);
  const [adminTarget, setAdminTarget] = useState(null);
  const [editingId, setEditingId] = useState('');
  const [lineItems, setLineItems] = useState([{ ...emptyLineItem }]);
  const subTotal = Number(lineItems.reduce((total, item) => total + Number(item.lineTotal || 0), 0).toFixed(3));
  
  const [formData, setFormData] = useState({
    customer_name: '', customer_gstin: '', customer_address: '', invoice_number: '', invoice_raised_by: '', discount_percent: '',
    invoice_date: new Date().toISOString().split('T')[0], 
    due_date: '', amount: '', gst_amount: '', gst_mode: 'percentage', gst_rate: '18', irn_number: '', notes: '', item_services: ['']
  });

  const grossTotal = Number((subTotal + Number(formData.gst_amount || 0)).toFixed(3));

  useEffect(() => {
    const globalDiscountAmount = calculateGlobalDiscountAmount(
      subTotal,
      formData.discount_percent,
      formData.discount_mode
    );
    const taxableAmount = Math.max(0, subTotal - globalDiscountAmount);
    const gstAmount = taxableAmount * (Math.max(0, Number(formData.gst_rate || 0)) / 100);

    setFormData((previous) => ({
      ...previous,
      amount: subTotal.toFixed(3),
      gst_amount: gstAmount.toFixed(3),
    }));
  }, [subTotal, formData.discount_percent, formData.discount_mode, formData.gst_rate]);

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

  const getInvoiceLineItems = (invoice) => {
    if (Array.isArray(invoice?.line_items) && invoice.line_items.length) return invoice.line_items;
    return getInvoiceItems(invoice).map((item) => ({
      itemName: item,
      description: item,
      quantity: invoice?.quantity || '',
      unitPrice: invoice?.unit_rate || '',
      lineTotal: '',
    }));
  };

  const downloadInvoice = (invoice) => {
    const discountPercent = Math.min(100, Math.max(0, Number(invoice?.discount_percent || 0)));
    // AR persists `amount` as the post-discount taxable value. Reconstruct the
    // gross value only for the invoice presentation so discount is not applied twice.
    const subtotal = Math.max(0, Number(invoice?.amount || 0));
    const grossBeforeDiscount = discountPercent < 100
      ? subtotal / (1 - discountPercent / 100)
      : subtotal;
    const discountAmount = Math.max(0, grossBeforeDiscount - subtotal);
    const gst = Number(invoice?.gst_amount || 0);
    const total = subtotal + gst;
    const items = getInvoiceLineItems(invoice);
    const customer = invoice?.cashflow_entities?.name || '';
    const customerDetails = invoice?.party_details || {};
    const seller = companyDetails;
    const sellerName = seller.legal_name || seller.name || profile?.company_name || '';
    const tax = gst;
    const gstRate = subtotal > 0 ? (gst / subtotal) * 100 : 0;
    const cgst = 0; const sgst = 0; const igst = gst;

    const html = `<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>Invoice ${invoice?.invoice_number || ''}</title>
    <style>
      * { box-sizing: border-box; } body { font-family: Arial, sans-serif; margin: 0; padding: 28px; color: #172033; font-size: 12px; } .invoice { max-width: 900px; margin: auto; border: 1px solid #172033; } .header { display: flex; justify-content: space-between; gap: 24px; padding: 22px; border-bottom: 1px solid #172033; } h1 { margin: 0 0 8px; font-size: 24px; letter-spacing: .08em; } h2 { margin: 0 0 8px; font-size: 17px; } .muted { color: #64748b; line-height: 1.5; } .meta { min-width: 245px; } .meta div, .summary-row { display: flex; justify-content: space-between; gap: 16px; padding: 5px 0; } .section { padding: 16px 22px; border-bottom: 1px solid #172033; } .parties { display: grid; grid-template-columns: 1fr 1fr; gap: 25px; } .party { min-height: 145px; } table { width: 100%; border-collapse: collapse; } th, td { border: 1px solid #172033; padding: 9px 8px; vertical-align: top; } th { background: #eef2f7; text-transform: uppercase; font-size: 10px; letter-spacing: .04em; } .right { text-align: right; } .totals { margin-left: auto; width: 390px; } .grand { font-size: 15px; font-weight: bold; background: #eef2f7; } .tax-table { margin-top: 16px; } .footer-grid { display: grid; grid-template-columns: 1.2fr .8fr; gap: 25px; } .sign { min-height: 75px; text-align: center; padding-top: 35px; } .declaration { line-height: 1.5; } @media print { body { padding: 0; } .invoice { border: 0; } }
    </style>
  </head>
  <body><div class="invoice">
    <div class="header"><div><h2>${escapeHtml(sellerName)}</h2><div class="muted">${escapeHtml(seller.billing_address)}</div><div>${escapeHtml(seller.phone)}</div><div>GSTIN: ${escapeHtml(seller.gstin)}</div><div>PAN: ${escapeHtml(seller.pan)}</div></div><div class="meta"><h1>TAX INVOICE</h1><div><b>Invoice No.</b><span>${escapeHtml(invoice?.invoice_number)}</span></div><div><b>Dated</b><span>${escapeHtml(invoice?.invoice_date)}</span></div><div><b>Due Date</b><span>${escapeHtml(invoice?.due_date)}</span></div><div><b>IRN</b><span>${escapeHtml(invoice?.irn_number)}</span></div></div></div>
    <div class="section parties"><div class="party"><b>Buyer (Bill to):</b><h2>${escapeHtml(customerDetails.customer_name || customer)}</h2><div>Address: ${escapeHtml(customerDetails.customer_address || invoice?.customer_address)}</div><div>GSTIN/UIN: ${escapeHtml(customerDetails.customer_gstin || invoice?.cashflow_entities?.gstin)}</div><div>PAN/IT No: ${escapeHtml(invoice?.customer_pan)}</div></div><div class="party"><b>Place of Supply</b><div>State: ${escapeHtml(invoice?.place_of_supply_state)}</div><div>State Code: ${escapeHtml(invoice?.place_of_supply_code)}</div><br><b>Terms of Payment</b><div>${escapeHtml(invoice?.payment_terms || 'As agreed')}</div></div></div>
    <div class="section"><table>
      <thead>
        <tr><th>Sl. No.</th><th>Particulars</th><th>HSN/SAC</th><th>Quantity</th><th class="right">Rate</th><th class="right">Amount (₹)</th></tr>
      </thead>
      <tbody>
        ${(items.length ? items : [{}]).map((item, index) => `<tr><td>${index + 1}</td><td>${escapeHtml(item.itemName || item.description)}</td><td>${escapeHtml(invoice?.hsn_sac_code || seller.default_hsn_sac)}</td><td>${escapeHtml(item.quantity)}</td><td class="right">${escapeHtml(item.unitPrice)}</td><td class="right">${item.lineTotal !== '' && item.lineTotal !== undefined ? `₹${Number(item.lineTotal).toFixed(3)}` : (index === 0 ? `₹${grossBeforeDiscount.toFixed(3)}` : '')}</td></tr>`).join('')}
      </tbody>
    </table></div><div class="section"><div class="totals"><div class="summary-row"><span>Gross Amount</span><b>₹${grossBeforeDiscount.toFixed(2)}</b></div><div class="summary-row"><span>Discount (${discountPercent.toFixed(2)}%)</span><b>- ₹${discountAmount.toFixed(2)}</b></div><div class="summary-row"><span>Net Taxable Value</span><b>₹${subtotal.toFixed(2)}</b></div><div class="summary-row"><span>CGST</span><span>₹${cgst.toFixed(2)}</span></div><div class="summary-row"><span>SGST</span><span>₹${sgst.toFixed(2)}</span></div><div class="summary-row"><span>IGST (${gstRate.toFixed(2)}%)</span><span>₹${igst.toFixed(2)}</span></div><div class="summary-row"><span>Total Tax Amount</span><b>₹${tax.toFixed(2)}</b></div><div class="summary-row grand"><span>Total</span><span>₹${total.toFixed(2)}</span></div></div><table class="tax-table"><thead><tr><th>HSN/SAC</th><th>Taxable Value</th><th>CGST</th><th>SGST</th><th>IGST</th><th>Total Tax</th></tr></thead><tbody><tr><td>${escapeHtml(invoice?.hsn_sac_code || seller.default_hsn_sac)}</td><td>₹${subtotal.toFixed(2)}</td><td>₹${cgst.toFixed(2)}</td><td>₹${sgst.toFixed(2)}</td><td>₹${igst.toFixed(2)}</td><td>₹${tax.toFixed(2)}</td></tr></tbody></table></div><div class="section footer-grid"><div><b>Amount Chargeable (in words)</b><p>${escapeHtml(amountInWords(total))}</p><b>Tax Amount (in words)</b><p>${escapeHtml(amountInWords(tax))}</p><b>Company's Bank Details</b><p class="muted">Bank: ${escapeHtml(seller.bank_name)}<br>Account Number: ${escapeHtml(seller.bank_account_number)}<br>IFSC Code: ${escapeHtml(seller.bank_ifsc)}</p><p class="declaration"><b>Declaration:</b><br>We declare that this invoice shows the actual price of the goods/services described and that all particulars are true and correct.</p></div><div><b>For ${escapeHtml(sellerName)}</b><div class="sign">Authorised Signatory</div><p class="muted">This is a computer-generated invoice and does not require signature.</p></div></div></div></body>
</html>`;

    const printWindow = window.open('', '_blank', 'width=1000,height=800');
    if (!printWindow) {
      alert('Please allow pop-ups to download the invoice as a PDF.');
      return;
    }

    printWindow.document.open();
    printWindow.document.write(html);
    printWindow.document.close();
    printWindow.document.title = `Invoice ${invoice?.invoice_number || ''}`;
    printWindow.addEventListener('load', () => {
      printWindow.focus();
      printWindow.print();
    }, { once: true });
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
    setFormData(next);
  };

  const updateLineItem = (index, field, value) => {
    setLineItems((previousItems) => previousItems.map((item, itemIndex) => {
      if (itemIndex !== index) return item;

      const updatedItem = {
        ...item,
        [field]: field === 'itemName' || field === 'description' ? value : Number(value || 0),
      };

      return {
        ...updatedItem,
        lineTotal: calculateLineTotal(updatedItem.unitPrice, updatedItem.quantity, updatedItem.discount),
      };
    }));
  };

  const handleInvoiceUpload = (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    const allowedTypes = ['application/pdf', 'application/vnd.ms-excel', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'image/jpeg', 'image/jpg', 'image/png', 'image/tiff', 'image/bmp'];
    if (!allowedTypes.includes((file.type || '').toLowerCase())) {
      setOcrStatus('Unsupported file type. Please upload PDF, Excel, JPG, PNG, TIFF, or BMP.');
      return;
    }
    if (file.size > 15 * 1024 * 1024) {
      setOcrStatus('File is too large. Please upload a file under 15 MB.');
      return;
    }
    setOcrLoading(true);
    setOcrStatus('');
    if (['application/vnd.ms-excel', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'].includes((file.type || '').toLowerCase()) || /\.(xlsx|xls)$/i.test(file.name)) {
      parseInvoiceSpreadsheet(file).then((payload) => {
        const nextLineItems = payload.parsedLineItems?.length ? payload.parsedLineItems : [{ ...emptyLineItem }];
        setLineItems(nextLineItems);
        setFormData((previous) => ({
          ...previous,
          customer_name: payload.customer_name || previous.customer_name,
          customer_gstin: payload.customer_gstin || previous.customer_gstin,
          invoice_number: payload.invoice_number || previous.invoice_number,
          invoice_date: payload.invoice_date || previous.invoice_date,
        }));
        setOcrStatus('Excel invoice uploaded. Please review the extracted details before creating it.');
      }).catch((error) => setOcrStatus(error instanceof Error ? error.message : 'Could not read the Excel invoice.')).finally(() => setOcrLoading(false));
      return;
    }
    const reader = new FileReader();
    reader.onload = async () => {
      try {
        const response = await cashflowFetch('/cashflow/ap/ocr', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ file: reader.result }),
        });
        const parsed = await parseCashflowResponse(response);
        if (!parsed.ok) throw new Error(parsed.error || 'Invoice scan failed.');
        const payload = parsed.data || {};
        const nextLineItems = Array.isArray(payload.parsedLineItems) && payload.parsedLineItems.length
          ? payload.parsedLineItems.map((item) => {
            const unitPrice = Number(Number(item.unitPrice || 0).toFixed(3));
            const quantity = Number(item.quantity || 1);
            const discount = Math.min(100, Math.max(0, Number(item.discount || 0)));

            return {
              itemName: item.itemName || '',
              description: item.description || '',
              unitPrice,
              quantity,
              discount,
              lineTotal: calculateLineTotal(unitPrice, quantity, discount),
            };
          })
          : [{ ...emptyLineItem }];
        setLineItems(nextLineItems);
        setFormData((previous) => ({
          ...previous,
          customer_name: payload.vendor_name || payload.customer_name || previous.customer_name,
          invoice_number: payload.bill_number || payload.invoice_number || previous.invoice_number,
          invoice_date: payload.bill_date || payload.invoice_date || previous.invoice_date,
          amount: payload.amount_before_gst ?? payload.amount ?? previous.amount,
          gst_amount: payload.gst_amount ?? previous.gst_amount,
          notes: payload.notes || previous.notes,
        }));
        setOcrStatus('Invoice uploaded. Please review the extracted details before creating it.');
      } catch (error) {
        setOcrStatus(error instanceof Error ? error.message : 'Invoice scan failed.');
      } finally {
        setOcrLoading(false);
      }
    };
    reader.onerror = () => {
      setOcrLoading(false);
      setOcrStatus('Could not read the invoice file.');
    };
    reader.readAsDataURL(file);
  };

  const handleCreateInvoice = async (e, forceSave = false) => {
    e.preventDefault();
    const requestIdentityKey = authIdentityKey;
    const invoicePayload = {
      ...formData,
      ...(editingId ? { invoice_id: editingId, reason: 'Manual edit', comment: 'Edited from Accounts Receivable' } : { force_save: forceSave }),
      item_services: lineItems.map((item) => item.itemName).filter(Boolean),
      line_items: lineItems,
      party_details: {
        customer_name: formData.customer_name,
        customer_gstin: formData.customer_gstin,
        customer_address: formData.customer_address || '',
      },
    };
    delete invoicePayload.gst_mode;
    delete invoicePayload.gst_rate;
    setSaving(true);
    try {
      const res = await cashflowFetch(editingId ? '/cashflow/ar/update' : '/cashflow/ar/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(invoicePayload)
      });
      const parsed = await parseCashflowResponse(res);
      if (activeIdentityKeyRef.current !== requestIdentityKey) return;
      if (parsed.ok) {
        setInvoices((previousInvoices) => editingId ? previousInvoices.map((item) => item.id === editingId ? parsed.data : item) : [parsed.data, ...previousInvoices]);
        setEditingId('');
        setFormData({ 
            customer_name: '', customer_gstin: '', customer_address: '', invoice_number: '', invoice_raised_by: '', discount_percent: '',
          invoice_date: new Date().toISOString().split('T')[0], 
            due_date: '', amount: '', gst_amount: '', gst_mode: 'percentage', gst_rate: '18', irn_number: '', notes: '', item_services: ['']
        });
          setLineItems([{ ...emptyLineItem }]);
      } else {
        if (parsed.status === 409 && parsed.data?.existing) {
          setDuplicateCandidate({ ...parsed.data, partyName: formData.customer_name });
          return;
        }
        setOcrStatus(parsed.error || 'Unable to save invoice.');
        throw new Error(parsed.error || `Server error ${parsed.status}`);
      }
    } catch (err) {
      console.error("Save Failed:", err);
      alert("Failed to create invoice.");
    } finally {
      if (activeIdentityKeyRef.current === requestIdentityKey) setSaving(false);
    }
  };

  const startEditInvoice = (invoice) => {
    setEditingId(invoice.id);
    setFormData((previous) => ({ ...previous, customer_name: invoice.cashflow_entities?.name || invoice.party_details?.customer_name || '', customer_gstin: invoice.cashflow_entities?.gstin || invoice.party_details?.customer_gstin || '', invoice_number: invoice.invoice_number || '', invoice_date: invoice.invoice_date || '', due_date: invoice.due_date || '', amount: String(invoice.amount || 0), gst_amount: String(invoice.gst_amount || 0), notes: invoice.notes || '' }));
    setLineItems(Array.isArray(invoice.line_items) && invoice.line_items.length ? invoice.line_items : [{ ...emptyLineItem }]);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const confirmAdminAction = async ({ reason, comment }) => {
    if (!adminTarget) return;
    try {
      const response = await cashflowFetch(`/cashflow/ar/${adminTarget.action}`, { method: 'POST', body: JSON.stringify({ invoice_id: adminTarget.id, reason, comment }) });
      const parsed = await parseCashflowResponse(response);
      if (!parsed.ok) throw new Error(parsed.error || `Could not ${adminTarget.action} invoice.`);
      setAdminTarget(null);
      await fetchInvoices(() => activeIdentityKeyRef.current === authIdentityKey);
    } catch (error) {
      setOcrStatus(error instanceof Error ? error.message : 'Could not delete invoice.');
    }
  };

  const handleRecordPayment = async (invoice, paymentAmount) => {
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
        setCollectInvoice(null);
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
      const items = Array.isArray(inv.line_items) && inv.line_items.length
        ? inv.line_items
        : (inv.item_services || []).map((item) => ({ itemName: item, description: item, quantity: '', unitPrice: '', lineTotal: '' }));
      return items.map((item) => ({
        customer: inv.cashflow_entities?.name || 'N/A',
        customer_gstin: inv.cashflow_entities?.gstin || '',
        customer_address: inv.party_details?.customer_address || '',
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
        item_name: item.itemName || '',
        description: item.description || '',
        quantity: item.quantity ?? '',
        unit_price: item.unitPrice ?? '',
        line_total: item.lineTotal ?? '',
      }));
    }).flat();

    exportRowsAsCsv(
      `ar_report_${now}.csv`,
      [
        { header: 'Customer', key: 'customer' },
        { header: 'Customer GSTIN', key: 'customer_gstin' },
        { header: 'Customer Address', key: 'customer_address' },
        { header: 'Invoice Number', key: 'invoice_number' },
        { header: 'Invoice Date', key: 'invoice_date' },
        { header: 'Due Date', key: 'due_date' },
        { header: 'Net Amount', key: 'amount' },
        { header: 'Total Invoice Value', key: 'total_invoice_value' },
        { header: 'Balance Due', key: 'balance_due' },
        { header: 'Status', key: 'status' },
        { header: 'Is Proforma', key: 'is_proforma' },
        { header: 'IRN Number', key: 'irn_number' },
        { header: 'Item Name', key: 'item_name' },
        { header: 'Description', key: 'description' },
        { header: 'Quantity', key: 'quantity' },
        { header: 'Unit Price', key: 'unit_price' },
        { header: 'Line Total', key: 'line_total' },
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
            <label className="label-ui" htmlFor="ar-customer_gstin">Customer GSTIN</label>
            <input id="ar-customer_gstin" type="text" name="customer_gstin" value={formData.customer_gstin} onChange={handleInputChange} placeholder="Optional" className="input-ui" />
          </div>
          <div>
            <label className="label-ui" htmlFor="ar-customer_address">Customer Address</label>
            <input id="ar-customer_address" type="text" name="customer_address" value={formData.customer_address} onChange={handleInputChange} placeholder="Optional" className="input-ui" />
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
            <input id="ar-amount" type="number" name="amount" value={formData.amount} readOnly required className="input-ui bg-slate-50" />
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
            <label className="label-ui" htmlFor="ar-gross_total">Gross Total (₹)</label>
            <input id="ar-gross_total" type="number" value={grossTotal.toFixed(3)} readOnly className="input-ui bg-slate-50" />
            <p className="mt-1 text-xs text-muted">Subtotal plus GST.</p>
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
            <label className="label-ui">Invoice Line Items</label>
            <div className="hidden items-center gap-2 px-1 text-xs font-semibold uppercase tracking-wide text-muted md:grid md:grid-cols-[1.2fr_1.5fr_0.8fr_0.6fr_0.8fr_0.9fr_auto]">
              <span>Item Name</span>
              <span>Description</span>
              <span>Price (₹)</span>
              <span>Qty</span>
              <span>Discount (%)</span>
              <span>Total</span>
              <span aria-hidden="true" />
            </div>
            <div className="grid gap-2">
              {lineItems.map((item, index) => (
                <div key={`line-item-${index}`} className="grid items-end gap-2 md:grid-cols-[1.2fr_1.5fr_0.8fr_0.6fr_0.8fr_0.9fr_auto]">
                  <input
                    type="text"
                    value={item.itemName}
                    onChange={(e) => updateLineItem(index, 'itemName', e.target.value)}
                    placeholder="Item name"
                    className="input-ui"
                  />
                  <input
                    type="text"
                    value={item.description}
                    onChange={(e) => updateLineItem(index, 'description', e.target.value)}
                    placeholder="Description"
                    className="input-ui"
                  />
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    value={item.unitPrice || ''}
                    onChange={(e) => updateLineItem(index, 'unitPrice', e.target.value)}
                    placeholder="Price"
                    className="input-ui"
                  />
                  <input
                    type="number"
                    min="0"
                    step="0.001"
                    value={item.quantity}
                    onChange={(e) => updateLineItem(index, 'quantity', e.target.value)}
                    placeholder="Qty"
                    className="input-ui"
                  />
                  <input
                    type="number"
                    min="0"
                    max="100"
                    step="0.01"
                    value={item.discount || ''}
                    onChange={(e) => updateLineItem(index, 'discount', e.target.value)}
                    placeholder="Discount %"
                    className="input-ui"
                  />
                  <input
                    type="number"
                    value={item.lineTotal}
                    readOnly
                    aria-label={`Line total for item ${index + 1}`}
                    placeholder="Total"
                    className="input-ui bg-slate-50"
                  />
                  {lineItems.length > 1 && (
                    <button
                      type="button"
                      onClick={() => setLineItems((previousItems) => previousItems.filter((_, itemIndex) => itemIndex !== index))}
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
              onClick={() => setLineItems((previousItems) => [...previousItems, { ...emptyLineItem }])}
              className="btn-ui btn-ui-sm btn-ui-neutral mt-2.5"
            >
              <Plus className="h-3.5 w-3.5" />
              Add Another Item
            </button>
            <div className="mt-4 border-t border-slate-200 pt-3 text-right text-base font-bold text-primary">
              Subtotal: ₹{subTotal.toFixed(3)}
            </div>
          </div>

          <div className="col-span-full rounded-xl border-2 border-amber-300 bg-amber-50 px-4 py-3 text-sm font-semibold text-amber-950">Confirm every customer, invoice number, date, tax field, line item, and total before saving this invoice.</div>
          <div className="col-span-full flex flex-wrap items-center gap-2">
            <button type="submit" disabled={saving} className="btn-ui btn-ui-primary h-[45px]">
              {saving ? 'Creating...' : 'Create Invoice'}
            </button>
            <label className={`btn-ui btn-ui-neutral h-[45px] cursor-pointer ${ocrLoading ? 'cursor-wait opacity-60' : ''}`}>
              <FileUp className="h-4 w-4" />
              {ocrLoading ? 'Scanning...' : 'Upload Invoice'}
              <input type="file" accept=".pdf,.xls,.xlsx,image/*" onChange={handleInvoiceUpload} disabled={ocrLoading} className="sr-only" />
            </label>
            {ocrStatus ? <span role="status" className="text-sm font-medium text-muted">{ocrStatus}</span> : null}
          </div>
        </form>
      </div>

      <div id="ar-invoice-list" className="scroll-ui overflow-x-auto rounded-2xl border border-slate-200 bg-white shadow-card">
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
                        {isAdmin && <><button type="button" onClick={() => startEditInvoice(inv)} aria-label="Edit invoice" title="Edit invoice" className="btn-ui btn-ui-sm btn-ui-secondary"><Edit2 className="h-3.5 w-3.5" /></button><button type="button" onClick={() => setAdminTarget({ id: inv.id, action: 'delete' })} aria-label="Delete invoice" title="Delete invoice" className="btn-ui btn-ui-sm btn-ui-danger"><Trash2 className="h-3.5 w-3.5" /></button></>}
                        {inv.status === 'pending' && !inv.is_proforma && isAdmin && (
                          <button
                            onClick={() => handleApproveInvoice(inv.id)}
                            disabled={approvingId === inv.id}
                            className="btn-ui btn-ui-sm btn-ui-secondary"
                          >
                            {approvingId === inv.id ? 'Approving...' : 'Approve'}
                          </button>
                        )}
                        {['approved', 'overdue'].includes(String(inv.status || '').toLowerCase()) && Number(inv.balance_due ?? total) > 0 && !inv.is_proforma && (
                           <button onClick={() => setCollectInvoice(inv)} className="btn-ui btn-ui-sm btn-ui-info">
                            Collect
                          </button>
                        )}
                        <button type="button" onClick={() => downloadInvoice(inv)} aria-label="Download invoice" title="Download invoice" className="btn-ui btn-ui-sm btn-ui-neutral">
                          <Download className="h-3.5 w-3.5" />
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
      <CollectAmountModal
        key={collectInvoice?.id || 'ar-collect'}
        open={Boolean(collectInvoice)}
        onClose={() => setCollectInvoice(null)}
        onConfirm={(amount) => handleRecordPayment(collectInvoice, amount)}
        documentLabel="Invoice"
        paymentAction="Collect"
        documentNumber={collectInvoice?.invoice_number}
        grossAmount={Number(collectInvoice?.amount || 0) + Number(collectInvoice?.gst_amount || 0)}
        remainingBalance={collectInvoice ? Number(collectInvoice.balance_due ?? (Number(collectInvoice.amount || 0) + Number(collectInvoice.gst_amount || 0))) : 0}
      />
      <DuplicateDocumentModal
        duplicate={duplicateCandidate}
        onClose={() => setDuplicateCandidate(null)}
        onViewExisting={() => {
          setDuplicateCandidate(null);
          document.getElementById('ar-invoice-list')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }}
        onForceSave={async () => {
          setDuplicateCandidate(null);
          await handleCreateInvoice({ preventDefault() {} }, true);
        }}
      />
      <AdminMutationModal action={adminTarget?.action} documentLabel="Invoice" onClose={() => setAdminTarget(null)} onConfirm={confirmAdminAction} />
    </div>
  );
}
