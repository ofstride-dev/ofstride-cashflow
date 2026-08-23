import { useMemo, useState } from 'react';
import { Link, Navigate, Outlet, useLocation } from 'react-router-dom';
import {
  ArrowDownCircle,
  ArrowUpCircle,
  Download,
  GitCompareArrows,
  LayoutDashboard,
  LogOut,
  Menu,
  Receipt,
  UserPlus,
  Wallet,
  X,
} from 'lucide-react';
import { cashflowFetch } from '../../services/cashflowApi';
import { useCashflowAuth } from '../../context/CashflowAuthContext';

const NAV_ITEMS = [
  { label: 'Dashboard', path: '/cashflow/dashboard', icon: LayoutDashboard },
  { label: 'Payables (AP)', path: '/cashflow/ap', icon: ArrowUpCircle },
  { label: 'Receivables (AR)', path: '/cashflow/ar', icon: ArrowDownCircle },
  { label: 'Petty Cash', path: '/cashflow/pettycash', icon: Wallet },
  { label: 'Bank Reconcile', path: '/cashflow/reconcile', icon: GitCompareArrows },
  { label: 'Expense Portal', path: '/cashflow/expense', icon: Receipt },
];

function initialsFor(nameOrEmail) {
  const source = String(nameOrEmail || '').trim();
  if (!source) return 'U';
  const parts = source.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return source.slice(0, 2).toUpperCase();
}

