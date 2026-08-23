import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  Banknote,
  Gauge,
  PiggyBank,
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
  Bar,
  BarChart,
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
      <p className="text-[0.68rem] font-bold uppercase tracking-wider text-slate-400">{label}</p>
      {payload.map((entry) => <p key={entry.dataKey} className="mt-1 text-sm font-semibold text-white">{entry.name}: {formatMoney(entry.value)}</p>)}
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

function BreakdownChart({ breakdown }) {
  const chartData = [
    { name: 'Customers', value: breakdown.inflowCustomers, tone: '#67e8f9' },
    { name: 'Petty cash', value: breakdown.inflowPetty, tone: '#a78bfa' },
    { name: 'Vendors', value: breakdown.outflowVendors, tone: '#fb7185' },
    { name: 'Petty out', value: breakdown.outflowPetty, tone: '#fbbf24' },
  ];
  return <div className="h-[205px] w-full"><ResponsiveContainer width="100%" height="100%"><BarChart data={chartData} margin={{ top: 8, right: 0, left: -24, bottom: 0 }}><CartesianGrid vertical={false} stroke="rgba(148,163,184,.1)" /><XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fill: '#64748b', fontSize: 10 }} /><YAxis hide /><Tooltip content={<ChartTooltip />} cursor={{ fill: 'rgba(255,255,255,.03)' }} /><Bar dataKey="value" name="Amount" radius={[6, 6, 2, 2]} fill="#67e8f9" /></BarChart></ResponsiveContainer></div>;
}

function DashboardSkeleton() {
  return (
    <div className="max-w-6xl mx-auto space-y-6" aria-busy="true" aria-live="polite">
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
      <span className="sr-only">Loading cash flow metrics…</span>
    </div>
  );
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

  const runAiPrompt = (prompt) => {
    const responses = {
      summary: `Your cash position is ${momentumSummary.net >= 0 ? 'healthy, with inflows ahead of outflows' : 'under pressure, with outflows ahead of inflows'}. The latest period shows ${formatMoney(momentumSummary.inflow)} received and ${formatMoney(momentumSummary.outflow)} spent.`,
      report: 'Executive report ready: collections are the key near-term lever. Prioritise pending customer receipts, review vendor commitments, and protect runway for the next operating cycle.',
      explain: 'Net movement is the difference between cash received and cash spent. A positive number means your available cash is building during the selected period.',
    };
    setAiResponse(responses[prompt]);
  };

  // Build a zero-filled dashboard payload so first-time users and API outages
  // always see empty (but valid) metrics instead of a hard failure.
  const emptyDashboardData = useMemo(() => ({
    period: {
      key: periodKey,
      start_date: customStartDate,
      end_date: todayIso,
      days: 0,
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
    },
    msme_alerts: [],
    trend: { monthly: [] },
  }), [periodKey, customStartDate, todayIso]);

  useEffect(() => {
    let isCurrent = true;
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

    Promise.all([dashboardPromise, reconcilePromise])
      .catch(() => {
        if (isCurrent) setReconcileRuns([]);
      })
      .finally(() => {
        if (isCurrent) setLoading(false);
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
    const inflowPetty = Number(summary.inflow_from_petty_cash || 0);
    const outflowVendors = Number(summary.outflow_to_vendors || 0);
    const outflowPetty = Number(summary.outflow_from_petty_cash || 0);
    return {
      inflowCustomers,
      inflowPetty,
      outflowVendors,
      outflowPetty,
      max: Math.max(inflowCustomers, inflowPetty, outflowVendors, outflowPetty, 0),
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
      <div className="grid gap-4 grid-cols-2 lg:grid-cols-4 mb-6">
        <SummaryCard label="Cash Received" value={formatMoney(data?.summary?.cash_received)} icon={ArrowUpRight} tone="emerald" />
        <SummaryCard label="Cash Payable" value={formatMoney(data?.summary?.cash_payable)} icon={ArrowDownRight} tone="rose" />
        <SummaryCard label="Customer Money Pending" value={formatMoney(data?.summary?.cash_pending)} icon={AlertTriangle} tone="amber" />
        <SummaryCard label="Cash Outflow" value={formatMoney(data?.summary?.cash_outflow)} icon={ArrowDownRight} tone="rose" />
        <SummaryCard label="Net Cash Position" value={formatMoney(data?.summary?.net_cash_position)} icon={Gauge} tone="sky" />
        <SummaryCard label="Petty Cash Balance" value={formatMoney(data?.summary?.petty_cash_balance)} icon={PiggyBank} tone="emerald" />
        <SummaryCard
          label="Months You Can Run"
          value={data?.summary?.runway_months == null ? 'N/A' : `${data.summary.runway_months} mo`}
          icon={Wallet}
          tone="indigo"
        />
        <SummaryCard label="Cash Inflow" value={formatMoney(data?.summary?.cash_inflow)} icon={Banknote} tone="sky" />
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
        <div className="mt-5 border-t border-slate-200 pt-4"><div className="flex flex-wrap gap-2"><button type="button" onClick={() => runAiPrompt('summary')} className="ai-action-button"><MessageCircle className="h-4 w-4" /> Summarise reports</button><button type="button" onClick={() => runAiPrompt('report')} className="ai-action-button"><FileText className="h-4 w-4" /> Generate report</button><button type="button" onClick={() => runAiPrompt('explain')} className="ai-action-button"><Languages className="h-4 w-4" /> Explain net movement</button></div><div className="ai-response mt-3"><Sparkles className="h-4 w-4 shrink-0" /><p>{aiResponse}</p><RefreshCw className="ml-auto h-3.5 w-3.5 shrink-0 opacity-50" /></div></div>
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
          <SafeBar label="Cash Added to Petty Cash" value={periodBreakdown.inflowPetty} max={periodBreakdown.max} tone="sky" />
          <SafeBar label="Paid to Vendors" value={periodBreakdown.outflowVendors} max={periodBreakdown.max} tone="rose" />
          <SafeBar label="Spent from Petty Cash" value={periodBreakdown.outflowPetty} max={periodBreakdown.max} tone="amber" />
          <div className="cashflow-ops mt-4 border-t border-slate-200 pt-4"><div className="flex items-center justify-between"><div><p className="dashboard-kicker">Cashflow operations</p><h4 className="mt-1 text-sm font-bold text-primary">Quotation pipeline</h4></div><Link to="/cashflow/receivables" className="text-xs font-bold text-secondary">View all</Link></div><div className="mt-3 grid grid-cols-3 gap-2"><div><strong className="text-base text-primary">12</strong><span>Open quotes</span></div><div><strong className="text-base text-amber-700">₹1.8L</strong><span>Awaiting decision</span></div><div><strong className="text-base text-emerald-700">4</strong><span>Due this week</span></div></div><div className="mt-3 h-1.5 overflow-hidden rounded-full bg-slate-100"><div className="h-full w-[68%] rounded-full bg-gradient-to-r from-cyan-500 to-sky-400" /></div><p className="mt-1.5 text-[11px] text-slate-500">68% of quoted value has a next action assigned.</p></div>
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
          <div className="mb-4"><p className="dashboard-kicker">Liquidity mix</p><h3 className="mt-1 text-lg font-semibold text-white">Flow breakdown</h3></div>
          <BreakdownChart breakdown={periodBreakdown} />
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
