import { useEffect, useState, useRef } from "react";
import { Link } from "react-router-dom";
import { Plus, ShieldCheck, Download, FileSpreadsheet, FileText } from "lucide-react";
import { useCashflowAuth } from "../../context/CashflowAuthContext";
import { listMyExpenses, STATUS_LABELS, STATUS_BADGE_CLASSES } from "../../services/expenseService";
import { downloadExpenseAsXlsx, downloadExpenseAsPdf } from "../../services/expenseExport";

function StatusBadge({ status }) {
  const classes = STATUS_BADGE_CLASSES[status] || "bg-slate-100 text-slate-700 border-slate-200";
  return (
    <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium border ${classes}`}>
      {STATUS_LABELS[status] || status}
    </span>
  );
}

function MyExpenses() {
  const { user, profile, signOut } = useCashflowAuth();
  const [expenses, setExpenses] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [openMenu, setOpenMenu] = useState(null);
  const menuRef = useRef(null);

  useEffect(() => {
    if (!user?.id) {
      return;
    }
    let isMounted = true;
    setLoading(true);
    listMyExpenses(user.id)
      .then((data) => {
        if (isMounted) setExpenses(data);
      })
      .catch(() => {
        if (isMounted) setError("Could not load your claims right now. Please try again shortly.");
      })
      .finally(() => {
        if (isMounted) setLoading(false);
      });
    return () => {
      isMounted = false;
    };
  }, [user?.id]);

  useEffect(() => {
    const handleClickOutside = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setOpenMenu(null);
      }
    };
    if (openMenu) {
      document.addEventListener("mousedown", handleClickOutside);
      return () => document.removeEventListener("mousedown", handleClickOutside);
    }
  }, [openMenu]);

  const handleDownload = (e, expense, format) => {
    e.preventDefault();
    e.stopPropagation();
    setOpenMenu(null);
    if (format === "xlsx") {
      downloadExpenseAsXlsx(expense);
    } else {
      downloadExpenseAsPdf(expense);
    }
  };

  return (
    <div className="bg-surface">
      <section className="py-2 sm:py-3 lg:py-4">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex flex-wrap items-center justify-end gap-2 mb-8">
            <div className="flex items-center gap-2">
              {profile?.role === "admin" && (
                <Link
                  to="/cashflow/expense/admin"
                  className="btn-ui btn-ui-info"
                >
                  <ShieldCheck className="w-4 h-4" />
                  Admin Queue
                </Link>
              )}
              <Link
                to="/cashflow/expense/new"
                className="btn-ui btn-ui-primary"
              >
                <Plus className="w-4 h-4" />
                New Claim
              </Link>
              <button
                type="button"
                onClick={signOut}
                className="btn-ui btn-ui-neutral"
              >
                Sign Out
              </button>
            </div>
          </div>

          {loading && <p className="text-sm text-muted py-4 text-center">Loading your claims...</p>}

          {!loading && error && (
            <div className="rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-800">
              {error}
            </div>
          )}

          {!loading && !error && expenses.length === 0 && (
            <div className="bg-white rounded-2xl p-8 shadow-sm text-center">
              <p className="text-sm text-muted">You haven't submitted any expense claims yet.</p>
            </div>
          )}

          {!loading && !error && expenses.length > 0 && (
            <div className="bg-white rounded-2xl shadow-sm divide-y divide-slate-100">
              {expenses.map((expense) => (
                <div
                  key={expense.id}
                  className="flex items-center justify-between gap-4 px-6 py-4 hover:bg-surface transition-colors"
                >
                  <Link
                    to={`/cashflow/expense/${expense.id}`}
                    className="flex items-center gap-4 min-w-0 flex-1"
                  >
                    <div className="min-w-0">
                      <p className="font-medium text-primary truncate">{expense.category}</p>
                      <p className="text-sm text-muted truncate">
                        {expense.spend_date} · {expense.currency} {Number(expense.amount).toFixed(2)}
                      </p>
                    </div>
                    <StatusBadge status={expense.status} />
                  </Link>
                  <div className="relative" ref={openMenu === expense.id ? menuRef : null}>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        setOpenMenu(openMenu === expense.id ? null : expense.id);
                      }}
                      className="inline-flex items-center gap-1.5 text-slate-500 hover:text-primary px-2 py-1.5 rounded-lg hover:bg-slate-100 transition-colors"
                      title="Download claim form"
                    >
                      <Download className="w-4 h-4" />
                    </button>
                    {openMenu === expense.id && (
                      <div className="absolute right-0 top-full mt-1 z-10 bg-white rounded-xl shadow-lg border border-slate-200 py-1 w-44">
                        <button
                          type="button"
                          onClick={(e) => handleDownload(e, expense, "xlsx")}
                          className="w-full flex items-center gap-2 px-3 py-2 text-sm text-text hover:bg-surface transition-colors"
                        >
                          <FileSpreadsheet className="w-4 h-4 text-emerald-600" />
                          Download Excel
                        </button>
                        <button
                          type="button"
                          onClick={(e) => handleDownload(e, expense, "pdf")}
                          className="w-full flex items-center gap-2 px-3 py-2 text-sm text-text hover:bg-surface transition-colors"
                        >
                          <FileText className="w-4 h-4 text-red-600" />
                          Download PDF
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

export default MyExpenses;
