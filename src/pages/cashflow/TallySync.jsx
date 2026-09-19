import { useRef, useState } from 'react';
import { ArrowDownToLine, ArrowUpFromLine, CheckCircle2, Download, FileUp, RefreshCw, UploadCloud, XCircle } from 'lucide-react';
import { cashflowFetch } from '../../services/cashflowApi';

const ACCEPTED = '.xml,.json,.xlsx';

function readFileAsBase64(file) {
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

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

async function errorFromResponse(response) {
  const text = await response.text();
  try {
    const payload = JSON.parse(text);
    return payload?.error || payload?.message || `Request failed with status ${response.status}.`;
  } catch {
    return text || `Request failed with status ${response.status}.`;
  }
}

export default function TallySync() {
  const inputRef = useRef(null);
  const [dragging, setDragging] = useState(false);
  const [file, setFile] = useState(null);
  const [progress, setProgress] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [summary, setSummary] = useState(null);

  const chooseFile = (nextFile) => {
    if (!nextFile) return;
    if (!/\.(xml|json|xlsx)$/i.test(nextFile.name)) {
      setError('Choose a Tally XML, JSON, or XLSX file.');
      return;
    }
    setError('');
    setSummary(null);
    setFile(nextFile);
  };

  const importFile = async () => {
    if (!file || busy) return;
    setBusy(true);
    setProgress(10);
    setError('');
    try {
      const fileContentBase64 = await readFileAsBase64(file);
      setProgress(35);
      const response = await cashflowFetch('/tally-sync/import', {
        method: 'POST',
        body: JSON.stringify({ file_name: file.name, file_content_base64: fileContentBase64 }),
      });
      setProgress(80);
      if (!response.ok) throw new Error(await errorFromResponse(response));
      const payload = await response.json();
      if (!payload?.ok) throw new Error(payload?.error || 'Tally import failed.');
      setSummary(payload.data || {});
      setProgress(100);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Tally import failed.');
      setProgress(0);
    } finally {
      setBusy(false);
    }
  };

  const exportFile = async (kind) => {
    setBusy(true);
    setError('');
    try {
      const response = await cashflowFetch(`/tally-sync/export?kind=${encodeURIComponent(kind)}`);
      if (!response.ok) throw new Error(await errorFromResponse(response));
      const filename = kind === 'gst_summary' ? 'GST_Summary.xlsx' : kind === 'sales' ? 'Sales_Vouchers.xml' : 'Bank_Receipts.xml';
      downloadBlob(await response.blob(), filename);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Tally export failed.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="-mx-4 -my-6 min-h-[calc(100vh-5rem)] space-y-6 bg-[linear-gradient(135deg,#f4fbff_0%,#f8fafc_52%,#f4f7ff_100%)] px-4 py-6 sm:-mx-6 sm:px-6 lg:-mx-8 lg:px-8">
      <header className="relative overflow-hidden rounded-2xl border border-cyan-100 bg-white/80 px-5 py-6 shadow-[0_18px_42px_-28px_rgba(14,116,144,.35)] backdrop-blur sm:px-7">
        <div className="absolute right-0 top-0 h-full w-1/3 bg-gradient-to-l from-cyan-50/80 to-transparent" aria-hidden="true" />
        <div className="relative">
          <div className="flex flex-wrap items-center gap-2 text-xs font-bold uppercase tracking-[0.2em] text-cyan-700">CashPulse / Tally Prime 2026</div>
          <h1 className="mt-2 text-3xl font-bold tracking-tight text-primary">Tally Sync</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">Bring compliance data from Tally into your cash flow workspace, then send clean CashPulse records back when your books need them.</p>
          <div className="mt-5 flex flex-wrap gap-2 text-xs font-semibold text-slate-600"><span className="inline-flex items-center gap-1.5 rounded-full border border-cyan-100 bg-cyan-50 px-3 py-1.5 text-cyan-800"><ArrowDownToLine className="h-3.5 w-3.5" /> Import masters & vouchers</span><span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-100 bg-emerald-50 px-3 py-1.5 text-emerald-800"><ArrowUpFromLine className="h-3.5 w-3.5" /> Export to Tally</span></div>
        </div>
      </header>

      {error && <div className="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800" role="alert"><XCircle className="mt-0.5 h-4 w-4 shrink-0" />{error}</div>}

      <div className="grid gap-5 xl:grid-cols-[1.15fr_.85fr]">
        <section className="card-ui overflow-hidden border-t-4 border-cyan-400 p-5 sm:p-6">
          <div className="flex items-start justify-between gap-4"><div><p className="text-[0.68rem] font-bold uppercase tracking-[0.16em] text-cyan-700">Inbound sync</p><h2 className="mt-1 text-xl font-semibold text-primary">Import from Tally</h2><p className="mt-1 text-sm text-slate-600">Upload Ledger Masters, Bills Outstanding, or Daybook / Vouchers.</p></div><span className="rounded-xl bg-cyan-50 p-2.5 text-cyan-600"><UploadCloud className="h-6 w-6" /></span></div>
          <button type="button" onClick={() => inputRef.current?.click()} onDragEnter={(event) => { event.preventDefault(); setDragging(true); }} onDragOver={(event) => event.preventDefault()} onDragLeave={() => setDragging(false)} onDrop={(event) => { event.preventDefault(); setDragging(false); chooseFile(event.dataTransfer.files?.[0]); }} className={`mt-5 flex min-h-48 w-full flex-col items-center justify-center rounded-2xl border-2 border-dashed px-5 text-center transition-colors ${dragging ? 'border-cyan-500 bg-cyan-50 shadow-inner' : 'border-cyan-200 bg-gradient-to-br from-cyan-50/70 to-slate-50 hover:border-cyan-400 hover:from-cyan-50'}`}>
            <span className="grid h-12 w-12 place-items-center rounded-2xl bg-white text-cyan-600 shadow-sm ring-1 ring-cyan-100"><FileUp className="h-6 w-6" /></span><span className="mt-3 text-sm font-semibold text-primary">Drop a Tally file here or browse</span><span className="mt-1 text-xs text-slate-500">XML, JSON, or XLSX</span>{file && <span className="mt-3 rounded-lg border border-cyan-100 bg-white px-3 py-1 text-xs font-medium text-cyan-800 shadow-sm">{file.name}</span>}
          </button>
          <input ref={inputRef} type="file" accept={ACCEPTED} className="hidden" onChange={(event) => chooseFile(event.target.files?.[0])} />
          {busy && progress > 0 && <div className="mt-4" aria-live="polite"><div className="mb-1 flex justify-between text-xs font-semibold text-slate-600"><span>Processing import</span><span>{progress}%</span></div><div className="h-2 overflow-hidden rounded-full bg-slate-200"><div className="h-full rounded-full bg-cyan-500 transition-all" style={{ width: `${progress}%` }} /></div></div>}
          <button type="button" onClick={importFile} disabled={!file || busy} className="btn-ui btn-ui-primary mt-5 w-full"><RefreshCw className={`h-4 w-4 ${busy ? 'animate-spin' : ''}`} />{busy ? 'Syncing…' : 'Import and update dashboard'}</button>
          <div className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950"><p className="font-semibold">Tally Prime 2026 export checklist</p><ol className="mt-2 list-decimal space-y-1 pl-5"><li>Export 'Ledger Masters' from Tally (Alt+E -&gt; Masters) to populate Customers/Vendors.</li><li>Export 'Bills Outstanding' to populate AR/AP tables.</li><li>Export 'Daybook / Vouchers' to train the Cash Runway AI.</li></ol></div>
        </section>

        <section className="card-ui overflow-hidden border-t-4 border-emerald-400 p-5 sm:p-6"><div className="flex items-start justify-between gap-4"><div><p className="text-[0.68rem] font-bold uppercase tracking-[0.16em] text-emerald-700">Outbound sync</p><h2 className="mt-1 text-xl font-semibold text-primary">Export to Tally</h2><p className="mt-1 text-sm text-slate-600">Download CashPulse records in Tally-friendly formats.</p></div><span className="rounded-xl bg-emerald-50 p-2.5 text-emerald-600"><Download className="h-6 w-6" /></span></div><div className="mt-6 space-y-3"><button type="button" disabled={busy} onClick={() => exportFile('sales')} className="btn-ui btn-ui-neutral flex w-full items-center justify-between border-emerald-100 hover:border-emerald-300 hover:bg-emerald-50/60"><span>Export Sales Vouchers</span><Download className="h-4 w-4 text-emerald-600" /></button><button type="button" disabled={busy} onClick={() => exportFile('bank')} className="btn-ui btn-ui-neutral flex w-full items-center justify-between border-emerald-100 hover:border-emerald-300 hover:bg-emerald-50/60"><span>Export Receipts / Payments</span><Download className="h-4 w-4 text-emerald-600" /></button><button type="button" disabled={busy} onClick={() => exportFile('gst_summary')} className="btn-ui btn-ui-neutral flex w-full items-center justify-between border-emerald-100 hover:border-emerald-300 hover:bg-emerald-50/60"><span>Export GST Summary</span><Download className="h-4 w-4 text-emerald-600" /></button></div><p className="mt-5 text-xs text-slate-500">Exports are limited to your current company workspace.</p></section>
      </div>

      {summary && <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4" role="dialog" aria-modal="true" aria-label="Tally import summary"><div className="card-ui w-full max-w-md p-6"><div className="flex items-center gap-3"><CheckCircle2 className="h-7 w-7 text-emerald-600" /><div><h2 className="text-lg font-semibold text-primary">Tally import complete</h2><p className="text-sm text-slate-600">Dashboard metrics have been refreshed.</p></div></div><div className="mt-5 grid grid-cols-2 gap-3 text-center">{[['Imported', summary.imported], ['Updated', summary.updated], ['Skipped', summary.skipped], ['Errors', Array.isArray(summary.errors) ? summary.errors.length : summary.errors]].map(([label, value]) => <div key={label} className="rounded-xl bg-slate-50 p-3"><p className="text-2xl font-bold text-primary">{Number(value || 0)}</p><p className="text-xs text-slate-500">{label}</p></div>)}</div>{summary.errors?.length ? <div className="mt-4 rounded-xl border border-rose-200 bg-rose-50 p-3 text-left"><p className="text-sm font-semibold text-rose-900">Voucher errors</p><ul className="mt-2 max-h-32 space-y-1 overflow-auto text-xs text-rose-800">{summary.errors.map((item) => <li key={`${item.voucherNo}-${item.error}`}><strong>{item.voucherNo}</strong>: {item.error}</li>)}</ul></div> : null}{summary.duplicates?.length ? <p className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">{summary.duplicates.length} voucher{summary.duplicates.length === 1 ? '' : 's'} already existed and was not duplicated. Matching used Tally REMOTEID where available.</p> : null}<p className="mt-4 text-sm text-slate-600">AR: {Number(summary.dashboard?.total_accounts_receivable || 0).toLocaleString('en-IN')} · AP: {Number(summary.dashboard?.total_accounts_payable || 0).toLocaleString('en-IN')}</p><button type="button" onClick={() => setSummary(null)} className="btn-ui btn-ui-primary mt-5 w-full">Close summary</button></div></div>}
    </div>
  );
}
