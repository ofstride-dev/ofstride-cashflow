import React, { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { cashflowFetch, parseCashflowResponse } from '../../services/cashflowApi';
import { useCashflowAuth } from '../../context/CashflowAuthContext';

function formatMoney(value) {
  const amount = Number(value || 0);
  return `₹${amount.toLocaleString('en-IN')}`;
}

function SafeBar({ label, value, max, color }) {
  const width = max > 0 ? Math.max(4, Math.round((value / max) * 100)) : 0;
  return (
    <div style={{ marginBottom: '0.65rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.82rem', marginBottom: '0.25rem' }}>
        <span style={{ color: '#475569' }}>{label}</span>
        <strong style={{ color: '#0f172a' }}>{formatMoney(value)}</strong>
      </div>
      <div style={{ width: '100%', height: 10, borderRadius: 999, background: '#eef2f7', overflow: 'hidden' }}>
        <div style={{ width: `${width}%`, height: '100%', background: color, borderRadius: 999 }} />
      </div>
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
  const monthlyMax = useMemo(() => {
    return monthlyTrend.reduce((acc, point) => Math.max(acc, Number(point.inflow || 0), Number(point.outflow || 0)), 0);
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
    ? { bg: '#fff1f2', border: '#fecdd3', text: '#be123c', pill: '#e11d48' }
    : latestRun?.risk_level === 'medium'
      ? { bg: '#fffbeb', border: '#fde68a', text: '#a16207', pill: '#d97706' }
      : { bg: '#ecfdf5', border: '#a7f3d0', text: '#047857', pill: '#10b981' };

  if (loading) return <div style={{ padding: '1rem', color: '#475569', fontWeight: 500 }}>Loading Cash Flow Metrics...</div>;

  return (
    <div style={{ maxWidth: '1200px', margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: '1rem', flexWrap: 'wrap', marginBottom: '1.25rem' }}>
        <div>
          <h2 style={{ fontSize: '1.75rem', fontWeight: 700, color: '#0f172a', marginTop: 0, marginBottom: '0.35rem' }}>
            Cash Flow Overview
          </h2>
          <p style={{ margin: 0, color: '#64748b', fontSize: '0.9rem' }}>
            Window: {data?.period?.start_date || '-'} to {data?.period?.end_date || '-'}
          </p>
        </div>

        <div style={{ display: 'inline-flex', border: '1px solid #dbe4ee', borderRadius: 12, overflow: 'hidden', background: '#fff' }}>
          {[
            { key: '1d', label: '1 Day' },
            { key: '7d', label: '7 Days' },
            { key: '30d', label: '30 Days' },
            { key: 'month', label: 'Current Month' },
            { key: 'custom', label: 'Custom' },
          ].map((item) => {
            const active = periodKey === item.key;
            return (
              <button
                key={item.key}
                type="button"
                onClick={() => setPeriodKey(item.key)}
                style={{
                  border: 'none',
                  borderRight: item.key === 'custom' ? 'none' : '1px solid #e2e8f0',
                  padding: '0.55rem 0.9rem',
                  fontSize: '0.82rem',
                  fontWeight: 700,
                  cursor: 'pointer',
                  color: active ? '#ffffff' : '#334155',
                  background: active ? '#0f172a' : '#ffffff',
                }}
              >
                {item.label}
              </button>
            );
          })}
        </div>
        {periodKey === 'custom' && (
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: '0.45rem', marginTop: '0.55rem' }}>
            <input
              type="date"
              value={customStartDate}
              max={customEndDate}
              onChange={(e) => setCustomStartDate(e.target.value)}
              style={{ border: '1px solid #dbe4ee', borderRadius: 8, padding: '0.4rem 0.55rem', fontSize: '0.8rem', color: '#334155' }}
            />
            <span style={{ fontSize: '0.78rem', color: '#64748b' }}>to</span>
            <input
              type="date"
              value={customEndDate}
              min={customStartDate}
              max={todayIso}
              onChange={(e) => setCustomEndDate(e.target.value)}
              style={{ border: '1px solid #dbe4ee', borderRadius: 8, padding: '0.4rem 0.55rem', fontSize: '0.8rem', color: '#334155' }}
            />
          </div>
        )}
      </div>

      {/* Summary Cards Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '1.25rem', marginBottom: '2rem' }}>
        <div style={{ padding: '1.25rem', background: 'linear-gradient(145deg, #ffffff, #f5f9ff)', borderRadius: '14px', border: '1px solid #dbeafe', boxShadow: '0 10px 24px rgba(15,23,42,0.05)' }}>
          <span style={{ fontSize: '0.85rem', color: '#64748b', fontWeight: 500 }}>Cash Received</span>
          <h3 style={{ fontSize: '1.5rem', fontWeight: 700, color: '#16a34a', margin: '0.5rem 0 0 0' }}>
            ₹{(data?.summary?.cash_received || 0).toLocaleString('en-IN')}
          </h3>
        </div>

        <div style={{ padding: '1.25rem', background: 'linear-gradient(145deg, #ffffff, #fff7f7)', borderRadius: '14px', border: '1px solid #fee2e2', boxShadow: '0 10px 24px rgba(15,23,42,0.05)' }}>
          <span style={{ fontSize: '0.85rem', color: '#64748b', fontWeight: 500 }}>Cash Payable</span>
          <h3 style={{ fontSize: '1.5rem', fontWeight: 700, color: '#dc2626', margin: '0.5rem 0 0 0' }}>
            ₹{(data?.summary?.cash_payable || 0).toLocaleString('en-IN')}
          </h3>
        </div>

        <div style={{ padding: '1.25rem', background: 'linear-gradient(145deg, #ffffff, #fefce8)', borderRadius: '14px', border: '1px solid #fef08a', boxShadow: '0 10px 24px rgba(15,23,42,0.05)' }}>
          <span style={{ fontSize: '0.85rem', color: '#64748b', fontWeight: 500 }}>Customer Money Pending</span>
          <h3 style={{ fontSize: '1.5rem', fontWeight: 700, color: '#a16207', margin: '0.5rem 0 0 0' }}>
            {formatMoney(data?.summary?.cash_pending || 0)}
          </h3>
        </div>

        <div style={{ padding: '1.25rem', background: 'linear-gradient(145deg, #ffffff, #fff7f7)', borderRadius: '14px', border: '1px solid #fee2e2', boxShadow: '0 10px 24px rgba(15,23,42,0.05)' }}>
          <span style={{ fontSize: '0.85rem', color: '#64748b', fontWeight: 500 }}>Cash Outflow</span>
          <h3 style={{ fontSize: '1.5rem', fontWeight: 700, color: '#dc2626', margin: '0.5rem 0 0 0' }}>
            ₹{(data?.summary?.cash_outflow || 0).toLocaleString('en-IN')}
          </h3>
        </div>

        <div style={{ padding: '1.25rem', background: 'linear-gradient(145deg, #ffffff, #f0f9ff)', borderRadius: '14px', border: '1px solid #dbeafe', boxShadow: '0 10px 24px rgba(15,23,42,0.05)' }}>
          <span style={{ fontSize: '0.85rem', color: '#64748b', fontWeight: 500 }}>Money Left (In - Out)</span>
          <h3 style={{ fontSize: '1.5rem', fontWeight: 700, color: '#0284c7', margin: '0.5rem 0 0 0' }}>
            {formatMoney(data?.summary?.net_cash_position || 0)}
          </h3>
        </div>

        <div style={{ padding: '1.25rem', background: 'linear-gradient(145deg, #ffffff, #f0fdf4)', borderRadius: '14px', border: '1px solid #bbf7d0', boxShadow: '0 10px 24px rgba(15,23,42,0.05)' }}>
          <span style={{ fontSize: '0.85rem', color: '#64748b', fontWeight: 500 }}>Petty Cash Balance</span>
          <h3 style={{ fontSize: '1.5rem', fontWeight: 700, color: '#15803d', margin: '0.5rem 0 0 0' }}>
            ₹{(data?.summary?.petty_cash_balance || 0).toLocaleString('en-IN')}
          </h3>
        </div>

        <div style={{ padding: '1.25rem', background: 'linear-gradient(145deg, #ffffff, #eef2ff)', borderRadius: '14px', border: '1px solid #c7d2fe', boxShadow: '0 10px 24px rgba(15,23,42,0.05)' }}>
          <span style={{ fontSize: '0.85rem', color: '#64748b', fontWeight: 500 }}>Months You Can Run</span>
          <h3 style={{ fontSize: '1.5rem', fontWeight: 700, color: '#0284c7', margin: '0.5rem 0 0 0' }}>
            {data?.summary?.runway_months == null ? 'N/A' : `${data.summary.runway_months} Months`}
          </h3>
        </div>
      </div>

      <div className="cashflow-trend-breakdown-grid" style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: '1.25rem', marginBottom: '2rem' }}>
        <div className="cashflow-trend-breakdown-card" style={{ backgroundColor: '#ffffff', padding: '1.5rem', borderRadius: '14px', border: '1px solid #e2e8f0', boxShadow: '0 12px 28px rgba(15,23,42,0.05)' }}>
          <h3 style={{ fontSize: '1.05rem', fontWeight: 700, color: '#0f172a', marginTop: 0, marginBottom: '1rem' }}>Last 3 Months: Inflow vs Outflow</h3>
          {monthlyTrend.length === 0 ? (
            <div style={{ color: '#64748b', fontSize: '0.9rem' }}>No monthly trend data yet.</div>
          ) : (
            <div style={{ display: 'grid', gap: '0.6rem' }}>
              {monthlyTrend.map((point) => (
                <div key={point.month} style={{ border: '1px solid #edf2f7', borderRadius: 10, padding: '0.6rem 0.75rem' }}>
                  <div style={{ fontSize: '0.8rem', color: '#64748b', marginBottom: '0.4rem', fontWeight: 700 }}>{point.label}</div>
                  <div style={{ display: 'grid', gridTemplateColumns: '70px 1fr 100px', gap: '0.5rem', alignItems: 'center', marginBottom: '0.35rem' }}>
                    <span style={{ fontSize: '0.78rem', color: '#166534' }}>Inflow</span>
                    <div style={{ background: '#ecfdf3', borderRadius: 999, height: 8, overflow: 'hidden' }}>
                      <div style={{ width: `${monthlyMax > 0 ? Math.max(4, Math.round((Number(point.inflow || 0) / monthlyMax) * 100)) : 0}%`, height: '100%', background: '#16a34a' }} />
                    </div>
                    <strong style={{ fontSize: '0.82rem', color: '#0f172a', textAlign: 'right' }}>{formatMoney(point.inflow)}</strong>
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: '70px 1fr 100px', gap: '0.5rem', alignItems: 'center' }}>
                    <span style={{ fontSize: '0.78rem', color: '#b91c1c' }}>Outflow</span>
                    <div style={{ background: '#fff1f2', borderRadius: 999, height: 8, overflow: 'hidden' }}>
                      <div style={{ width: `${monthlyMax > 0 ? Math.max(4, Math.round((Number(point.outflow || 0) / monthlyMax) * 100)) : 0}%`, height: '100%', background: '#dc2626' }} />
                    </div>
                    <strong style={{ fontSize: '0.82rem', color: '#0f172a', textAlign: 'right' }}>{formatMoney(point.outflow)}</strong>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="cashflow-trend-breakdown-card" style={{ backgroundColor: '#ffffff', padding: '1.5rem', borderRadius: '14px', border: '1px solid #e2e8f0', boxShadow: '0 12px 28px rgba(15,23,42,0.05)' }}>
          <h3 style={{ fontSize: '1.05rem', fontWeight: 700, color: '#0f172a', marginTop: 0, marginBottom: '1rem' }}>This Period Breakdown</h3>
          <SafeBar label="Money Received from Customers" value={periodBreakdown.inflowCustomers} max={periodBreakdown.max} color="#16a34a" />
          <SafeBar label="Cash Added to Petty Cash" value={periodBreakdown.inflowPetty} max={periodBreakdown.max} color="#0ea5e9" />
          <SafeBar label="Paid to Vendors" value={periodBreakdown.outflowVendors} max={periodBreakdown.max} color="#dc2626" />
          <SafeBar label="Spent from Petty Cash" value={periodBreakdown.outflowPetty} max={periodBreakdown.max} color="#f59e0b" />
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1.35fr 1fr', gap: '1.25rem', marginBottom: '2rem' }}>
        <div style={{ background: '#ffffff', padding: '1.5rem', borderRadius: '14px', border: '1px solid #e2e8f0', boxShadow: '0 12px 28px rgba(15,23,42,0.05)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '1rem', marginBottom: '0.9rem' }}>
            <h3 style={{ fontSize: '1.1rem', fontWeight: 600, color: '#0f172a', margin: 0 }}>
              Reconciliation Watch
            </h3>
            <Link
              to="/cashflow/reconcile"
              style={{ fontSize: '0.85rem', fontWeight: 700, color: '#1d4ed8', textDecoration: 'none' }}
            >
              Open Bank Reconcile
            </Link>
          </div>

          {!latestRun && (
            <div style={{ padding: '0.95rem 1rem', borderRadius: '10px', background: '#f8fafc', border: '1px dashed #cbd5e1', color: '#334155' }}>
              No reconciliation runs yet. Upload a bank statement to generate mismatch intelligence.
            </div>
          )}

          {latestRun && (
            <>
              <div style={{
                background: riskTone.bg,
                border: `1px solid ${riskTone.border}`,
                borderRadius: '11px',
                padding: '0.95rem 1rem',
                color: riskTone.text,
                marginBottom: '0.9rem',
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '0.75rem' }}>
                  <div style={{ fontWeight: 700 }}>
                    Latest Run Health
                  </div>
                  <span style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    borderRadius: 999,
                    padding: '0.2rem 0.55rem',
                    fontSize: '0.72rem',
                    fontWeight: 700,
                    color: '#ffffff',
                    background: riskTone.pill,
                    textTransform: 'uppercase',
                    letterSpacing: '0.03em',
                  }}>
                    {latestRun.risk_level}
                  </span>
                </div>
                <div style={{ marginTop: '0.45rem', fontSize: '0.92rem' }}>
                  {latestRun.source_file_name || 'Source file'} ({latestRun.start_date} to {latestRun.end_date})
                </div>
              </div>

              <div className="reconcile-status-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: '0.65rem' }}>
                <div className="reconcile-status-card" style={{ border: '1px solid #dcfce7', borderRadius: '10px', padding: '0.65rem', background: '#f0fdf4' }}>
                  <p className="reconcile-status-label" style={{ margin: 0, fontSize: '0.74rem', color: '#166534', textTransform: 'uppercase', fontWeight: 700 }}>Matched</p>
                  <p className="reconcile-status-value" style={{ margin: '0.25rem 0 0', fontSize: '1.1rem', fontWeight: 700, color: '#166534' }}>{latestRun.summary?.matched || 0}</p>
                </div>
                <div className="reconcile-status-card" style={{ border: '1px solid #fde68a', borderRadius: '10px', padding: '0.65rem', background: '#fffbeb' }}>
                  <p className="reconcile-status-label" style={{ margin: 0, fontSize: '0.74rem', color: '#a16207', textTransform: 'uppercase', fontWeight: 700 }}>Amount Mismatch</p>
                  <p className="reconcile-status-value" style={{ margin: '0.25rem 0 0', fontSize: '1.1rem', fontWeight: 700, color: '#a16207' }}>{latestRun.summary?.amount_mismatch || 0}</p>
                </div>
                <div className="reconcile-status-card" style={{ border: '1px solid #fecdd3', borderRadius: '10px', padding: '0.65rem', background: '#fff1f2' }}>
                  <p className="reconcile-status-label" style={{ margin: 0, fontSize: '0.74rem', color: '#be123c', textTransform: 'uppercase', fontWeight: 700 }}>Missing In Bank Statement</p>
                  <p className="reconcile-status-value" style={{ margin: '0.25rem 0 0', fontSize: '1.1rem', fontWeight: 700, color: '#be123c' }}>{latestRun.summary?.missing_in_bank_statement || 0}</p>
                </div>
                <div className="reconcile-status-card" style={{ border: '1px solid #e2e8f0', borderRadius: '10px', padding: '0.65rem', background: '#f8fafc' }}>
                  <p className="reconcile-status-label" style={{ margin: 0, fontSize: '0.74rem', color: '#475569', textTransform: 'uppercase', fontWeight: 700 }}>Unexpected In Bank Statement</p>
                  <p className="reconcile-status-value" style={{ margin: '0.25rem 0 0', fontSize: '1.1rem', fontWeight: 700, color: '#334155' }}>{latestRun.summary?.unexpected_in_bank_statement || 0}</p>
                </div>
              </div>
            </>
          )}
        </div>

        <div style={{ backgroundColor: '#ffffff', padding: '1.5rem', borderRadius: '14px', border: '1px solid #e2e8f0', boxShadow: '0 12px 28px rgba(15,23,42,0.05)' }}>
          <h3 style={{ fontSize: '1.1rem', fontWeight: 600, color: '#0f172a', marginTop: 0, marginBottom: '1rem' }}>
            MSME Compliance Alerts (Section 43B(h))
          </h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            {(data?.msme_alerts || []).map((alert, idx) => (
              <div key={idx} style={{ padding: '0.85rem 1rem', backgroundColor: '#fef2f2', borderLeft: '4px solid #ef4444', borderRadius: '4px', color: '#991b1b', fontSize: '0.95rem' }}>
                <strong>{alert.vendor}</strong>: Payment of <strong>₹{alert.amount?.toLocaleString('en-IN')}</strong> due in <strong>{alert.days_remaining} days</strong> (Deadline: {alert.deadline})
              </div>
            ))}
            {(data?.msme_alerts || []).length === 0 && (
              <div style={{ padding: '0.95rem 1rem', borderRadius: '10px', background: '#f8fafc', border: '1px dashed #cbd5e1', color: '#334155' }}>
                No MSME compliance alerts. All vendor payments are on track.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}