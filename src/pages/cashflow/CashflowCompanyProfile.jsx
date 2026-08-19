import { useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { useCashflowAuth } from "../../context/CashflowAuthContext";

function CashflowCompanyProfile() {
  const navigate = useNavigate();
  const { user, profile, onboardOwner, hasCompany, loading } = useCashflowAuth();

  const [companyName, setCompanyName] = useState("");
  const [fullName, setFullName] = useState(profile?.full_name || user?.user_metadata?.full_name || "");
  const [companyEmail, setCompanyEmail] = useState(user?.email || profile?.email || "");
  const [website, setWebsite] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  // If the user already has a company, send them straight to the dashboard.
  if (!loading && hasCompany) {
    return <Navigate to="/cashflow/dashboard" replace />;
  }

  const handleSubmit = async (event) => {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      await onboardOwner(companyName.trim(), fullName.trim(), false, companyEmail.trim());
      navigate("/cashflow/dashboard", { replace: true });
    } catch (nextError) {
      setError(nextError?.message || "Could not create your company profile.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto">
      <div className="bg-white rounded-2xl shadow-sm p-6 sm:p-8">
        <div className="mb-2 inline-flex items-center gap-2 rounded-full bg-sky-50 border border-sky-200 px-3 py-1 text-xs font-semibold text-sky-700">
          <span className="h-1.5 w-1.5 rounded-full bg-sky-500 animate-pulse" />
          First-time setup
        </div>
        <h1 className="text-2xl font-semibold text-primary mb-2">Create Your Company Profile</h1>
        <p className="text-sm text-muted mb-6">
          Tell us about your company to get started. You'll be taken to your Cashflow dashboard once this is complete.
        </p>

        {error && (
          <div className="rounded-xl border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800 mb-4">
            {error}
          </div>
        )}

        <form className="space-y-4" onSubmit={handleSubmit}>
          <div>
            <label className="block text-sm font-medium text-primary mb-1">Company Name *</label>
            <input
              type="text"
              required
              value={companyName}
              onChange={(event) => setCompanyName(event.target.value)}
              placeholder="Acme Pvt Ltd"
              className="w-full px-4 py-3 rounded-xl border border-slate-200 focus:border-secondary focus:ring-2 focus:ring-secondary/20 outline-none"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-primary mb-1">Company Email *</label>
            <input
              type="email"
              required
              value={companyEmail}
              onChange={(event) => setCompanyEmail(event.target.value)}
              placeholder="finance@company.com"
              className="w-full px-4 py-3 rounded-xl border border-slate-200 focus:border-secondary focus:ring-2 focus:ring-secondary/20 outline-none"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-primary mb-1">Website (optional)</label>
            <input
              type="url"
              value={website}
              onChange={(event) => setWebsite(event.target.value)}
              placeholder="https://company.com"
              className="w-full px-4 py-3 rounded-xl border border-slate-200 focus:border-secondary focus:ring-2 focus:ring-secondary/20 outline-none"
            />
          </div>

          <div className="border-t border-slate-100 pt-4">
            <div>
              <label className="block text-sm font-medium text-primary mb-1">Your Name *</label>
              <input
                type="text"
                required
                value={fullName}
                onChange={(event) => setFullName(event.target.value)}
                className="w-full px-4 py-3 rounded-xl border border-slate-200 focus:border-secondary focus:ring-2 focus:ring-secondary/20 outline-none"
              />
            </div>
          </div>

          <button type="submit" disabled={submitting} className="w-full btn-ui btn-ui-primary">
            {submitting ? "Creating company profile..." : "Create Company & Continue to Dashboard"}
          </button>

          <p className="text-xs text-muted text-center">
            By creating a company profile you become the workspace owner and can invite team members to collaborate.
          </p>
        </form>
      </div>
    </div>
  );
}

export default CashflowCompanyProfile;