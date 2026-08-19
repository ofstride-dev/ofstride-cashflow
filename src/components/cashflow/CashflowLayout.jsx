import React, { useMemo, useState } from 'react';
import { Link, Navigate, Outlet, useLocation } from 'react-router-dom';
import { Download, X } from 'lucide-react';
import { cashflowFetch } from '../../services/cashflowApi';
import { useCashflowAuth } from '../../context/CashflowAuthContext';

function CashflowShell() {
  const { session, profile, signOut, isAdmin, loading } = useCashflowAuth();

  const location = useLocation();
  const isLoginRoute = location.pathname.replace(/\/$/, '') === '/cashflow/login';
  const [isExportOpen, setIsExportOpen] = useState(false);
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [isDownloading, setIsDownloading] = useState(false);
  const [exportError, setExportError] = useState('');

  const today = useMemo(() => {
    const dt = new Date();
    return dt.toISOString().slice(0, 10);
  }, []);

  const monthStart = useMemo(() => {
    const dt = new Date();
    dt.setDate(1);
    return dt.toISOString().slice(0, 10);
  }, []);

  const openExportModal = () => {
    setStartDate((prev) => prev || monthStart);
    setEndDate((prev) => prev || today);
    setExportError('');
    setIsExportOpen(true);
  };

  const closeExportModal = () => {
    if (isDownloading) return;
    setIsExportOpen(false);
    setExportError('');
  };

  const handleDownload = async () => {
    if (!startDate || !endDate) {
      setExportError('Please select both start and end dates.');
      return;
    }
    if (startDate > endDate) {
      setExportError('Start date must be earlier than or equal to end date.');
      return;
    }

    const endpoint = '/export/gstr';
    const params = new URLSearchParams({
      start_date: startDate,
      end_date: endDate,
    });

    setIsDownloading(true);
    setExportError('');

    try {
      const res = await cashflowFetch(`${endpoint}?${params.toString()}`, {
        method: 'GET',
      });

      if (!res.ok) {
        const contentType = res.headers.get('content-type') || '';
        if (contentType.includes('application/json')) {
          const payload = await res.json();
          throw new Error(payload?.error || payload?.message || 'Export failed.');
        }
        const text = await res.text();
        throw new Error(text || `Export failed with status ${res.status}.`);
      }

      const blob = await res.blob();
      const filename = `gstr_report_${startDate}_to_${endDate}.xlsx`;

      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);

      setIsExportOpen(false);
    } catch (error) {
      setExportError(error instanceof Error ? error.message : 'Export failed. Please try again.');
    } finally {
      setIsDownloading(false);
    }
  };

  const navItems = [
    { label: 'Dashboard', path: '/cashflow/dashboard' },
    { label: 'Payables (AP)', path: '/cashflow/ap' },
    { label: 'Receivables (AR)', path: '/cashflow/ar' },
    { label: 'Petty Cash', path: '/cashflow/pettycash' },
    { label: 'Bank Statement Reconcile', path: '/cashflow/reconcile' },
    { label: 'Expense Portal', path: '/cashflow/expense' },
  ];

  const isActivePath = (path) => {
    if (path === '/cashflow/expense') {
      return location.pathname.startsWith('/cashflow/expense');
    }
    return location.pathname === path;
  };

  if (isLoginRoute) {
    return (
      <div className="pt-12 sm:pt-16 min-h-screen bg-[radial-gradient(circle_at_0%_0%,rgba(56,189,248,0.10),transparent_40%),radial-gradient(circle_at_100%_100%,rgba(59,130,246,0.10),transparent_42%),#f8fafc]">
        <Outlet />
      </div>
    );
  }

  if (loading) {
    return (
      <div className="pt-12 sm:pt-16 min-h-screen bg-slate-50 flex items-center justify-center">
        <p className="text-sm text-slate-600">Loading workspace…</p>
      </div>
    );
  }

  if (!session) {
    return <Navigate to="/cashflow/login" replace />;
  }

  return (
    <div className="pt-12 sm:pt-16 min-h-screen bg-[radial-gradient(circle_at_0%_0%,rgba(56,189,248,0.10),transparent_40%),radial-gradient(circle_at_100%_100%,rgba(59,130,246,0.10),transparent_42%),#f8fafc]">
      <section className="py-10 sm:py-14">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="mb-6 sm:mb-8 rounded-2xl border border-slate-200 bg-white/90 backdrop-blur-sm shadow-sm px-5 sm:px-7 py-5 sm:py-6">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <p className="text-sm font-semibold uppercase tracking-wider text-secondary mb-2">Solutions</p>
                <h1 className="text-3xl sm:text-4xl font-bold text-primary">Managing Cashflow</h1>
                <p className="text-text mt-3 max-w-3xl">
                  Unified finance operations for AP, AR, petty cash, and employee expense workflows.
                </p>
              </div>
              <div className="text-right">
                {session ? (
                  <>
                    <p className="text-sm font-medium text-primary">{profile?.company_name || 'Workspace setup pending'}</p>
                    <p className="text-xs text-muted mt-1">{session.user?.email} · {profile?.role || 'employee'}</p>
                    <div className="mt-3 flex flex-wrap justify-end gap-2">
                      {isAdmin && (
                        <Link to="/cashflow/invites" className="btn-ui btn-ui-sm btn-ui-neutral">
                          Invite Admin
                        </Link>
                      )}
                      <button type="button" onClick={signOut} className="btn-ui btn-ui-sm btn-ui-danger">
                        Sign Out
                      </button>
                    </div>
                  </>
                ) : (
                  <Link to="/cashflow/login" className="btn-ui btn-ui-sm btn-ui-primary">
                    Sign In
                  </Link>
                )}
              </div>
            </div>
          </div>

          <div className="rounded-2xl bg-white/95 border border-slate-200 shadow-[0_10px_30px_rgba(15,23,42,0.06)] p-2 sm:p-3 backdrop-blur-sm">
            <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
              <nav className="flex flex-wrap items-center gap-2">
              {navItems.map((item) => {
                const isActive = isActivePath(item.path);
                return (
                  <Link
                    key={item.path}
                    to={item.path}
                    className={`px-3.5 py-2 rounded-xl text-sm font-medium whitespace-nowrap transition-colors ${
                      isActive
                        ? 'bg-primary text-white shadow-[0_8px_20px_rgba(37,99,235,0.35)]'
                        : 'text-text hover:bg-slate-100'
                    }`}
                  >
                    {item.label}
                  </Link>
                );
              })}
              </nav>

              <button
                type="button"
                onClick={openExportModal}
                className="inline-flex w-fit items-center gap-2 px-3 py-2 rounded-xl border border-blue-200 bg-blue-50 text-secondary text-sm font-semibold hover:bg-blue-100 transition-colors whitespace-nowrap"
              >
                <Download className="w-4 h-4" />
                GST compliance Export
              </button>
            </div>
          </div>

          <div className="mt-6 sm:mt-8">
            <Outlet />
          </div>
        </div>
      </section>

      {isExportOpen && (
        <div className="fixed inset-0 z-50 bg-slate-900/45 backdrop-blur-[1px] flex items-center justify-center p-4">
          <div className="w-full max-w-lg bg-white rounded-2xl border border-slate-200 shadow-xl">
            <div className="flex items-center justify-between px-5 py-4 border-b border-slate-100">
              <h3 className="text-lg font-semibold text-primary">GST compliance Export</h3>
              <button
                type="button"
                onClick={closeExportModal}
                disabled={isDownloading}
                className="p-1.5 rounded-lg text-slate-500 hover:bg-slate-100"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="px-5 py-4 space-y-4">
              <div className="rounded-xl border border-blue-100 bg-blue-50 px-3 py-2.5 text-sm text-slate-700">
                <p className="font-semibold text-secondary">Export: GSTR Excel Report</p>
                <p className="mt-0.5">Ledger XML export has been retired from this workflow.</p>
              </div>

              <div className="grid sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-primary mb-1">Start Date</label>
                  <input
                    type="date"
                    value={startDate}
                    onChange={(e) => setStartDate(e.target.value)}
                    className="w-full px-3 py-2.5 rounded-xl border border-slate-200 text-sm"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-primary mb-1">End Date</label>
                  <input
                    type="date"
                    value={endDate}
                    onChange={(e) => setEndDate(e.target.value)}
                    className="w-full px-3 py-2.5 rounded-xl border border-slate-200 text-sm"
                  />
                </div>
              </div>

              {exportError && (
                <div className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                  {exportError}
                </div>
              )}
            </div>

            <div className="px-5 py-4 border-t border-slate-100 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={closeExportModal}
                disabled={isDownloading}
                className="px-4 py-2 rounded-xl border border-slate-200 text-sm font-medium text-text hover:bg-slate-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleDownload}
                disabled={isDownloading}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-primary text-white text-sm font-semibold disabled:opacity-60"
              >
                <Download className="w-4 h-4" />
                {isDownloading ? 'Preparing...' : 'Download'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function CashflowLayout() {
  return <CashflowShell />;
}