import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  Gauge,
  Sparkles,
  MessageCircle,
  Languages,
  BarChart3,
  ClipboardCheck,
  FileText,
  RefreshCw,
  Wallet,
} from 'lucide-react';
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { cashflowFetch, parseCashflowResponse } from '../../services/cashflowApi';
import { useCashflowAuth } from '../../context/CashflowAuthContext';

function formatMoney(value) {
  const amount = Number(value || 0);
  return `₹${amount.toLocaleString('en-IN')}`;
}

function resolveDashboardPeriod(periodKey, customStartDate, customEndDate) {
  if (periodKey === 'custom') return { start_date: customStartDate, end_date: customEndDate };
  const today = new Date();
  const end = today.toISOString().slice(0, 10);
  const start = new Date(today);
  if (periodKey === '1d') return { start_date: end, end_date: end };
  if (periodKey === '7d') start.setDate(start.getDate() - 6);
  else if (periodKey === '30d') start.setDate(start.getDate() - 29);
  else start.setDate(1);
  return { start_date: start.toISOString().slice(0, 10), end_date: end };
}

const PERIOD_OPTIONS = [
  { key: '1d', label: '1 Day' },
  { key: '7d', label: '7 Days' },
  { key: '30d', label: '30 Days' },
  { key: 'month', label: 'This Month' },
  { key: 'custom', label: 'Custom' },
];

function SafeBar({ label, value, max, tone }) {
  const width = max > 0 ? Math.max(4, Math.round((value / max) * 100)) : 0;
  const toneClasses = {
    emerald: 'bg-emerald-500',
    sky: 'bg-sky-500',
    rose: 'bg-rose-500',
    amber: 'bg-amber-500',
  };
  return (
    <div className="mb-3 last:mb-0">
      <div className="flex items-center justify-between text-[0.8rem] mb-1">
        <span className="text-muted">{label}</span>
        <strong className="text-primary tabular-nums">{formatMoney(value)}</strong>
      </div>
      <div className="h-2.5 w-full rounded-full bg-slate-100 overflow-hidden">
        <div className={`h-full rounded-full ${toneClasses[tone] || 'bg-slate-400'}`} style={{ width: `${width}%` }} />
      </div>
    </div>
  );
}

function SummaryCard({ label, value, icon: Icon, tone }) {
  const toneClasses = {
    emerald: { glow: 'dashboard-card-mint', icon: 'text-cyan-200 bg-cyan-300/10', text: 'text-cyan-200' },
    rose: { glow: 'dashboard-card-pink', icon: 'text-rose-200 bg-rose-300/10', text: 'text-rose-200' },
    amber: { glow: 'dashboard-card-gold', icon: 'text-amber-200 bg-amber-300/10', text: 'text-amber-200' },
    sky: { glow: 'dashboard-card-blue', icon: 'text-sky-200 bg-sky-300/10', text: 'text-sky-200' },
    indigo: { glow: 'dashboard-card-violet', icon: 'text-violet-200 bg-violet-300/10', text: 'text-violet-200' },
  }[tone];

  return (
    <div className={`dashboard-stat-card ${toneClasses.glow} rounded-2xl border p-5`}>
      <div className="flex items-center justify-between">
        <span className="text-[0.68rem] font-bold uppercase tracking-[0.12em] text-slate-400">{label}</span>
        <span className={`flex h-8 w-8 items-center justify-center rounded-lg ${toneClasses.icon}`}>
          <Icon className="h-4 w-4" aria-hidden="true" />
        </span>
      </div>
      <h3 className={`dashboard-kpi-value mt-3 text-[1.45rem] font-medium tracking-[-0.025em] tabular-nums ${toneClasses.text}`}>{value}</h3>
      <div className="mt-3 h-1 w-16 rounded-full bg-white/10"><div className="h-full w-2/3 rounded-full bg-current opacity-70" /></div>
    </div>
  );
}

function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="dashboard-tooltip">
      <p className="text-[0.68rem] font-bold uppercase tracking-wider text-slate-500">{label}</p>
      {payload.map((entry) => <p key={entry.dataKey} className="mt-1 text-sm font-semibold text-slate-800">{entry.name}: {formatMoney(entry.value)}</p>)}
    </div>
  );
}

