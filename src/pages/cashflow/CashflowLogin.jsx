import { useEffect, useMemo, useState } from "react";
import { Navigate, useSearchParams } from "react-router-dom";
import { Globe, Sparkles, X } from "lucide-react";
import { getCashflowPostAuthRoute, useCashflowAuth } from "../../context/CashflowAuthContext";
import { sendPasswordResetEmail } from "../../services/supabase";

function CashflowLogin() {
  const { session, profile, profileError, signIn, signInWithGoogle, signInWithInviteLink, loading, signOut } = useCashflowAuth();
  const [searchParams] = useSearchParams();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [authModalOpen, setAuthModalOpen] = useState(false);
  const [authMode, setAuthMode] = useState("get-started");
  const [submitting, setSubmitting] = useState(false);

  const inviteToken = useMemo(() => String(searchParams.get("token") || "").trim(), [searchParams]);
  const inviteEmail = useMemo(() => String(searchParams.get("email") || "").trim(), [searchParams]);
  const inviteRole = useMemo(() => String(searchParams.get("role") || "").trim(), [searchParams]);
  const invitePath = useMemo(() => {
    if (!inviteToken) {
      return null;
    }
    const params = new URLSearchParams({ token: inviteToken });
    if (inviteEmail) params.set("email", inviteEmail);
    if (inviteRole) params.set("role", inviteRole);
    return `/cashflow/expense/accept-invite?${params.toString()}`;
  }, [inviteToken, inviteEmail, inviteRole]);
  const authRedirect = useMemo(() => {
    if (!invitePath) return "/cashflow/login";
    return `/cashflow/login?${new URLSearchParams({ token: inviteToken, ...(inviteEmail ? { email: inviteEmail } : {}), ...(inviteRole ? { role: inviteRole } : {}) }).toString()}`;
  }, [invitePath, inviteToken, inviteEmail, inviteRole]);

  useEffect(() => {
    if (inviteEmail) {
      setEmail(inviteEmail);
      setAuthModalOpen(true);
    }
  }, [inviteEmail]);

  useEffect(() => {
    if (inviteToken) {
      setAuthModalOpen(true);
    }
  }, [inviteToken]);

  // If there is an existing session and the auth modal isn't open, redirect
  // to the appropriate destination (onboarding or invite accept).
  // Once the user explicitly opens the auth modal, we stay on the login page.
  const postAuthRoute = getCashflowPostAuthRoute({ session, profile, profileError, invitePath });
  if (!loading && postAuthRoute && session && !authModalOpen) {
    return <Navigate to={postAuthRoute} replace />;
  }

  const handleGoogleSignIn = async () => {
    setError("");
    setInfo("");
    const { error: googleError } = await signInWithGoogle(authRedirect);
    if (googleError) {
      setError(googleError);
    }
  };

  const handleEmailLink = async () => {
    const normalizedEmail = email.trim().toLowerCase();
    if (!normalizedEmail) {
      setError("Email is required.");
      return;
    }

    setSubmitting(true);
    setError("");
    setInfo("");
    try {
      const { error: otpError } = await signInWithInviteLink(normalizedEmail, authRedirect);
      if (otpError) {
        setError(otpError);
        return;
      }
      setInfo(`A sign-in link has been sent to ${normalizedEmail}. Open that email on the same device and continue.`);
    } finally {
      setSubmitting(false);
    }
  };

  const handlePasswordSignIn = async () => {
    const normalizedEmail = email.trim().toLowerCase();
    if (!normalizedEmail || !password) {
      setError("Email and password are required.");
      return;
    }

    setSubmitting(true);
    setError("");
    setInfo("");
    try {
      const { error: signInError } = await signIn(normalizedEmail, password);
      if (signInError) {
        setError(signInError);
        return;
      }
      setPassword("");
      setAuthModalOpen(false);
    } finally {
      setSubmitting(false);
    }
  };

  const handlePasswordReset = async () => {
    const normalizedEmail = email.trim().toLowerCase();
    if (!normalizedEmail) {
      setError("Enter your email address first.");
      return;
    }
    setSubmitting(true);
    setError("");
    setInfo("");
    try {
      const { error: resetError } = await sendPasswordResetEmail(normalizedEmail);
      if (resetError) {
        setError(resetError);
        return;
      }
      setInfo(`A password setup link has been sent to ${normalizedEmail}. Open it on this device to choose your password.`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="px-4 pt-4 pb-4 sm:px-6 sm:pt-6 sm:pb-6 lg:px-8">
      <div className="mx-auto w-full max-w-7xl">
        <div className="grid min-h-[calc(100vh-12rem)] items-start gap-6 lg:grid-cols-2">
          <div className="relative mt-4 overflow-hidden rounded-2xl border border-sky-200 bg-gradient-to-br from-sky-100 via-cyan-50 to-blue-100 px-5 py-6 text-slate-900 shadow-[0_20px_45px_-28px_rgba(14,116,144,0.45)] sm:px-6 sm:py-7 lg:px-8">
            <div className="pointer-events-none absolute -right-8 -top-10 h-44 w-44 rounded-full bg-sky-300/30 blur-2xl" />
            <div className="pointer-events-none absolute -bottom-16 -left-10 h-56 w-56 rounded-full bg-cyan-300/25 blur-3xl" />
            <div className="relative flex flex-col justify-center rounded-2xl border border-white/70 bg-white/55 p-4 backdrop-blur-md sm:p-5">
            <div className="inline-flex w-fit items-center gap-2 rounded-full border border-cyan-300 bg-cyan-50/90 px-3 py-1 text-xs font-semibold text-cyan-900">
              <Sparkles className="h-3.5 w-3.5" />
              One source of truth for all cash-flow.
            </div>
            <h1 className="mt-5 text-4xl font-extrabold leading-[1.04] tracking-[-0.035em] text-slate-900 sm:text-5xl">
              CashFlow built
              <span className="block bg-gradient-to-r from-sky-700 via-blue-700 to-cyan-600 bg-clip-text text-transparent">around intelligence</span>
            </h1>
            <p className="mt-4 max-w-xl text-[1.03rem] leading-7 text-slate-700">
              Unified payables, receivables, expenses, and GST visibility in one real-time finance cockpit.
            </p>
            <p className="mt-1.5 max-w-xl text-[0.98rem] leading-7 text-slate-600">
              Cut manual effort, reduce cash leaks, and make faster decisions with AI-assisted cashflow signals.
            </p>

            <button
              type="button"
              onClick={() => {
                setError("");
                setInfo("");
                setAuthMode("get-started");
                setAuthModalOpen(true);
              }}
              className="mt-8 inline-flex w-fit items-center justify-center gap-2 rounded-2xl bg-slate-900 px-7 py-3.5 text-lg font-semibold text-white shadow-[0_14px_30px_-14px_rgba(15,23,42,0.5)] hover:bg-slate-800"
            >
              <Sparkles className="h-5 w-5 text-amber-300" />
              Get Started for Free
            </button>
            </div>
          </div>

          <div className="mt-4 flex min-h-[420px] flex-col rounded-2xl border border-slate-200 bg-white p-4 shadow-[0_18px_45px_-28px_rgba(15,23,42,0.35)] sm:p-5">
            <div className="relative overflow-hidden rounded-xl border-4 border-black bg-white shadow-[0_14px_32px_-16px_rgba(15,23,42,0.55)]">
              <img
                src="/dashboard.png"
                alt="Cashflow dashboard preview"
                className="h-[56vh] min-h-[360px] w-full object-cover object-top"
                loading="eager"
              />
            </div>

            <div className="mt-3 rounded-xl border border-sky-100 bg-sky-50 px-4 py-3 text-sm text-slate-700">
              First person to sign in and create a company becomes the workspace owner. Owners can invite admins and employees to the same workspace using invite links.
            </div>
          </div>
        </div>
      </div>

      {authModalOpen ? (
        <div className="fixed inset-0 z-[90] flex items-center justify-center bg-slate-950/55 px-4 py-6 backdrop-blur-sm">
          <div className="w-full max-w-3xl rounded-3xl bg-white px-6 py-7 shadow-[0_24px_70px_-30px_rgba(15,23,42,0.55)] sm:px-8 sm:py-8">
            <div className="flex justify-end">
              <button
                type="button"
                onClick={() => {
                  if (inviteToken) return;
                  setAuthModalOpen(false);
                  setError("");
                  setInfo("");
                }}
                disabled={Boolean(inviteToken)}
                className="rounded-full border border-slate-200 p-2 text-slate-500 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-40"
                aria-label="Close"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <h2 className="text-center text-3xl font-semibold leading-tight text-slate-900 sm:text-4xl">
              {inviteToken
                ? "Join your workspace in under a minute"
                : authMode === "sign-in"
                  ? "Sign in to your workspace"
                  : "Get started in less than 1 minute!"}
            </h2>

            {inviteToken ? (
              <p className="mx-auto mt-3 max-w-2xl text-center text-sm text-slate-600">
                Continue with invited account: <span className="font-semibold text-slate-900">{inviteEmail}</span>{inviteRole ? ` (${inviteRole})` : ""}
              </p>
            ) : null}

            <div className="mt-7 rounded-2xl bg-slate-50 p-3 sm:p-4">
              <div className="space-y-3">
                <input
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="name@company.com"
                  className="h-12 w-full rounded-xl border border-slate-200 bg-white px-4 text-base text-slate-700 focus:border-blue-300 focus:outline-none"
                  readOnly={Boolean(inviteToken && inviteEmail)}
                  autoComplete="email"
                />
                {authMode === "sign-in" && !inviteToken ? (
                  <input
                    type="password"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    placeholder="Password"
                    className="h-12 w-full rounded-xl border border-slate-200 bg-white px-4 text-base text-slate-700 focus:border-blue-300 focus:outline-none"
                    autoComplete="current-password"
                  />
                ) : null}
                <button
                  type="button"
                  onClick={authMode === "sign-in" && !inviteToken ? handlePasswordSignIn : handleEmailLink}
                  disabled={submitting}
                  className="h-12 w-full rounded-xl bg-slate-900 px-6 text-base font-semibold text-white hover:bg-slate-800 disabled:opacity-60"
                >
                  {authMode === "sign-in" && !inviteToken ? "Sign In" : "Get Started"}
                </button>
                {authMode === "sign-in" && !inviteToken ? (
                  <button
                    type="button"
                    onClick={handlePasswordReset}
                    disabled={submitting}
                    className="text-sm font-semibold text-blue-700 hover:text-blue-900 disabled:opacity-60"
                  >
                    Forgot or set password?
                  </button>
                ) : null}
              </div>
            </div>

            {!inviteToken ? (
              <button
                type="button"
                onClick={() => {
                  setError("");
                  setInfo("");
                  setAuthMode((current) => current === "sign-in" ? "get-started" : "sign-in");
                }}
                className="mt-4 w-full text-center text-sm font-semibold text-blue-700 hover:text-blue-900"
              >
                {authMode === "sign-in" ? "New user? Get started" : "Existing user? Sign in"}
              </button>
            ) : null}

            <div className="my-6 flex items-center gap-4 text-sm font-semibold text-slate-500">
              <div className="h-px flex-1 bg-slate-200" />
              <span>OR</span>
              <div className="h-px flex-1 bg-slate-200" />
            </div>

            <button
              type="button"
              onClick={handleGoogleSignIn}
              className="inline-flex h-12 w-full items-center justify-center gap-3 rounded-xl border border-slate-200 bg-white text-base font-medium text-slate-900 shadow-sm hover:bg-slate-50"
            >
              <Globe className="h-5 w-5" />
              Sign up with Google
            </button>

            {error ? (
              <div className="mt-4 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                {error}
              </div>
            ) : null}
            {profileError?.message ? (
              <div className="mt-4 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                We couldn't load your Cashflow profile. Please retry or contact support.
              </div>
            ) : null}
            {info ? (
              <div className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
                {info}
              </div>
            ) : null}

            <p className="mt-6 text-center text-sm text-slate-500">No credit card needed.</p>
          </div>
        </div>
      ) : null}
    </section>
  );
}

export default CashflowLogin;