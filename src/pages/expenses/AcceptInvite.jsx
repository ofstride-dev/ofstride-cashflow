import { useMemo, useState } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { getCashflowPostAuthRoute, useCashflowAuth } from "../../context/CashflowAuthContext";

function AcceptInvite() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { session, profile, acceptInvite, loading, signOut } = useCashflowAuth();
  const inviteToken = useMemo(() => String(searchParams.get("token") || "").trim(), [searchParams]);
  const invitedEmail = useMemo(() => String(searchParams.get("email") || "").trim().toLowerCase(), [searchParams]);
  const invitedRole = useMemo(() => String(searchParams.get("role") || "").trim().toLowerCase(), [searchParams]);
  const sessionEmail = String(session?.user?.email || "").trim().toLowerCase();
  const emailMismatch = Boolean(invitedEmail && session && sessionEmail !== invitedEmail);
  const inviteLabel = invitedRole === "admin" ? "Admin" : "Team Member";
  const [fullName, setFullName] = useState(profile?.full_name || "");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  if (!inviteToken) {
    return <Navigate to="/cashflow/expense/login" replace />;
  }

  if (!loading && !session) {
    const params = new URLSearchParams({ token: inviteToken });
    if (invitedEmail) params.set("email", invitedEmail);
    if (invitedRole) params.set("role", invitedRole);
    return <Navigate to={`/cashflow/expense/login?${params.toString()}`} replace />;
  }

  const handleSubmit = async (event) => {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      const result = await acceptInvite(inviteToken, fullName.trim());
      navigate(getCashflowPostAuthRoute({ session, profile: result?.profile }) || "/cashflow/login", { replace: true });
    } catch (nextError) {
      setError(nextError?.message || "Invite could not be accepted.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="max-w-xl mx-auto bg-white rounded-2xl shadow-sm p-6 sm:p-8">
      <h1 className="text-2xl font-semibold text-primary mb-2">Accept {inviteLabel} Invite</h1>
      <p className="text-sm text-muted mb-6">
        Sign in with the invited email address, confirm your name, and join the workspace{invitedRole ? ` as ${invitedRole}` : ""}.
      </p>

      {invitedEmail ? (
        <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700 mb-4">
          Invited email: <strong>{invitedEmail}</strong>
        </div>
      ) : null}

      {session ? (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 mb-4">
          Signed in as <strong>{session.user?.email || "unknown user"}</strong>.
          {invitedEmail && sessionEmail !== invitedEmail ? " This does not match the invited email." : ""}
        </div>
      ) : null}

      {emailMismatch ? (
        <div className="flex flex-col sm:flex-row gap-3 mb-4">
          <button
            type="button"
            className="btn-ui btn-ui-danger"
            onClick={async () => {
              await signOut();
              const params = new URLSearchParams({ token: inviteToken, email: invitedEmail });
              if (invitedRole) params.set("role", invitedRole);
              navigate(`/cashflow/expense/login?${params.toString()}`, { replace: true });
            }}
          >
            Sign out and continue with invited account
          </button>
        </div>
      ) : null}

      {error && (
        <div className="rounded-xl border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800 mb-4">
          {error}
        </div>
      )}

      <form className="space-y-4" onSubmit={handleSubmit}>
        <div>
          <label className="block text-sm font-medium text-primary mb-1">Full Name</label>
          <input
            type="text"
            required
            value={fullName}
            onChange={(event) => setFullName(event.target.value)}
            className="w-full px-4 py-3 rounded-xl border border-slate-200 focus:border-secondary focus:ring-2 focus:ring-secondary/20 outline-none"
          />
        </div>
        <button type="submit" disabled={submitting || emailMismatch} className="w-full btn-ui btn-ui-primary">
          {emailMismatch ? "Use the invited account to continue" : submitting ? "Joining workspace..." : "Accept Invite"}
        </button>
      </form>
    </div>
  );
}

export default AcceptInvite;
