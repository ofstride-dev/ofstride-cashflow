import { useEffect, useRef, useState } from "react";
import { Navigate } from "react-router-dom";
import { useCashflowAuth } from "../context/CashflowAuthContext";
import { canUseCashflow, hasCashflowRole } from "../auth/cashflowPermissions";

function CashflowProtectedRoute({ children, adminOnly = false, allowedRoles = null, allowWithoutCompany = false }) {
  const { session, profile, profileError, loading, refreshProfile } = useCashflowAuth();
  const attemptedRecoveryRef = useRef(false);
  const [retryingProfile, setRetryingProfile] = useState(false);

  useEffect(() => {
    attemptedRecoveryRef.current = false;
  }, [session?.user?.id]);

  useEffect(() => {
    if (!session || loading || profile || (!profileError && profile !== null) || attemptedRecoveryRef.current) {
      return;
    }

    attemptedRecoveryRef.current = true;
    setRetryingProfile(true);
    Promise.resolve(refreshProfile())
      .catch(() => null)
      .finally(() => setRetryingProfile(false));
  }, [session, profile, profileError, loading, refreshProfile]);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-surface">
        <p className="text-sm text-muted">Loading...</p>
      </div>
    );
  }

  if (!session) {
    return <Navigate to="/cashflow/login" replace />;
  }

  // If we have a session but the profile query failed (e.g. RLS misconfig /
  // 500), don't let the user through to pages that dereference `profile.id`
  // or `profile.role` — that would crash. Show a clear error instead.
  if (profileError || !profile) {
    return (
      <div className="pt-12 sm:pt-16 min-h-screen bg-surface">
        <div className="max-w-md mx-auto px-4 sm:px-6 lg:px-8 py-10">
          <div className="bg-white rounded-2xl p-6 shadow-sm text-center">
            <h1 className="text-lg font-semibold text-primary mb-2">Profile unavailable</h1>
            <p className="text-sm text-muted mb-4">
              We couldn't load your Cashflow profile. This usually means the database schema
              hasn't been applied yet, or row-level security is misconfigured. Please run
              <code className="mx-1 px-1 py-0.5 rounded bg-slate-100 text-xs">the Cashflow Supabase setup script</code>
              in the Supabase SQL editor and sign in again.
            </p>
            {profileError?.message ? (
              <p className="text-xs text-red-600 bg-red-50 border border-red-100 rounded-xl px-3 py-2 mb-4">
                {profileError.message}
              </p>
            ) : null}
            <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
              <button
                type="button"
                onClick={() => {
                  setRetryingProfile(true);
                  Promise.resolve(refreshProfile())
                    .catch(() => null)
                    .finally(() => setRetryingProfile(false));
                }}
                className="inline-flex items-center justify-center bg-primary text-white px-5 py-2.5 rounded-xl font-semibold text-sm"
              >
                {retryingProfile ? "Retrying..." : "Retry profile"}
              </button>
            <a
              href="/cashflow/login"
              className="inline-flex items-center justify-center border border-slate-200 px-5 py-2.5 rounded-xl font-semibold text-sm text-primary"
            >
              Back to sign in
            </a>
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (!allowWithoutCompany && !canUseCashflow(profile)) {
    return <Navigate to="/cashflow/expense/company-profile" replace />;
  }

  if (adminOnly && !hasCashflowRole(profile, ["owner", "admin", "finance"])) {
    return <Navigate to="/cashflow/dashboard" replace />;
  }

  if (!hasCashflowRole(profile, allowedRoles)) {
    return <Navigate to="/cashflow/dashboard" replace />;
  }

  return children;
}

export default CashflowProtectedRoute;