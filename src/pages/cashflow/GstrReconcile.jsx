import { useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, Download, FileSpreadsheet, Mail, Play, Plus, UploadCloud, X, XCircle } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { cashflowFetch } from '../../services/cashflowApi';
import { useCashflowAuth } from '../../context/CashflowAuthContext';

function toBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const value = String(reader.result || '');
      resolve(value.includes(',') ? value.split(',')[1] : value);
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

function monthKey() {
  const now = new Date();
  return `${String(now.getMonth() + 1).padStart(2, '0')}${now.getFullYear()}`;
}

function money(value) {
  return `₹${Number(value || 0).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;
}

function taxTotal(row) {
  const source = row?.gstr2b || row?.books || row || {};
  return Number(source.igst || source.igst_amount || 0) + Number(source.cgst || source.cgst_amount || 0) + Number(source.sgst || source.sgst_amount || 0);
}

function recordLabel(row) {
  return row?.books?.invoice_number || row?.gstr2b?.invoice_number || row?.invoice_number || '—';
}

const TONES = {
  emerald: { card: 'border-emerald-200 bg-emerald-50', icon: 'text-emerald-600', label: 'text-emerald-800' },
  amber: { card: 'border-amber-200 bg-amber-50', icon: 'text-amber-600', label: 'text-amber-800' },
  rose: { card: 'border-rose-200 bg-rose-50', icon: 'text-rose-600', label: 'text-rose-800' },
  sky: { card: 'border-sky-200 bg-sky-50', icon: 'text-sky-600', label: 'text-sky-800' },
};

export default function GstrReconcile() {
  const { profile } = useCashflowAuth();
  const navigate = useNavigate();
  const [files, setFiles] = useState([]);
  const [period, setPeriod] = useState(monthKey);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);
  const [activeTab, setActiveTab] = useState('all');
  const [expandedMismatch, setExpandedMismatch] = useState(null);
  const [notice, setNotice] = useState('');

  const chooseFiles = (selected) => {
    const next = Array.from(selected || []).filter((file) => /\.(json|xlsx)$/i.test(file.name));
    setFiles(next);
    setResult(null);
    setError(next.length === selected?.length ? '' : 'Only GSTR-2B JSON and XLSX files are supported.');
  };

  const reconcile = async () => {
    if (!files.length) return setError('Select at least one GSTR-2B JSON or XLSX file.');
    if (!/^\d{6}$/.test(period)) return setError('Period must use MMYYYY format, for example 032026.');
    setBusy(true); setError('');
    try {
      const payload = await Promise.all(files.map(async (file) => ({ filename: file.name, file_type: file.name.toLowerCase().endsWith('.xlsx') ? 'xlsx' : 'json', content: await toBase64(file) })));
      const response = await cashflowFetch('/gstr/reconcile', { method: 'POST', body: JSON.stringify({ client_id: profile?.company_id, period, files: payload }) });
      const body = await response.json();
      if (!response.ok || !body?.ok) throw new Error(body?.error || 'GSTR reconciliation failed.');
      setResult(body.data);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'GSTR reconciliation failed.');
    } finally { setBusy(false); }
  };

  const metrics = useMemo(() => {
    if (!result) return null;
    const portalRows = [...(result.matched || []), ...(result.tax_mismatches || []), ...(result.missing_in_books || [])];
    const bookRows = [...(result.matched || []), ...(result.tax_mismatches || []), ...(result.missing_in_2b || [])];
    const portalItc = portalRows.reduce((sum, row) => sum + taxTotal(row.gstr2b || row), 0);
    const bookItc = bookRows.reduce((sum, row) => sum + taxTotal(row.books || row), 0);
    const safe = (result.matched || []).reduce((sum, row) => sum + taxTotal(row.gstr2b || row), 0);
    const atRisk = (result.missing_in_2b || []).reduce((sum, row) => sum + taxTotal(row.books || row), 0) + (result.tax_mismatches || []).reduce((sum, row) => sum + Number(row.tax_variance || Math.abs(taxTotal(row.gstr2b || row) - taxTotal(row.books || row))), 0);
    return { portalItc, bookItc, safe, atRisk };
  }, [result]);

  const tabRows = useMemo(() => {
    if (!result) return [];
    if (activeTab === 'all') return Object.entries({ matched: result.matched, tax_mismatches: result.tax_mismatches, missing_in_2b: result.missing_in_2b, missing_in_books: result.missing_in_books }).flatMap(([bucket, rows]) => (rows || []).map((row) => ({ ...row, bucket })));
    return (result[activeTab] || []).map((row) => ({ ...row, bucket: activeTab }));
  }, [activeTab, result]);

  const sendReminder = async (row) => {
    const book = row.books || row;
    const response = await cashflowFetch('/vendors/remind', { method: 'POST', body: JSON.stringify({ vendor_name: book.vendor_name || book.cashflow_entities?.name || '', invoice_number: recordLabel(row) }) });
    if (!response.ok) throw new Error('Could not send vendor reminder.');
    setNotice(`Reminder queued for ${recordLabel(row)}.`);
  };

  const addToAp = (row) => {
    const portal = row.gstr2b || row;
    navigate('/cashflow/ap', { state: { gstrPrefill: { vendor_gstin: portal.supplier_gstin, bill_number: portal.invoice_number, bill_date: portal.invoice_date, amount_before_gst: portal.taxable_value, gst_amount: taxTotal(portal), total_amount: Number(portal.taxable_value || 0) + taxTotal(portal) } } });
  };

  const exportReport = async () => {
    if (!result) return;
    setBusy(true); setError('');
    try {
      const response = await cashflowFetch('/gstr/reconcile/export', { method: 'POST', body: JSON.stringify({ period, result }) });
      if (!response.ok) throw new Error('Could not generate GST audit report.');
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement('a'); anchor.href = url; anchor.download = `gstr_report_${period}.xlsx`; anchor.click(); URL.revokeObjectURL(url);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Could not generate GST audit report.');
    } finally { setBusy(false); }
  };

  const buckets = result ? [
    { key: 'matched', label: 'Matched', tone: 'emerald', icon: CheckCircle2 },
    { key: 'tax_mismatches', label: 'Tax mismatches', tone: 'amber', icon: AlertTriangle },
    { key: 'missing_in_2b', label: 'Missing in 2B', tone: 'rose', icon: XCircle },
    { key: 'missing_in_books', label: 'Missing in books', tone: 'sky', icon: FileSpreadsheet },
  ] : [];

  return (
    <div className="-mx-4 -my-6 min-h-[calc(100vh-5rem)] space-y-6 bg-[linear-gradient(135deg,#f4fbff_0%,#f8fafc_52%,#f4f7ff_100%)] px-4 py-6 sm:-mx-6 sm:px-6 lg:-mx-8 lg:px-8">
      <header className="rounded-2xl border border-cyan-100 bg-white/85 px-5 py-6 shadow-[0_18px_42px_-28px_rgba(14,116,144,.35)] sm:px-7">
        <p className="text-xs font-bold uppercase tracking-[0.2em] text-cyan-700">GST compliance / Input Tax Credit</p>
        <h1 className="mt-2 text-3xl font-bold tracking-tight text-primary">GSTR-2B Reconcile</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">Compare portal purchases with CashPulse AP records across one or more GSTINs and periods.</p>
      </header>

      {error && <div className="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800" role="alert"><XCircle className="mt-0.5 h-4 w-4 shrink-0" />{error}</div>}

      <section className="card-ui border-t-4 border-cyan-400 p-5 sm:p-6">
        <div className="flex items-start justify-between gap-4"><div><p className="text-[0.68rem] font-bold uppercase tracking-[0.16em] text-cyan-700">Portal data</p><h2 className="mt-1 text-xl font-semibold text-primary">Upload GSTR-2B files</h2><p className="mt-1 text-sm text-slate-600">Select multiple monthly JSON/XLSX downloads. Files are deduplicated before matching.</p></div><span className="rounded-xl bg-cyan-50 p-2.5 text-cyan-600"><UploadCloud className="h-6 w-6" /></span></div>
        <div className="mt-5 grid gap-4 md:grid-cols-[1fr_10rem_auto] md:items-end">
          <label className="block"><span className="label-ui">GSTR-2B JSON/XLSX files</span><input type="file" multiple accept=".json,.xlsx" onChange={(event) => chooseFiles(event.target.files)} className="input-ui mt-1 w-full file:mr-3 file:rounded-lg file:border-0 file:bg-cyan-700 file:px-3 file:py-2 file:font-semibold file:text-white" /></label>
          <label className="block"><span className="label-ui">Tax period</span><input value={period} onChange={(event) => setPeriod(event.target.value)} inputMode="numeric" maxLength={6} placeholder="032026" className="input-ui mt-1 w-full" /></label>
          <button type="button" onClick={reconcile} disabled={busy || !files.length} className="btn-ui btn-ui-primary h-12"><Play className="h-4 w-4" />{busy ? 'Reconciling…' : 'Run reconciliation'}</button>
        </div>
        {files.length > 0 && <div className="mt-4 flex flex-wrap gap-2">{files.map((file) => <span key={`${file.name}-${file.size}`} className="rounded-lg border border-cyan-100 bg-cyan-50 px-3 py-1.5 text-xs font-medium text-cyan-900">{file.name}</span>)}</div>}
      </section>

      {result && <section className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {[['Total GSTR-2B ITC', metrics.portalItc, 'sky'], ['Total Book ITC', metrics.bookItc, 'indigo'], ['Matched & Safe ITC', metrics.safe, 'emerald'], ['ITC At Risk', metrics.atRisk, 'rose']].map(([label, value, tone]) => <div key={label} className={`rounded-2xl border p-5 ${TONES[tone === 'indigo' ? 'sky' : tone].card}`}><p className="text-xs font-bold uppercase tracking-[0.14em] text-slate-500">{label}</p><p className="mt-3 text-2xl font-bold text-primary">{money(value)}</p><p className="mt-1 text-xs text-slate-500">Input tax credit</p></div>)}
        </div>
        <div className="card-ui overflow-hidden p-0"><div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-5 py-4"><div><h2 className="text-lg font-semibold text-primary">Exception board</h2><p className="mt-1 text-xs text-slate-500">{result.files_processed} files · {result.portal_records} portal records</p></div><button type="button" onClick={exportReport} className="btn-ui btn-ui-neutral"><Download className="h-4 w-4" />Export Audit Report</button></div><div className="flex gap-1 overflow-x-auto border-b border-slate-200 px-4 pt-3">{[['all','All'],['matched','Matched 🟢'],['tax_mismatches','Tax Mismatches 🟠'],['missing_in_2b','Missing in 2B 🔴'],['missing_in_books','Missing in Books 🟡']].map(([key,label]) => <button key={key} type="button" onClick={() => setActiveTab(key)} className={`whitespace-nowrap rounded-t-lg px-3 py-2 text-sm font-semibold ${activeTab === key ? 'border-b-2 border-cyan-600 text-cyan-700' : 'text-slate-500 hover:text-primary'}`}>{label}</button>)}</div><div className="overflow-x-auto"><table className="w-full min-w-[760px] text-left text-sm"><thead className="bg-slate-50 text-xs uppercase tracking-wider text-slate-500"><tr><th className="px-5 py-3">Invoice</th><th className="px-5 py-3">GSTIN</th><th className="px-5 py-3">Date</th><th className="px-5 py-3">Portal Tax</th><th className="px-5 py-3">Book Tax</th><th className="px-5 py-3">Status</th><th className="px-5 py-3">Action</th></tr></thead><tbody className="divide-y divide-slate-100">{tabRows.map((row, index) => { const portal = row.gstr2b || row; const book = row.books || row; const status = row.bucket; return <tr key={`${recordLabel(row)}-${index}`} className="hover:bg-cyan-50/40"><td className="px-5 py-3 font-semibold text-primary">{recordLabel(row)}</td><td className="px-5 py-3 text-xs text-slate-600">{portal.supplier_gstin || book.supplier_gstin || '—'}</td><td className="px-5 py-3 text-xs text-slate-600">{portal.invoice_date || book.invoice_date || '—'}</td><td className="px-5 py-3 tabular-nums">{money(taxTotal(portal))}</td><td className="px-5 py-3 tabular-nums">{money(taxTotal(book))}</td><td className="px-5 py-3"><span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${status === 'matched' ? 'bg-emerald-100 text-emerald-800' : status === 'tax_mismatches' ? 'bg-amber-100 text-amber-800' : status === 'missing_in_2b' ? 'bg-rose-100 text-rose-800' : 'bg-sky-100 text-sky-800'}`}>{status === 'tax_mismatches' ? `Variance ${money(row.tax_variance)}` : status.replaceAll('_', ' ')}</span></td><td className="px-5 py-3">{status === 'missing_in_2b' && <button type="button" onClick={() => sendReminder(row).catch((nextError) => setError(nextError.message))} className="btn-ui btn-ui-sm btn-ui-neutral"><Mail className="h-3.5 w-3.5" />Send Reminder</button>}{status === 'missing_in_books' && <button type="button" onClick={() => addToAp(row)} className="btn-ui btn-ui-sm btn-ui-primary"><Plus className="h-3.5 w-3.5" />Add to AP</button>}{status === 'tax_mismatches' && <button type="button" onClick={() => setExpandedMismatch(expandedMismatch === index ? null : index)} className="btn-ui btn-ui-sm btn-ui-neutral">Compare</button>}</td></tr>})}</tbody></table></div>{expandedMismatch !== null && tabRows[expandedMismatch]?.bucket === 'tax_mismatches' && <div className="border-t border-amber-200 bg-amber-50/60 px-5 py-4 text-sm text-amber-950">Books Tax <strong>{money(taxTotal(tabRows[expandedMismatch].books))}</strong> · Portal Tax <strong>{money(taxTotal(tabRows[expandedMismatch].gstr2b))}</strong> · Variance <strong>{money(tabRows[expandedMismatch].tax_variance)}</strong></div>}</div>
      </section>}
      {notice && <div className="fixed bottom-5 right-5 z-50 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm font-semibold text-emerald-800 shadow-lg">{notice}<button type="button" onClick={() => setNotice('')} className="ml-3"><X className="inline h-4 w-4" /></button></div>}
    </div>
  );
}
