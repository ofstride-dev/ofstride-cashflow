import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { getCashflowPostAuthRoute, useCashflowAuth } from "../../context/CashflowAuthContext";
import { supabase } from "../../services/supabase";

function GoogleIcon({ className = "h-5 w-5" }) {
  return (
    <svg className={className} viewBox="0 0 24 24" aria-hidden="true">
      <path fill="#4285F4" d="M21.35 12.27c0-.72-.06-1.42-.18-2.09H12v3.96h5.24a4.48 4.48 0 0 1-1.94 2.94v2.45h3.14c1.84-1.69 2.91-4.18 2.91-7.26Z" />
      <path fill="#34A853" d="M12 21.7c2.63 0 4.84-.87 6.45-2.37l-3.14-2.45c-.87.58-1.98.92-3.31.92-2.54 0-4.69-1.72-5.46-4.03H3.3v2.53A9.74 9.74 0 0 0 12 21.7Z" />
      <path fill="#FBBC05" d="M6.54 13.77A5.85 5.85 0 0 1 6.23 12c0-.62.11-1.22.31-1.77V7.7H3.3A9.74 9.74 0 0 0 2.27 12c0 1.56.37 3.03 1.03 4.3l3.24-2.53Z" />
      <path fill="#EA4335" d="M12 6.2c1.43 0 2.72.49 3.73 1.46l2.8-2.8C16.84 3.3 14.63 2.3 12 2.3A9.74 9.74 0 0 0 3.3 7.7l3.24 2.53C7.31 7.92 9.46 6.2 12 6.2Z" />
    </svg>
  );
}

function AcceptInvite() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { session, profile, acceptInvite, loading, signIn, signInWithGoogle, signUp } = useCashflowAuth();
  const inviteToken = useMemo(() => String(searchParams.get("token") || "").trim(), [searchParams]);
  const invitedEmail = useMemo(() => String(searchParams.get("email") || "").trim().toLowerCase(), [searchParams]);
  const invitedRole = useMemo(() => String(searchParams.get("role") || "").trim().toLowerCase(), [searchParams]);
  const sessionEmail = String(session?.user?.email || "").trim().toLowerCase();
  const emailMismatch = Boolean(invitedEmail && session && sessionEmail !== invitedEmail);
  const inviteLabel = invitedRole === "admin" ? "Admin" : "Team Member";
  const [mode, setMode] = useState("create");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  if (!inviteToken) return <div className="max-w-xl mx-auto bg-white rounded-2xl shadow-sm p-6">This invite link is missing its token.</div>;

  const finishAcceptance = async (activeSession, name) => {
    if (!activeSession) throw new Error("Your account was created. Confirm your email, then open this invite link again.");
    const result = await acceptInvite(inviteToken, name);
    navigate(getCashflowPostAuthRoute({ session: activeSession, profile: result?.profile }) || "/cashflow/dashboard", { replace: true });
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      if (session) {
        await finishAcceptance(session, fullName.trim() || profile?.full_name || "Team Member");
      } else if (mode === "create") {
        if (password.length < 8) throw new Error("Password must be at least 8 characters.");
        const created = await signUp(invitedEmail, password, fullName.trim(), invitedRole || "employee");
        if (created.error) throw new Error(created.error);
        const { data } = await supabase.auth.getSession();
        await finishAcceptance(data?.session, fullName.trim());
      } else {
        const result = await signIn(invitedEmail, password);
        if (result.error) throw new Error(result.error);
        const { data } = await supabase.auth.getSession();
        await finishAcceptance(data?.session, fullName.trim());
      }
    } catch (nextError) {
      setError(nextError?.message || "Invite could not be accepted.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="max-w-xl mx-auto bg-white rounded-2xl shadow-sm p-6 sm:p-8">
      <h1 className="text-2xl font-semibold text-primary mb-2">Join your workspace</h1>
      <p className="text-sm text-muted mb-6">
        Create your account or use an existing account, then join the workspace{invitedRole ? ` as ${invitedRole}` : ""}.
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

      {!session && <div className="flex gap-2 mb-4"><button type="button" className={`btn-ui ${mode === "create" ? "btn-ui-primary" : "btn-ui-neutral"}`} onClick={() => setMode("create")}>Create account</button><button type="button" className={`btn-ui ${mode === "signin" ? "btn-ui-primary" : "btn-ui-neutral"}`} onClick={() => setMode("signin")}>I already have an account</button></div>}

      {error && (
        <div className="rounded-xl border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800 mb-4">
          {error}
        </div>
      )}

      <form className="space-y-4" onSubmit={handleSubmit}>
        <div>
          <label className="block text-sm font-medium text-primary mb-1">Your name</label>
          <input
            type="text"
            required
            value={fullName}
            onChange={(event) => setFullName(event.target.value)}
            className="w-full px-4 py-3 rounded-xl border border-slate-200 focus:border-secondary focus:ring-2 focus:ring-secondary/20 outline-none"
          />
        </div>
        {!session && <div><label className="block text-sm font-medium text-primary mb-1">Password</label><input type="password" required minLength={8} value={password} onChange={(event) => setPassword(event.target.value)} className="w-full px-4 py-3 rounded-xl border border-slate-200" /></div>}
        <button type="submit" disabled={submitting || emailMismatch} className="w-full btn-ui btn-ui-primary">
          {emailMismatch ? "Use the invited account to continue" : submitting ? "Joining workspace..." : session ? "Accept Invite" : mode === "create" ? "Create account and join" : "Sign in and join"}
        </button>
      </form>
      {!session && <button type="button" onClick={async () => { const result = await signInWithGoogle(`/cashflow/expense/accept-invite?token=${encodeURIComponent(inviteToken)}&email=${encodeURIComponent(invitedEmail)}&role=${encodeURIComponent(invitedRole)}`); if (result?.error) setError(result.error); }} className="w-full btn-ui btn-ui-neutral mt-3"><GoogleIcon className="h-5 w-5" /> Continue with Google</button>}
    </div>
  );
}

export default AcceptInvite;
