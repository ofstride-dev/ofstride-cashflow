import { useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { useCashflowAuth } from "../../context/CashflowAuthContext";

function CashflowOnboarding() {
  const navigate = useNavigate();
  const { user, profile, onboardOwner, hasCompany } = useCashflowAuth();
  const [companyName, setCompanyName] = useState("");
  const [fullName, setFullName] = useState(profile?.full_name || user?.user_metadata?.full_name || "");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  if (hasCompany) {
    return <Navigate to="/cashflow/dashboard" replace />;
  }

  const handleSubmit = async (event) => {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      await onboardOwner(companyName.trim(), fullName.trim(), false);
      navigate("/cashflow/dashboard", { replace: true });
    } catch (nextError) {
      setError(nextError?.message || "Could not create your workspace.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto bg-white rounded-2xl shadow-sm p-6 sm:p-8">
      <h1 className="text-2xl font-semibold text-primary mb-2">Create Your Workspace</h1>
      <p className="text-sm text-muted mb-6">
        Finish the first-time setup to become the workspace owner and unlock cashflow approvals and admin invites.
      </p>

      {error && (
        <div className="rounded-xl border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800 mb-4">
          {error}
        </div>
      )}

      <form className="space-y-4" onSubmit={handleSubmit}>
        <div>
          <label className="block text-sm font-medium text-primary mb-1">Your Name</label>
          <input
            type="text"
            required
            value={fullName}
            onChange={(event) => setFullName(event.target.value)}
            className="w-full px-4 py-3 rounded-xl border border-slate-200 focus:border-secondary focus:ring-2 focus:ring-secondary/20 outline-none"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-primary mb-1">Company Name</label>
          <input
            type="text"
            required
            value={companyName}
            onChange={(event) => setCompanyName(event.target.value)}
            placeholder="OfStride Finance Demo"
            className="w-full px-4 py-3 rounded-xl border border-slate-200 focus:border-secondary focus:ring-2 focus:ring-secondary/20 outline-none"
          />
        </div>
        <button type="submit" disabled={submitting} className="w-full btn-ui btn-ui-primary">
          {submitting ? "Creating workspace..." : "Create Workspace"}
        </button>
      </form>
    </div>
  );
}

export default CashflowOnboarding;
