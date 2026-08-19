import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listAllExpenses, STATUS_LABELS, STATUS_BADGE_CLASSES, EXPENSE_STATUSES } from "../../services/expenseService";

function StatusBadge({ status }) {
  const classes = STATUS_BADGE_CLASSES[status] || "bg-slate-100 text-slate-700 border-slate-200";
  return (
    <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium border ${classes}`}>
      {STATUS_LABELS[status] || status}
    </span>
  );
}

function AdminExpenseQueue() {
  const [statusFilter, setStatusFilter] = useState("");
  const [expenses, setExpenses] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let isMounted = true;
    setLoading(true);
    setError("");
    listAllExpenses({ status: statusFilter || undefined })
      .then((data) => {
        if (isMounted) setExpenses(data);
      })
      .catch(() => {
        if (isMounted) setError("Could not load the expense queue right now. Please try again shortly.");
      })
      .finally(() => {
        if (isMounted) setLoading(false);
      });
    return () => {
      isMounted = false;
    };
  }, [statusFilter]);

  return (
    <div className="bg-surface">
      <section className="py-2 sm:py-3 lg:py-4">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex flex-wrap items-center justify-between gap-4 mb-8">
            <div>
              <h1 className="text-2xl font-semibold text-primary">Admin Expense Queue</h1>
              <p className="text-sm text-muted mt-1">All submitted claims across the company</p>
            </div>
            <Link to="/cashflow/expense" className="btn-ui btn-ui-sm btn-ui-neutral">
              ← My Claims
            </Link>
          </div>

          <div className="mb-6">
            <label className="block text-sm font-medium text-primary mb-1">Filter by status</label>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="w-full sm:w-64 px-4 py-3 rounded-xl border border-slate-200 focus:border-secondary focus:ring-2 focus:ring-secondary/20 outline-none bg-white"
            >
              <option value="">All statuses</option>
              {EXPENSE_STATUSES.map((status) => (
                <option key={status} value={status}>
                  {STATUS_LABELS[status]}
                </option>
              ))}
            </select>
          </div>

          {loading && <p className="text-sm text-muted py-4 text-center">Loading queue...</p>}

          {!loading && error && (
            <div className="rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-800">
              {error}
            </div>
          )}

          {!loading && !error && expenses.length === 0 && (
            <div className="bg-white rounded-2xl p-8 shadow-sm text-center">
              <p className="text-sm text-muted">No claims match this filter.</p>
            </div>
          )}

          {!loading && !error && expenses.length > 0 && (
            <div className="bg-white rounded-2xl shadow-sm divide-y divide-slate-100">
              {expenses.map((expense) => (
                <Link
                  key={expense.id}
                  to={`/cashflow/expense/${expense.id}`}
                  className="flex items-center justify-between gap-4 px-6 py-4 hover:bg-surface transition-colors"
                >
                  <div className="min-w-0">
                    <p className="font-medium text-primary truncate">
                      {expense.claimant_name || "Unknown claimant"}
                    </p>
                    <p className="text-sm text-muted truncate">
                      {expense.category} · {expense.spend_date} · {expense.currency} {Number(expense.amount).toFixed(2)}
                    </p>
                  </div>
                  <StatusBadge status={expense.status} />
                </Link>
              ))}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

export default AdminExpenseQueue;