function FlowChart({ data }) {
  return (
    <div className="h-[280px] w-full">
      {data.length ? (
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 12, right: 8, left: -18, bottom: 0 }}>
            <defs>
              <linearGradient id="inflowGradient" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#67e8f9" stopOpacity={0.42} /><stop offset="100%" stopColor="#67e8f9" stopOpacity={0} /></linearGradient>
              <linearGradient id="outflowGradient" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#c4b5fd" stopOpacity={0.24} /><stop offset="100%" stopColor="#c4b5fd" stopOpacity={0} /></linearGradient>
            </defs>
            <CartesianGrid vertical={false} stroke="rgba(148,163,184,.12)" />
            <XAxis dataKey="label" axisLine={false} tickLine={false} tick={{ fill: '#64748b', fontSize: 11 }} dy={10} />
            <YAxis hide domain={[0, 'auto']} />
            <Tooltip content={<ChartTooltip />} cursor={{ stroke: 'rgba(103,232,249,.28)' }} />
            <Area type="monotone" dataKey="inflow" name="Inflow" stroke="#67e8f9" strokeWidth={3} fill="url(#inflowGradient)" dot={{ r: 3, fill: '#67e8f9', strokeWidth: 0 }} activeDot={{ r: 5, stroke: '#cffafe', strokeWidth: 3 }} />
            <Area type="monotone" dataKey="outflow" name="Outflow" stroke="#a78bfa" strokeWidth={2.5} fill="url(#outflowGradient)" dot={false} />
          </AreaChart>
        </ResponsiveContainer>
      ) : <div className="flex h-full items-center justify-center rounded-xl border border-dashed border-white/10 text-sm text-slate-500">Trend data will appear as transactions arrive.</div>}
    </div>
  );
}

function DashboardSkeleton() {
  return (
    <div className="dashboard-loading-wrap" aria-busy="true" aria-live="polite">
      <div className="max-w-6xl mx-auto space-y-6 dashboard-loading-content" aria-hidden="true">
        <div className="flex items-center justify-between gap-4">
          <div className="skeleton-ui h-8 w-56" />
          <div className="skeleton-ui h-10 w-72" />
        </div>
        <div className="grid gap-4 grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="skeleton-ui h-24" />
          ))}
        </div>
        <div className="grid gap-4 lg:grid-cols-[1.2fr_1fr]">
          <div className="skeleton-ui h-64" />
          <div className="skeleton-ui h-64" />
        </div>
      </div>
      <div className="dashboard-loading-message">
        <div className="dashboard-loading-spinner" aria-hidden="true"><BarChart3 className="h-5 w-5" /></div>
        <p className="dashboard-loading-title">Getting your dashboard ready</p>
        <p className="dashboard-loading-subtitle">Loading your latest financial insights…</p>
        <div className="dashboard-loading-bar" aria-hidden="true"><span /></div>
      </div>
      <span className="sr-only">Loading cash flow metrics…</span>
    </div>
  );
}

function AnalystLoadingStatus({ active }) {
  const labels = [
    'Reading transactions...',
    'Reviewing accounts payable and receivable...',
    'Analyzing...',
  ];
  const [labelIndex, setLabelIndex] = useState(0);

  useEffect(() => {
    if (!active) return undefined;

    const resetTimer = setTimeout(() => setLabelIndex(0), 0);
    const firstStepTimer = setTimeout(() => setLabelIndex(1), 1500);
    const secondStepTimer = setTimeout(() => setLabelIndex(2), 5000);

    return () => {
      clearTimeout(resetTimer);
      clearTimeout(firstStepTimer);
      clearTimeout(secondStepTimer);
    };
  }, [active]);

  if (!active) return null;

  return <span className="ai-loading-status" role="status" aria-live="polite">{labels[labelIndex]}</span>;
}

