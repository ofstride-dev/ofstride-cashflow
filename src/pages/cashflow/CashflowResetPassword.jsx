import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { supabase, updatePassword } from "../../services/supabase";

function CashflowResetPassword() {
  const navigate = useNavigate();
  const [session, setSession] = useState(null);
  const [checkingSession, setCheckingSession] = useState(true);
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let mounted = true;
    const loadSession = async () => {
      const { data } = await supabase.auth.getSession();
      if (mounted) {
        setSession(data.session);
        setCheckingSession(false);
      }
    };
    loadSession();
    const { data: listener } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      if (mounted) {
        setSession(nextSession);
        setCheckingSession(false);
      }
    });
    return () => {
      mounted = false;
      listener.subscription.unsubscribe();
    };
  }, []);

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }
    setSaving(true);
    setError("");
    const { error: updateError } = await updatePassword(password);
    if (updateError) {
      setError(updateError);
      setSaving(false);
      return;
    }
    setInfo("Password updated. Redirecting to your workspace…");
    await supabase.auth.signOut();
    setTimeout(() => navigate("/cashflow/login", { replace: true }), 700);
  };

  if (checkingSession) {
    return <div className="max-w-md mx-auto bg-white rounded-2xl shadow-sm p-6">Checking password reset link…</div>;
  }

  if (!session) {
    return (
      <div className="max-w-md mx-auto bg-white rounded-2xl shadow-sm p-6 sm:p-8">
        <h1 className="text-2xl font-semibold text-primary mb-2">Reset link unavailable</h1>
        <p className="text-sm text-muted mb-6">This password-reset link may have expired. Request a new one from the Cashflow sign-in page.</p>
        <button type="button" onClick={() => navigate("/cashflow/login", { replace: true })} className="w-full btn-ui btn-ui-primary">Back to Sign In</button>
      </div>
    );
  }

  return (
    <div className="max-w-md mx-auto bg-white rounded-2xl shadow-sm p-6 sm:p-8">
      <h1 className="text-2xl font-semibold text-primary mb-2">Set your Cashflow password</h1>
      <p className="text-sm text-muted mb-6">Choose a password to use with Existing user? Sign in.</p>
      <form className="space-y-4" onSubmit={handleSubmit}>
        <input type="password" required minLength={8} value={password} onChange={(event) => setPassword(event.target.value)} placeholder="New password" autoComplete="new-password" className="w-full px-4 py-3 rounded-xl border border-slate-200" />
        <input type="password" required minLength={8} value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} placeholder="Confirm password" autoComplete="new-password" className="w-full px-4 py-3 rounded-xl border border-slate-200" />
        <button type="submit" disabled={saving} className="w-full btn-ui btn-ui-primary">{saving ? "Saving…" : "Set Password"}</button>
      </form>
      {error ? <p className="mt-4 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700">{error}</p> : null}
      {info ? <p className="mt-4 rounded-xl bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{info}</p> : null}
    </div>
  );
}

export default CashflowResetPassword;