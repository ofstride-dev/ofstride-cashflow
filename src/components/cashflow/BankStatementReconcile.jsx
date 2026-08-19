import React, { useMemo, useState } from 'react';
import { cashflowFetch } from '../../services/cashflowApi';

async function readErrorMessage(res) {
  const contentType = (res.headers.get('content-type') || '').toLowerCase();
  const raw = await res.text();

  if (!raw) {
    return `Request failed with status ${res.status}.`;
  }

  if (contentType.includes('application/json')) {
    try {
      const payload = JSON.parse(raw);
      return payload?.error || payload?.message || `Request failed with status ${res.status}.`;
    } catch {
      return `Request failed with status ${res.status}.`;
    }
  }

  return raw.slice(0, 240);
}

async function parseJsonBodySafe(res) {
  const raw = await res.text();
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function readFileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result || '');
      const base64 = result.includes(',') ? result.split(',')[1] : result;
      resolve(base64);
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

function statusTone(status) {
  if (status === 'matched') return 'bg-emerald-50 text-emerald-700 border-emerald-200';
  if (status === 'amount_mismatch') return 'bg-amber-50 text-amber-700 border-amber-200';
  if (status === 'missing_in_bank_statement') return 'bg-rose-50 text-rose-700 border-rose-200';
  return 'bg-slate-100 text-slate-700 border-slate-200';
}