export default function CashflowDashboard() {
  const { session, profile } = useCashflowAuth();
  const authIdentityKey = `${session?.user?.id || ''}:${profile?.company_id || ''}`;
  const todayIso = new Date().toISOString().slice(0, 10);
  const monthStartIso = (() => {
    const now = new Date();
    now.setDate(1);
    return now.toISOString().slice(0, 10);
  })();

  const [data, setData] = useState(null);
  const [reconcileRuns, setReconcileRuns] = useState([]);
  const [periodKey, setPeriodKey] = useState('month');
  const [customStartDate, setCustomStartDate] = useState(monthStartIso);
  const [customEndDate, setCustomEndDate] = useState(todayIso);
  const [loading, setLoading] = useState(true);
  const [aiResponse, setAiResponse] = useState('Select an insight to generate a live analyst response.');
  const [aiQuestion, setAiQuestion] = useState('');
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState('');
  const [aiCoverage, setAiCoverage] = useState(null);
  const analystRequestIdRef = useRef(0);
  const analystAbortRef = useRef(null);
  const [aiDetails, setAiDetails] = useState({ findings: [], risks: [], actions: [] });
  const [reportSending, setReportSending] = useState(false);
  const [reportMessage, setReportMessage] = useState('');
  const [scheduledReports, setScheduledReports] = useState(false);
  const [showNetDetails, setShowNetDetails] = useState(false);
  const [guideSlide, setGuideSlide] = useState(0);
  const guideTouchStartRef = useRef(null);
  const [scheduleLoading, setScheduleLoading] = useState(false);
  const canSendReport = ['owner', 'admin', 'finance'].includes(String(profile?.role || '').toLowerCase());
  const canManageScheduledReports = ['owner', 'admin'].includes(String(profile?.role || '').toLowerCase());

  useEffect(() => {
    if (!canManageScheduledReports) return undefined;
    cashflowFetch('/cashflow/analyst', { method: 'POST', body: JSON.stringify({ intent: 'report_settings' }) })
      .then(parseCashflowResponse)
      .then((parsed) => { if (parsed.ok) setScheduledReports(Boolean(parsed.data?.weekly_reports_enabled)); })
      .catch(() => {});
    return undefined;
  }, [canManageScheduledReports, authIdentityKey]);

  const toggleScheduledReports = async (event) => {
    const enabled = event.target.checked;
    setScheduleLoading(true);
    try {
      const response = await cashflowFetch('/cashflow/analyst', { method: 'POST', body: JSON.stringify({ intent: 'report_settings', enabled }) });
      const parsed = await parseCashflowResponse(response);
      if (!parsed.ok) throw new Error(parsed.error || 'Could not update scheduled reports');
      setScheduledReports(Boolean(parsed.data?.weekly_reports_enabled));
    } catch (error) {
      setReportMessage(error instanceof Error ? error.message : 'Could not update scheduled reports');
    } finally {
      setScheduleLoading(false);
    }
  };

  const sendReport = async (reportType) => {
    setReportSending(true);
    setReportMessage('');
    try {
      const response = await cashflowFetch('/cashflow/analyst', { method: 'POST', body: JSON.stringify({ intent: 'report_email', report_type: reportType }) });
      const parsed = await parseCashflowResponse(response);
      if (!parsed.ok) throw new Error(parsed.error || 'Report email failed');
      setReportMessage(`${reportType === 'weekly' ? 'Weekly' : 'Monthly'} report sent to ${parsed.data?.sent || 0} active members.`);
    } catch (error) {
      setReportMessage(error instanceof Error ? error.message : 'Report email failed');
    } finally {
      setReportSending(false);
    }
  };

  const runAiPrompt = async (intent, question = '') => {
    const requestId = ++analystRequestIdRef.current;
    analystAbortRef.current?.abort();
    const controller = new AbortController();
    analystAbortRef.current = controller;
    const timeoutId = window.setTimeout(() => controller.abort(), 45000);
    setAiLoading(true);
    setAiError('');
    setAiDetails({ findings: [], risks: [], actions: [] });
    try {
      const response = await cashflowFetch('/cashflow/analyst', {
        method: 'POST',
        signal: controller.signal,
        body: JSON.stringify({
          intent,
          question: question.trim(),
          period: periodKey,
          ...(periodKey === 'custom' ? { start_date: customStartDate, end_date: customEndDate } : {}),
        }),
      });
      const parsed = await parseCashflowResponse(response);
      if (!parsed.ok) throw new Error(parsed.error || 'Analyst unavailable');
      if (requestId !== analystRequestIdRef.current) return;
      setAiResponse(parsed.data?.answer || parsed.data?.headline || 'No analyst response was returned.');
      setAiCoverage(parsed.data?.coverage || null);
      setAiDetails({
        findings: Array.isArray(parsed.data?.findings) ? parsed.data.findings : [],
        risks: Array.isArray(parsed.data?.risks) ? parsed.data.risks : [],
        actions: Array.isArray(parsed.data?.actions) ? parsed.data.actions : [],
      });
      setAiQuestion('');
    } catch (error) {
      if (requestId !== analystRequestIdRef.current) return;
      setAiError(error?.name === 'AbortError' ? 'Analyst request timed out. Please try again.' : error instanceof Error ? error.message : 'Analyst unavailable');
      setAiCoverage(null);
      setAiDetails({ findings: [], risks: [], actions: [] });
      setAiResponse('The analyst could not complete this request. Review the data coverage and try again.');
    } finally {
      window.clearTimeout(timeoutId);
      if (requestId === analystRequestIdRef.current) {
        setAiLoading(false);
        analystAbortRef.current = null;
      }
    }
  };

  const submitAiQuestion = (event) => {
    event.preventDefault();
    if (aiQuestion.trim()) runAiPrompt('ask', aiQuestion);
  };

  // Build a zero-filled dashboard payload so first-time users and API outages
  // always see empty (but valid) metrics instead of a hard failure.
  const emptyDashboardData = useMemo(() => {
    const fallbackPeriod = resolveDashboardPeriod(periodKey, customStartDate, customEndDate);
    const start = new Date(fallbackPeriod.start_date);
    const end = new Date(fallbackPeriod.end_date);
    const days = Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())
      ? 0
      : Math.max(1, Math.round((end - start) / 86400000) + 1);
    return ({
    period: {
      key: periodKey,
      ...fallbackPeriod,
      days,
    },
    summary: {
      cash_received: 0,
      cash_pending: 0,
      cash_payable: 0,
      cash_inflow: 0,
      cash_outflow: 0,
      net_cash_position: 0,
      petty_cash_balance: 0,
      runway_months: null,
      inflow_from_customers: 0,
      inflow_from_petty_cash: 0,
      outflow_to_vendors: 0,
      outflow_from_petty_cash: 0,
      accrued_revenue: 0,
      accrued_expenses: 0,
      direct_expenses: 0,
      net_profit_loss: 0,
      aging_summary: { ar: { overdue: 0, due_soon: 0, not_due: 0 }, ap: { overdue: 0, due_soon: 0, not_due: 0 } },
    },
    msme_alerts: [],
    trend: { monthly: [] },
    });
  }, [periodKey, customStartDate, customEndDate, todayIso]);

  useEffect(() => {
    let isCurrent = true;
    analystRequestIdRef.current += 1;
    analystAbortRef.current?.abort();
    setData(null);
    setReconcileRuns([]);
    setLoading(true);
    const params = new URLSearchParams({ period: periodKey });
    if (periodKey === 'custom') {
      params.set('start_date', customStartDate);
      params.set('end_date', customEndDate);
    }

    // Fetch dashboard metrics with graceful fallback to zero data.
    // Cache-bust the tenant-sensitive dashboard request. The response must be
    // recomputed after a company/account switch, even behind a dev proxy.
    params.set('_tenant_refresh', `${authIdentityKey}:${Date.now()}`);
    const dashboardPromise = cashflowFetch(`/cashflow/dashboard?${params.toString()}`)
      .then(res => parseCashflowResponse(res))
      .then(parsed => {
        if (!isCurrent) return;
        if (parsed.ok) {
          setData(parsed.data || emptyDashboardData);
        } else {
          // On first-time setup (empty workspace) or transient API issues,
          // fall back to an empty dashboard instead of showing an error.
          setData(emptyDashboardData);
          console.warn('Dashboard metrics unavailable:', parsed.error);
        }
      })
      .catch(() => {
        if (!isCurrent) return;
        // API network error – still show an empty dashboard.
        setData(emptyDashboardData);
      });

    const reconcilePromise = cashflowFetch('/reconcile/bank/recent?limit=5')
      .then(async (res) => {
        if (!res.ok) {
          // Reconcilation preview is additive. A 403 here should not block the
          // rest of the dashboard, especially when the workspace is still
          // onboarding or the bank-reconcile route is not configured yet.
          if (res.status === 403 || res.status === 401) return [];
          return [];
        }
        const payload = await res.json().catch(() => null);
        if (!payload?.success) return [];
        return payload?.data?.runs || [];
      })
        .then((runs) => {
          if (isCurrent) setReconcileRuns(Array.isArray(runs) ? runs : []);
        })
      .catch(() => {
        if (isCurrent) setReconcileRuns([]);
      });

    // Reconciliation is an optional side panel. Render the primary dashboard
    // as soon as its own request completes instead of waiting for this second
    // network call, which can make an otherwise-ready dashboard look stuck.
    dashboardPromise.finally(() => {
      if (isCurrent) setLoading(false);
    });
    reconcilePromise.catch(() => {
      if (isCurrent) setReconcileRuns([]);
    });

    return () => {
      isCurrent = false;
    };
  }, [authIdentityKey, periodKey, customStartDate, customEndDate, emptyDashboardData]);

  const latestRun = useMemo(() => (reconcileRuns.length ? reconcileRuns[0] : null), [reconcileRuns]);
  const monthlyTrend = useMemo(() => {
    const all = Array.isArray(data?.trend?.monthly) ? data.trend.monthly : [];
    return all.slice(-3);
  }, [data]);
  const momentumSummary = useMemo(() => {
    const inflow = monthlyTrend.reduce((sum, point) => sum + Number(point.inflow || 0), 0);
    const outflow = monthlyTrend.reduce((sum, point) => sum + Number(point.outflow || 0), 0);
    return { inflow, outflow, net: inflow - outflow };
  }, [monthlyTrend]);

  const periodBreakdown = useMemo(() => {
    const summary = data?.summary || {};
    const inflowCustomers = Number(summary.inflow_from_customers || 0);
    const outflowVendors = Number(summary.outflow_to_vendors || 0);
    const overdueAr = Number(summary.aging_summary?.ar?.overdue || 0);
    const overdueAp = Number(summary.aging_summary?.ap?.overdue || 0);
    return {
      inflowCustomers,
      outflowVendors,
      overdueAr,
      overdueAp,
      max: Math.max(inflowCustomers, outflowVendors, overdueAr, overdueAp, 0),
    };
  }, [data]);

  const riskTone = latestRun?.risk_level === 'high'
    ? { border: 'border-rose-200', bg: 'bg-rose-50', text: 'text-rose-700', pill: 'bg-rose-600' }
    : latestRun?.risk_level === 'medium'
      ? { border: 'border-amber-200', bg: 'bg-amber-50', text: 'text-amber-700', pill: 'bg-amber-600' }
      : { border: 'border-emerald-200', bg: 'bg-emerald-50', text: 'text-emerald-700', pill: 'bg-emerald-600' };

  if (loading) return <DashboardSkeleton />;

  return (
    <div className="dashboard-shell max-w-6xl mx-auto">
      {/* Header + period selector */}
      <div className="dashboard-heading flex flex-col gap-4 mb-6 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="dashboard-kicker">Financial command center / Overview</p>
          <h2 className="mt-1 text-3xl font-bold text-white">Cash Flow Overview</h2>
          <p className="mt-2 text-sm text-slate-400">
            Window: <span className="tabular-nums">{data?.period?.start_date || '-'}</span> to{' '}
            <span className="tabular-nums">{data?.period?.end_date || '-'}</span>
          </p>
        </div>

        <div className="flex flex-col gap-2 sm:items-end">
        <div className="period-switcher inline-flex rounded-xl border border-white/10 bg-white/[0.04] overflow-hidden self-start sm:self-auto" role="group" aria-label="Select reporting period">
            {PERIOD_OPTIONS.map((item, idx) => {
              const active = periodKey === item.key;
              return (
                <button
                  key={item.key}
                  type="button"
                  onClick={() => setPeriodKey(item.key)}
                  aria-pressed={active}
                  className={`px-3 py-2 text-xs sm:text-sm font-semibold whitespace-nowrap transition-colors ${
                    idx !== PERIOD_OPTIONS.length - 1 ? 'border-r border-white/10' : ''
                  } ${active ? 'bg-cyan-300 text-slate-950' : 'bg-transparent text-slate-400 hover:bg-white/10 hover:text-white'}`}
                >
                  {item.label}
                </button>
              );
            })}
          </div>
          {periodKey === 'custom' && (
            <div className="inline-flex items-center gap-2">
              <input
                type="date"
                value={customStartDate}
                max={customEndDate}
                onChange={(e) => setCustomStartDate(e.target.value)}
                className="input-ui py-1.5 text-xs w-auto"
              />
              <span className="text-xs text-muted">to</span>
              <input
                type="date"
                value={customEndDate}
                min={customStartDate}
                max={todayIso}
                onChange={(e) => setCustomEndDate(e.target.value)}
                className="input-ui py-1.5 text-xs w-auto"
              />
            </div>
          )}
        </div>
      </div>

      {/* Summary cards */}
      <div className="grid gap-4 grid-cols-2 lg:grid-cols-6 mb-6">
        <SummaryCard label="Cash Collected" value={formatMoney(data?.summary?.cash_received)} icon={ArrowUpRight} tone="emerald" />
        <SummaryCard label="Cash Disbursed" value={formatMoney(data?.summary?.cash_outflow)} icon={ArrowDownRight} tone="rose" />
        <SummaryCard label="Accounts Payable" value={formatMoney(data?.summary?.cash_payable)} icon={ArrowDownRight} tone="rose" />
        <SummaryCard label="Accounts Receivable" value={formatMoney(data?.summary?.cash_pending)} icon={AlertTriangle} tone="amber" />
        <SummaryCard
          label="Cash Runway"
          value={data?.summary?.runway_months == null ? 'N/A' : `${data.summary.runway_months} mo`}
          icon={Wallet}
          tone="indigo"
        />
        <div className="relative">
          <button type="button" className="w-full text-left" onClick={() => setShowNetDetails((value) => !value)} title="Show cash inflow and outflow">
            <SummaryCard label="Net Cash Flow" value={formatMoney(data?.summary?.net_cash_position)} icon={Gauge} tone="sky" />
          </button>
          {showNetDetails && <div className="absolute z-20 left-0 right-0 top-full mt-2 rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-700 shadow-xl"><div className="flex justify-between"><span>Total Cash Inflow</span><strong className="text-emerald-700">{formatMoney(data?.summary?.cash_inflow)}</strong></div><div className="mt-2 flex justify-between"><span>Payments Made (Outflow)</span><strong className="text-rose-700">{formatMoney(data?.summary?.cash_outflow)}</strong></div></div>}
        </div>
      </div>
      <div className="grid gap-5 lg:grid-cols-2 mb-6">
        <div className="card-ui p-6"><h3 className="text-base font-semibold text-primary">P&amp;L Snapshot (Accrual)</h3><div className="mt-4 grid grid-cols-3 gap-3"><div><p className="text-xs text-muted">Revenue</p><strong className="text-emerald-700">{formatMoney(data?.summary?.accrued_revenue)}</strong></div><div><p className="text-xs text-muted">Expenses</p><strong className="text-rose-700">{formatMoney(Number(data?.summary?.accrued_expenses || 0) + Number(data?.summary?.direct_expenses || 0))}</strong></div><div><p className="text-xs text-muted">Net Profit/Loss</p><strong className={Number(data?.summary?.net_profit_loss || 0) >= 0 ? 'text-emerald-700' : 'text-rose-700'}>{formatMoney(data?.summary?.net_profit_loss)}</strong></div></div></div>
        <div className="card-ui p-6"><h3 className="text-base font-semibold text-primary">Aging Summary</h3><div className="mt-4 grid grid-cols-2 gap-4 text-sm"><div><p className="font-semibold text-primary">Receivables</p><p className="text-danger">Overdue: {formatMoney(data?.summary?.aging_summary?.ar?.overdue)}</p><p className="text-amber-700">Due soon: {formatMoney(data?.summary?.aging_summary?.ar?.due_soon)}</p></div><div><p className="font-semibold text-primary">Payables</p><p className="text-danger">Overdue: {formatMoney(data?.summary?.aging_summary?.ap?.overdue)}</p><p className="text-amber-700">Due soon: {formatMoney(data?.summary?.aging_summary?.ap?.due_soon)}</p></div></div></div>
      </div>

      <div className="ai-analyst-card mb-6 rounded-2xl border p-6">
        <div className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
          <div className="max-w-xl">
            <div className="flex flex-wrap items-center gap-3"><span className="ai-analyst-icon"><Sparkles className="h-5 w-5" /></span><div><p className="dashboard-kicker ai-kicker">OfStride Intelligence</p><h3 className="mt-1 text-xl font-bold text-primary">AI Financial Analyst</h3></div></div>
            <p className="mt-3 text-sm leading-6 text-slate-600">Turn your ledger into clear decisions. Ask questions in plain English, translate complex metrics, and create board-ready financial narratives in seconds.</p>
          </div>
          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4 lg:w-[52%]">
            <div className="ai-feature"><MessageCircle /><span>Ask your ledger</span></div><div className="ai-feature"><Languages /><span>Explain metrics</span></div><div className="ai-feature"><BarChart3 /><span>Generate charts</span></div><div className="ai-feature"><ClipboardCheck /><span>Board summaries</span></div>
          </div>
        </div>
        <div className="mt-5 border-t border-slate-200 pt-4">
          <div className="flex flex-wrap gap-2">
            <button type="button" disabled={aiLoading} onClick={() => runAiPrompt('summary')} className="ai-action-button"><MessageCircle className="h-4 w-4" /> Summarise reports</button>
            <button type="button" disabled={aiLoading} onClick={() => runAiPrompt('report')} className="ai-action-button"><FileText className="h-4 w-4" /> Generate report</button>
            {canSendReport && <><button type="button" disabled={reportSending || aiLoading} onClick={() => sendReport('weekly')} className="ai-action-button"><FileText className="h-4 w-4" /> {reportSending ? 'Sending…' : 'Email weekly report'}</button><button type="button" disabled={reportSending || aiLoading} onClick={() => sendReport('monthly')} className="ai-action-button"><FileText className="h-4 w-4" /> Email monthly report</button></>}
            {canManageScheduledReports && <label className="ai-action-button cursor-pointer"><input type="checkbox" checked={scheduledReports} disabled={scheduleLoading} onChange={toggleScheduledReports} className="accent-cyan-600" /> Weekly reports every Monday 9:00 AM IST</label>}
            <button type="button" disabled={aiLoading} onClick={() => runAiPrompt('explain_movement')} className="ai-action-button"><Languages className="h-4 w-4" /> Explain net movement</button>
            <button type="button" disabled={aiLoading} onClick={() => runAiPrompt('explain_metric', 'Accounts payable and receivables')} className="ai-action-button"><BarChart3 className="h-4 w-4" /> Explain AP / AR</button>
          </div>
          <form onSubmit={submitAiQuestion} className="mt-3 flex gap-2">
            <input value={aiQuestion} onChange={(event) => setAiQuestion(event.target.value)} disabled={aiLoading} className="input-ui min-w-0 flex-1" placeholder="Ask your finance analyst…" aria-label="Ask your finance analyst" />
            <button type="submit" disabled={aiLoading || !aiQuestion.trim()} className="btn-ui btn-ui-primary whitespace-nowrap">{aiLoading ? 'Analysing…' : 'Ask'}</button>
          </form>
          {aiError && <p className="mt-2 text-xs text-rose-600">{aiError}</p>}
          {reportMessage && <p className="mt-2 text-xs text-cyan-700">{reportMessage}</p>}
          {aiCoverage?.unavailable?.length > 0 && <p className="mt-2 text-xs text-amber-700">Partial coverage: {aiCoverage.unavailable.join(', ')}.</p>}
          <div className="ai-response mt-3"><Sparkles className="h-4 w-4 shrink-0" /><div className="min-w-0 flex-1">{aiLoading ? <AnalystLoadingStatus active /> : <><p>{aiResponse}</p>{aiDetails.findings.length > 0 && <div className="mt-3"><strong>Findings</strong><ul className="mt-1 list-disc pl-5">{aiDetails.findings.map((item, index) => <li key={`finding-${index}`}>{item}</li>)}</ul></div>}{aiDetails.risks.length > 0 && <div className="mt-3"><strong>Risks</strong><ul className="mt-1 list-disc pl-5">{aiDetails.risks.map((item, index) => <li key={`risk-${index}`}>{item}</li>)}</ul></div>}{aiDetails.actions.length > 0 && <div className="mt-3"><strong>Actions</strong><ul className="mt-1 list-disc pl-5">{aiDetails.actions.map((item, index) => <li key={`action-${index}`}>{item}</li>)}</ul></div>}</>}</div><RefreshCw className={`ml-auto h-3.5 w-3.5 shrink-0 opacity-50 ${aiLoading ? 'animate-spin' : ''}`} /></div>
        </div>
      </div>

      {/* Trend + breakdown */}
      <div className="grid gap-5 lg:grid-cols-[1.35fr_0.65fr] mb-6">
        <div className="dashboard-glass dashboard-chart-card p-6">
          <div className="mb-3 flex items-start justify-between gap-3"><div><p className="dashboard-kicker">Momentum</p><h3 className="mt-1 text-lg font-semibold text-white">Last 3 Months: Inflow vs Outflow</h3></div><span className="dashboard-live-pill"><span /> Live view</span></div>
          <div className="mb-2 flex items-center gap-4 text-xs text-slate-400"><span><i className="legend-dot bg-cyan-300" />Inflow</span><span><i className="legend-dot bg-violet-300" />Outflow</span></div>
          <FlowChart data={monthlyTrend} />
          <div className="momentum-insights grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="momentum-insight momentum-insight-inflow"><span>Received momentum</span><strong>{formatMoney(momentumSummary.inflow)}</strong><small>Across the latest {monthlyTrend.length || 0} months</small></div>
            <div className="momentum-insight momentum-insight-outflow"><span>Spend momentum</span><strong>{formatMoney(momentumSummary.outflow)}</strong><small>Operating cash leaving the business</small></div>
            <div className={`momentum-insight ${momentumSummary.net >= 0 ? 'momentum-insight-net' : 'momentum-insight-risk'}`}><span>Net movement</span><strong>{momentumSummary.net >= 0 ? '+' : '-'}{formatMoney(Math.abs(momentumSummary.net))}</strong><small>{momentumSummary.net >= 0 ? 'Positive cash accumulation' : 'Review upcoming commitments'}</small></div>
          </div>
          <div className="mt-4 flex items-center justify-between rounded-xl border border-dashed border-slate-200 bg-slate-50/70 px-4 py-3">
            <div><p className="text-xs font-bold uppercase tracking-wider text-slate-500">Executive read</p><p className="mt-1 text-sm font-semibold text-primary">{momentumSummary.net >= 0 ? 'Cash is building faster than it is leaving.' : 'Outflows are currently running ahead of inflows.'}</p></div>
            <span className="momentum-spark" aria-hidden="true">↗</span>
          </div>
        </div>

        <div className="card-ui p-5">
          <h3 className="text-base font-semibold text-primary mb-3">This Period Breakdown</h3>
          <SafeBar label="Money Received from Customers" value={periodBreakdown.inflowCustomers} max={periodBreakdown.max} tone="emerald" />
          <SafeBar label="Paid to Vendors" value={periodBreakdown.outflowVendors} max={periodBreakdown.max} tone="rose" />
          <SafeBar label="Overdue Customer Receivables" value={periodBreakdown.overdueAr} max={periodBreakdown.max} tone="amber" />
          <SafeBar label="Overdue Vendor Payables" value={periodBreakdown.overdueAp} max={periodBreakdown.max} tone="rose" />
          <div className="cashflow-ops mt-4 border-t border-slate-200 pt-4"><div className="flex items-center justify-between"><div><p className="dashboard-kicker">Cashflow operations</p><h4 className="mt-1 text-sm font-bold text-primary">Quotation pipeline</h4></div><Link to="/cashflow/receivables" className="text-xs font-bold text-secondary">View all</Link></div><div className="mt-3 grid grid-cols-3 gap-2"><div><strong className="text-base text-primary">0</strong><span>Open quotes</span></div><div><strong className="text-base text-amber-700">₹0</strong><span>Awaiting decision</span></div><div><strong className="text-base text-emerald-700">0</strong><span>Due this week</span></div></div><div className="mt-3 h-1.5 overflow-hidden rounded-full bg-slate-100"><div className="h-full w-0 rounded-full bg-gradient-to-r from-cyan-500 to-sky-400" /></div><p className="mt-1.5 text-[11px] text-slate-500">No quotations yet. Your pipeline will appear here as you create quotes.</p></div>
        </div>
      </div>

      {/* Reconciliation + MSME alerts */}
      <div className="grid gap-5 lg:grid-cols-[1.35fr_1fr]">
        <div className="card-ui p-6">
          <div className="flex items-center justify-between gap-3 mb-4">
            <h3 className="text-base font-semibold text-primary">Reconciliation Watch</h3>
            <Link to="/cashflow/reconcile" className="text-sm font-bold text-secondary hover:text-secondary-hover">
              Open Bank Reconcile
            </Link>
          </div>

          {!latestRun && (
            <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-3.5 text-sm text-text">
              No reconciliation runs yet. Upload a bank statement to generate mismatch intelligence.
            </div>
          )}

          {latestRun && (
            <>
              <div className={`rounded-xl border ${riskTone.border} ${riskTone.bg} px-4 py-3.5 mb-3.5`}>
                <div className="flex items-center justify-between gap-3">
                  <p className={`font-bold ${riskTone.text}`}>Latest Run Health</p>
                  <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-[0.7rem] font-bold text-white uppercase tracking-wide ${riskTone.pill}`}>
                    {latestRun.risk_level}
                  </span>
                </div>
                <p className={`mt-1.5 text-sm ${riskTone.text}`}>
                  {latestRun.source_file_name || 'Source file'} ({latestRun.start_date} to {latestRun.end_date})
                </p>
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
                <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-2.5">
                  <p className="text-[0.72rem] font-bold uppercase text-emerald-700">Matched</p>
                  <p className="mt-1 text-lg font-bold text-emerald-700 tabular-nums">{latestRun.summary?.matched || 0}</p>
                </div>
                <div className="rounded-xl border border-amber-200 bg-amber-50 p-2.5">
                  <p className="text-[0.72rem] font-bold uppercase text-amber-700">Amount Mismatch</p>
                  <p className="mt-1 text-lg font-bold text-amber-700 tabular-nums">{latestRun.summary?.amount_mismatch || 0}</p>
                </div>
                <div className="rounded-xl border border-rose-200 bg-rose-50 p-2.5">
                  <p className="text-[0.72rem] font-bold uppercase text-rose-700">Missing In Bank</p>
                  <p className="mt-1 text-lg font-bold text-rose-700 tabular-nums">{latestRun.summary?.missing_in_bank_statement || 0}</p>
                </div>
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-2.5">
                  <p className="text-[0.72rem] font-bold uppercase text-muted">Unexpected In Bank</p>
                  <p className="mt-1 text-lg font-bold text-primary tabular-nums">{latestRun.summary?.unexpected_in_bank_statement || 0}</p>
                </div>
              </div>
            </>
          )}
        </div>

        <div className="dashboard-glass p-6">
          <div className="mb-4"><p className="dashboard-kicker">CashPulse guide</p><h3 className="mt-1 text-lg font-semibold text-white">Keep your cash position healthy</h3></div>
          {(() => {
            const guideSlides = [
              { title: 'Start with the CashPulse flow', copy: 'Set up your company billing details from the top-left profile area, then use the dashboard to see your cash position, inflows, outflows, and runway in one place.' },
              { title: 'Stay ahead of AP and AR', copy: 'Create and review payables and receivables, watch due dates and balances, and record collections or vendor payments so your cash position stays current.' },
              { title: 'Keep every rupee connected', copy: 'Upload bank statements for reconciliation, resolve unmatched transactions, and submit reimbursement claims in the Expense Portal so your books remain complete.' },
            ];
            const slide = guideSlides[guideSlide];
            const previous = () => setGuideSlide((current) => (current + guideSlides.length - 1) % guideSlides.length);
            const next = () => setGuideSlide((current) => (current + 1) % guideSlides.length);
            return (
              <div
                className="text-sm"
                onTouchStart={(event) => { guideTouchStartRef.current = event.touches[0].clientX; }}
                onTouchEnd={(event) => { const start = guideTouchStartRef.current; if (start == null) return; const delta = event.changedTouches[0].clientX - start; if (Math.abs(delta) > 40) (delta < 0 ? next : previous)(); guideTouchStartRef.current = null; }}
              >
                <div className="cashpulse-guide-item min-h-28 rounded-xl border border-white/15 bg-white/[0.06] p-4">
                  <div className="flex items-center justify-between gap-3"><span className="cashpulse-guide-number font-semibold">0{guideSlide + 1} / 03</span><span className="text-xs text-slate-500">Swipe to explore</span></div>
                  <p className="cashpulse-guide-copy mt-3"><strong>{slide.title}.</strong> {slide.copy}</p>
                </div>
                <div className="mt-3 flex items-center justify-between">
                  <button type="button" onClick={previous} className="text-xs font-semibold text-secondary hover:text-secondary-hover">← Previous</button>
                  <div className="flex gap-1.5" aria-label="CashPulse guide slides">{guideSlides.map((item, index) => <button key={item.title} type="button" aria-label={`Go to guide slide ${index + 1}`} aria-pressed={guideSlide === index} onClick={() => setGuideSlide(index)} className={`h-2 w-2 rounded-full ${guideSlide === index ? 'bg-cyan-500' : 'bg-slate-300'}`} />)}</div>
                  <button type="button" onClick={next} className="text-xs font-semibold text-secondary hover:text-secondary-hover">Next →</button>
                </div>
              </div>
            );
          })()}
          <h3 className="mt-5 border-t border-white/10 pt-5 text-sm font-semibold text-white">MSME Compliance Alerts</h3>
          <div className="flex flex-col gap-3">
            {(data?.msme_alerts || []).map((alert, idx) => (
              <div key={idx} className="rounded-r-md border-l-4 border-rose-500 bg-rose-50 px-4 py-3 text-sm text-rose-900">
                <strong>{alert.vendor}</strong>: Payment of <strong>{formatMoney(alert.amount)}</strong> due in{' '}
                <strong>{alert.days_remaining} days</strong> (Deadline: {alert.deadline})
              </div>
            ))}
            {(data?.msme_alerts || []).length === 0 && (
              <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-3.5 text-sm text-text">
                No MSME compliance alerts. All vendor payments are on track.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