function NavLinks({ isActivePath, onNavigate }) {
  return (
    <nav className="flex flex-col gap-1" aria-label="Cashflow modules">
      {NAV_ITEMS.map((item) => {
        const isActive = isActivePath(item.path);
        const Icon = item.icon;
        return (
          <Link
            key={item.path}
            to={item.path}
            onClick={onNavigate}
            aria-current={isActive ? 'page' : undefined}
            className={`flex items-center gap-3 rounded-xl px-3.5 py-2.5 text-sm font-medium transition-colors ${
              isActive
                ? 'dashboard-nav-active text-white shadow-[0_8px_24px_-10px_rgba(34,211,238,0.75)]'
                : 'dashboard-nav-link text-slate-200 hover:bg-white/10 hover:text-white'
            }`}
          >
            <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
            <span className="truncate">{item.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}

function CashflowShell() {
  const { session, profile, signOut, isAdmin, loading } = useCashflowAuth();

  const location = useLocation();
  const isLoginRoute = location.pathname.replace(/\/$/, '') === '/cashflow/login';
  const [isExportOpen, setIsExportOpen] = useState(false);
  const [isMobileNavOpen, setIsMobileNavOpen] = useState(false);
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

  const isActivePath = (path) => {
    if (path === '/cashflow/expense') {
      return location.pathname.startsWith('/cashflow/expense');
    }
    return location.pathname === path;
  };

  const activeItem = NAV_ITEMS.find((item) => isActivePath(item.path));

  if (isLoginRoute) {
    return (
      <div className="min-h-screen bg-[radial-gradient(circle_at_0%_0%,rgba(56,189,248,0.10),transparent_40%),radial-gradient(circle_at_100%_100%,rgba(59,130,246,0.10),transparent_42%),#f6f8fb]">
        <Outlet />
      </div>
    );
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-surface flex items-center justify-center">
        <div className="flex items-center gap-3 text-sm text-muted">
          <span className="h-2 w-2 rounded-full bg-secondary animate-pulse" />
          Loading workspace…
        </div>
      </div>
    );
  }

  if (!session) {
    return <Navigate to="/cashflow/login" replace />;
  }

  const displayName = profile?.company_name || 'Workspace setup pending';
  const userLabel = session.user?.email || '';

  return (
    <div className="dashboard-app min-h-screen lg:flex">
      {/* Desktop sidebar */}
      <aside className="dashboard-sidebar hidden lg:flex lg:w-64 lg:flex-col lg:shrink-0 lg:sticky lg:top-0 lg:h-screen">
          <div className="px-5 py-6 border-b border-white/10">
          <p className="dashboard-sidebar-brand-parent">OFSTRIDE</p>
          <h1 className="dashboard-sidebar-brand-product">CASHFLOW</h1>
          <p className="mt-5 text-[0.65rem] font-bold uppercase tracking-[0.16em] text-slate-500">Workspace</p>
        </div>
        <div className="flex-1 overflow-y-auto px-3 py-4">
          <NavLinks isActivePath={isActivePath} />
        </div>
        <div className="px-3 py-4 border-t border-white/10">
          {isAdmin && (
            <Link
              to="/cashflow/invites"
                className="dashboard-nav-link flex items-center gap-3 rounded-xl px-3.5 py-2.5 text-sm font-semibold text-slate-200 hover:bg-white/10 hover:text-white transition-colors"
            >
              <UserPlus className="h-4 w-4 shrink-0" aria-hidden="true" />
              Invite Admin
            </Link>
          )}
          <button
            type="button"
            onClick={signOut}
            className="dashboard-nav-danger mt-1 flex w-full items-center gap-3 rounded-xl px-3.5 py-2.5 text-sm font-semibold text-rose-200 hover:bg-rose-400/10 transition-colors"
          >
            <LogOut className="h-4 w-4 shrink-0" aria-hidden="true" />
            Sign Out
          </button>
        </div>
      </aside>

      {/* Mobile nav drawer */}
      {isMobileNavOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button
            type="button"
            aria-label="Close navigation"
            className="absolute inset-0 bg-slate-900/45 backdrop-blur-[1px]"
            onClick={() => setIsMobileNavOpen(false)}
          />
          <div className="dashboard-sidebar relative z-10 flex h-full w-72 max-w-[85vw] flex-col shadow-2xl">
            <div className="flex items-center justify-between px-5 py-5 border-b border-white/10">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.22em] text-cyan-300">OfStride</p>
                <h1 className="text-lg font-bold text-white mt-1">Cashflow</h1>
              </div>
              <button
                type="button"
                onClick={() => setIsMobileNavOpen(false)}
                aria-label="Close navigation"
                className="p-2 rounded-lg text-slate-400 hover:bg-white/10 hover:text-white"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto px-3 py-4">
              <NavLinks isActivePath={isActivePath} onNavigate={() => setIsMobileNavOpen(false)} />
            </div>
            <div className="px-3 py-4 border-t border-white/10">
              {isAdmin && (
                <Link
                  to="/cashflow/invites"
                  onClick={() => setIsMobileNavOpen(false)}
                  className="dashboard-nav-link flex items-center gap-3 rounded-xl px-3.5 py-2.5 text-sm font-semibold text-slate-200 hover:bg-white/10 hover:text-white"
                >
                  <UserPlus className="h-4 w-4 shrink-0" aria-hidden="true" />
                  Invite Admin
                </Link>
              )}
              <button
                type="button"
                onClick={signOut}
                className="dashboard-nav-danger mt-1 flex w-full items-center gap-3 rounded-xl px-3.5 py-2.5 text-sm font-semibold text-rose-200 hover:bg-rose-400/10"
              >
                <LogOut className="h-4 w-4 shrink-0" aria-hidden="true" />
                Sign Out
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Main column */}
      <div className="flex-1 min-w-0">
        <header className="dashboard-header sticky top-0 z-30 border-b border-white/10 backdrop-blur-xl">
          <div className="flex items-center gap-3 px-4 sm:px-6 lg:px-8 py-3.5">
            <button
              type="button"
              onClick={() => setIsMobileNavOpen(true)}
              aria-label="Open navigation"
              className="lg:hidden p-2 -ml-2 rounded-lg text-slate-400 hover:bg-white/10 hover:text-white"
            >
              <Menu className="h-5 w-5" />
            </button>

            <div className="min-w-0 flex-1">
              <div className="dashboard-page-chip"><span className="dashboard-page-dot" />{activeItem ? activeItem.label : displayName}</div>
            </div>

            <button
              type="button"
              onClick={openExportModal}
              className="dashboard-export hidden sm:inline-flex items-center gap-2 px-3 py-2 rounded-xl border text-cyan-200 text-sm font-semibold transition-colors whitespace-nowrap"
            >
              <Download className="w-4 h-4" />
              GST Export
            </button>
            <button
              type="button"
              onClick={openExportModal}
              aria-label="GST compliance export"
              className="dashboard-export sm:hidden inline-flex items-center justify-center p-2 rounded-xl border text-cyan-200"
            >
              <Download className="w-4 h-4" />
            </button>

            <div className="hidden md:flex items-center gap-2.5 pl-3 ml-1 border-l border-slate-200">
              <span className="dashboard-avatar flex h-8 w-8 items-center justify-center rounded-full text-xs font-bold text-slate-950">
                {initialsFor(profile?.full_name || userLabel)}
              </span>
              <div className="text-left leading-tight">
                <p className="text-sm font-medium text-white truncate max-w-[160px]">{displayName}</p>
                <p className="text-xs text-slate-500 truncate max-w-[160px]">{profile?.role || 'employee'}</p>
              </div>
            </div>
          </div>
        </header>

        <main className="dashboard-main px-4 sm:px-6 lg:px-8 py-6 sm:py-8">
          <Outlet />
        </main>
      </div>

      {isExportOpen && (
        <div className="fixed inset-0 z-50 bg-slate-900/45 backdrop-blur-[1px] flex items-center justify-center p-4">
          <div className="w-full max-w-lg card-ui">
            <div className="flex items-center justify-between px-5 py-4 border-b border-slate-100">
              <h3 className="text-lg font-semibold text-primary">GST Compliance Export</h3>
              <button
                type="button"
                onClick={closeExportModal}
                disabled={isDownloading}
                aria-label="Close export dialog"
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
                  <label className="label-ui" htmlFor="gst-export-start">Start Date</label>
                  <input
                    id="gst-export-start"
                    type="date"
                    value={startDate}
                    onChange={(e) => setStartDate(e.target.value)}
                    className="input-ui"
                  />
                </div>
                <div>
                  <label className="label-ui" htmlFor="gst-export-end">End Date</label>
                  <input
                    id="gst-export-end"
                    type="date"
                    value={endDate}
                    onChange={(e) => setEndDate(e.target.value)}
                    className="input-ui"
                  />
                </div>
              </div>

              {exportError && (
                <div className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">
                  {exportError}
                </div>
              )}
            </div>

            <div className="px-5 py-4 border-t border-slate-100 flex items-center justify-end gap-2">
              <button type="button" onClick={closeExportModal} disabled={isDownloading} className="btn-ui btn-ui-neutral">
                Cancel
              </button>
              <button type="button" onClick={handleDownload} disabled={isDownloading} className="btn-ui btn-ui-primary">
                <Download className="w-4 h-4" />
                {isDownloading ? 'Preparing…' : 'Download'}
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