export default function BankStatementReconcile() {
  const today = useMemo(() => new Date().toISOString().slice(0, 10), []);
  const monthStart = useMemo(() => {
    const dt = new Date();
    dt.setDate(1);
    return dt.toISOString().slice(0, 10);
  }, []);

  const [startDate, setStartDate] = useState(monthStart);
  const [endDate, setEndDate] = useState(today);
  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [summary, setSummary] = useState(null);
  const [runId, setRunId] = useState('');
  const [rows, setRows] = useState([]);
  const [uploadedRows, setUploadedRows] = useState([]);
  const [columnWarnings, setColumnWarnings] = useState([]);
  const [rowIssuesCount, setRowIssuesCount] = useState(0);
  const [comparisonMode, setComparisonMode] = useState('');

  const onFileChange = (e) => {
    const next = e.target.files?.[0] || null;
    setFile(next);
    setError('');
  };

  const runReconcile = async (compareWithPlatform = false) => {
    if (!startDate || !endDate) {
      setError('Please select start and end dates.');
      return;
    }
    if (startDate > endDate) {
      setError('Start date cannot be later than end date.');
      return;
    }
    if (!file) {
      setError('Please upload a bank statement CSV, Excel, or PDF file first.');
      return;
    }

    setLoading(true);
    setError('');

    try {
      const fileBase64 = await readFileAsBase64(file);
      const res = await cashflowFetch('/reconcile/bank/analyze', {
        method: 'POST',
        body: JSON.stringify({
          start_date: startDate,
          end_date: endDate,
          file_name: file.name,
          file_content_base64: fileBase64,
          compare_with_platform: compareWithPlatform,
        }),
      });

      if (!res.ok) {
        throw new Error(await readErrorMessage(res));
      }

      const payload = await parseJsonBodySafe(res);
      if (!payload?.success) {
        throw new Error(payload?.error || 'Reconcile request did not return a valid success payload.');
      }

      setSummary(payload.data?.summary || null);
      setRows(payload.data?.sample_mismatches || []);
      setRunId(payload.data?.run_id || '');
      setUploadedRows(payload.data?.uploaded_rows || []);
      setColumnWarnings(payload.data?.column_warnings || []);
      setRowIssuesCount(Number(payload.data?.row_issues_count || 0));
      setComparisonMode(payload.data?.comparison_mode || '');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Reconcile failed.');
    } finally {
      setLoading(false);
    }
  };

  const downloadCsv = async (kind) => {
    if (!runId) return;
    setLoading(true);
    setError('');
    try {
      const res = await cashflowFetch(`/reconcile/bank/export?run_id=${encodeURIComponent(runId)}&kind=${encodeURIComponent(kind)}`, {
        method: 'GET',
      });

      if (!res.ok) {
        throw new Error(await readErrorMessage(res));
      }

      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `bank_reconcile_${kind}_${runId}.csv`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not download CSV.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-5">
      <section className="rounded-2xl border border-slate-200 bg-white p-5 sm:p-6 shadow-sm">
        <h2 className="text-2xl font-bold text-primary">Bank Statement Reconcile</h2>
        <p className="text-sm text-slate-600 mt-1">
          Compare uploaded bank receipts, transactions, and statements with AP, AR, and Petty Cash records to identify mismatches before final posting.
        </p>

        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3 mt-4">
          <div>
            <label className="block text-sm font-medium text-primary mb-1">Start Date</label>
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-primary mb-1">End Date</label>
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm"
            />
          </div>
          <div className="sm:col-span-2">
            <label className="block text-sm font-medium text-primary mb-1">Bank Statement File (.csv, .xlsx, .pdf)</label>
            <input
              type="file"
              accept=".csv,.xlsx,.xls,.pdf"
              onChange={onFileChange}
              className="w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm bg-white"
            />
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => runReconcile(false)}
            disabled={loading}
            className="px-4 py-2 rounded-xl bg-primary text-white text-sm font-semibold disabled:opacity-60"
          >
            {loading ? 'Processing...' : 'Run Statement Parse'}
          </button>
          {file && (
            <button
              type="button"
              onClick={() => runReconcile(true)}
              disabled={loading}
              className="px-4 py-2 rounded-xl border border-blue-200 bg-blue-50 text-secondary text-sm font-semibold hover:bg-blue-100 disabled:opacity-60"
            >
              {loading ? 'Processing...' : 'Run + Compare with AP/AR'}
            </button>
          )}
          {runId && (
            <>
              <button
                type="button"
                onClick={() => downloadCsv('mismatch')}
                disabled={loading}
                className="px-4 py-2 rounded-xl border border-slate-200 bg-white text-sm font-medium text-text"
              >
                Download Mismatches CSV
              </button>
              <button
                type="button"
                onClick={() => downloadCsv('corrected')}
                disabled={loading}
                className="px-4 py-2 rounded-xl border border-blue-200 bg-blue-50 text-sm font-medium text-secondary"
              >
                Download Corrected Suggestions
              </button>
            </>
          )}
        </div>

        {(columnWarnings.length > 0 || rowIssuesCount > 0) && (
          <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
            <p className="font-semibold">Uploaded report has validation flags, but it is still visible for review.</p>
            {columnWarnings.length > 0 && (
              <ul className="list-disc ml-5 mt-1 space-y-0.5">
                {columnWarnings.map((warn, idx) => (
                  <li key={`${warn}-${idx}`}>{warn}</li>
                ))}
              </ul>
            )}
            {rowIssuesCount > 0 && (
              <p className="mt-1">{rowIssuesCount} row(s) have missing/invalid fields. We can review and correct these for you.</p>
            )}
          </div>
        )}

        {comparisonMode && (
          <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">
            <span className="font-semibold">Mode:</span>{' '}
            {comparisonMode === 'platform' ? 'Platform comparison enabled (AP/AR/Petty Cash).' : 'Bank statement only.'}
          </div>
        )}

        {error && (
          <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </div>
        )}
      </section>

      {summary && (
        <section className="rounded-2xl border border-slate-200 bg-white p-5 sm:p-6 shadow-sm">
          <h3 className="text-lg font-semibold text-primary">Reconcile Summary</h3>
          <div className="mt-3 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2 text-sm">
            <div className="rounded-xl border border-slate-200 px-3 py-2 bg-slate-50">
              <p className="text-slate-500">Bank Statement Rows</p>
              <p className="text-lg font-semibold text-primary">{summary.total_bank_rows || 0}</p>
            </div>
            <div className="rounded-xl border border-slate-200 px-3 py-2 bg-slate-50">
              <p className="text-slate-500">Platform Rows</p>
              <p className="text-lg font-semibold text-primary">{summary.total_platform_rows || 0}</p>
            </div>
            <div className="rounded-xl border border-emerald-200 px-3 py-2 bg-emerald-50">
              <p className="text-emerald-700">Matched</p>
              <p className="text-lg font-semibold text-emerald-700">{summary.matched || 0}</p>
            </div>
            <div className="rounded-xl border border-amber-200 px-3 py-2 bg-amber-50">
              <p className="text-amber-700">Amount Mismatch</p>
              <p className="text-lg font-semibold text-amber-700">{summary.amount_mismatch || 0}</p>
            </div>
            <div className="rounded-xl border border-rose-200 px-3 py-2 bg-rose-50">
              <p className="text-rose-700">Missing In Bank Statement</p>
              <p className="text-lg font-semibold text-rose-700">{summary.missing_in_bank_statement || 0}</p>
            </div>
            <div className="rounded-xl border border-slate-200 px-3 py-2 bg-slate-100">
              <p className="text-slate-700">Unexpected In Bank Statement</p>
              <p className="text-lg font-semibold text-slate-700">{summary.unexpected_in_bank_statement || 0}</p>
            </div>
          </div>
        </section>
      )}

      {rows.length > 0 && (
        <section className="rounded-2xl border border-slate-200 bg-white p-5 sm:p-6 shadow-sm">
          <h3 className="text-lg font-semibold text-primary">Mismatch Samples</h3>
          <div className="mt-3 overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="text-left text-slate-500 border-b border-slate-100">
                  <th className="px-2 py-2">Reference</th>
                  <th className="px-2 py-2">Date</th>
                  <th className="px-2 py-2">Party</th>
                  <th className="px-2 py-2 text-right">Amount</th>
                  <th className="px-2 py-2">Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row, idx) => (
                  <tr key={`${row.voucher_number || 'row'}-${idx}`} className="border-b border-slate-100 last:border-b-0">
                    <td className="px-2 py-2 font-medium text-primary">{row.voucher_number || '-'}</td>
                    <td className="px-2 py-2 text-slate-700">{row.voucher_date || '-'}</td>
                    <td className="px-2 py-2 text-slate-700">{row.party_name || '-'}</td>
                    <td className="px-2 py-2 text-right text-slate-700">{Number(row.amount || 0).toLocaleString('en-IN', { maximumFractionDigits: 2 })}</td>
                    <td className="px-2 py-2">
                      <span className={`inline-flex px-2 py-1 rounded-full border text-xs font-medium ${statusTone(row.status)}`}>
                        {row.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {uploadedRows.length > 0 && (
        <section className="rounded-2xl border border-slate-200 bg-white p-5 sm:p-6 shadow-sm">
          <div className="flex items-start justify-between gap-3 flex-wrap">
            <h3 className="text-lg font-semibold text-primary">Uploaded Report Preview</h3>
            {rowIssuesCount > 0 && (
              <span className="inline-flex px-2.5 py-1 rounded-full border border-amber-200 bg-amber-50 text-amber-700 text-xs font-semibold">
                {rowIssuesCount} flagged row(s)
              </span>
            )}
          </div>
          <p className="text-sm text-slate-600 mt-1">
            Report is shown even with errors. Flagged rows include suggestions so your team can review or use our assisted correction workflow.
          </p>

          <div className="mt-3 overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="text-left text-slate-500 border-b border-slate-100">
                  <th className="px-2 py-2">Row</th>
                  <th className="px-2 py-2">Reference</th>
                  <th className="px-2 py-2">Date</th>
                  <th className="px-2 py-2">Party</th>
                  <th className="px-2 py-2 text-right">Amount</th>
                  <th className="px-2 py-2">Validation</th>
                </tr>
              </thead>
              <tbody>
                {uploadedRows.map((row, idx) => {
                  const issues = Array.isArray(row.validation_issues) ? row.validation_issues : [];
                  const hasIssues = issues.length > 0;

                  return (
                    <tr key={`upload-${idx}`} className="border-b border-slate-100 last:border-b-0">
                      <td className="px-2 py-2 text-slate-700">{row.row_number || idx + 2}</td>
                      <td className="px-2 py-2 font-medium text-primary">{row.voucher_number || '-'}</td>
                      <td className="px-2 py-2 text-slate-700">{row.voucher_date || '-'}</td>
                      <td className="px-2 py-2 text-slate-700">{row.party_name || '-'}</td>
                      <td className="px-2 py-2 text-right text-slate-700">{Number(row.amount || 0).toLocaleString('en-IN', { maximumFractionDigits: 2 })}</td>
                      <td className="px-2 py-2">
                        {hasIssues ? (
                          <div className="space-y-1">
                            <span className="inline-flex px-2 py-1 rounded-full border border-amber-200 bg-amber-50 text-amber-700 text-xs font-medium">
                              Needs review
                            </span>
                            <div className="text-xs text-amber-800">
                              {issues.join('; ')}
                            </div>
                            <div className="text-xs text-slate-600">
                              {row.suggested_correction || 'We can review and correct this row for you.'}
                            </div>
                          </div>
                        ) : (
                          <span className="inline-flex px-2 py-1 rounded-full border border-emerald-200 bg-emerald-50 text-emerald-700 text-xs font-medium">
                            Looks valid
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
