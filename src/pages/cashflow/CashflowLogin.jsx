import { useEffect, useMemo, useState } from "react";
import { Navigate, useSearchParams } from "react-router-dom";
import { ArrowUpRight, LineChart, Sparkles, X } from "lucide-react";
import { getCashflowPostAuthRoute, useCashflowAuth } from "../../context/CashflowAuthContext";
import { sendPasswordResetEmail } from "../../services/supabase";
import ofstrideLogo from "../../assets/Screenshot 2026-08-20 194422.png";

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

function CashflowLogin() {
  const { session, profile, profileError, signIn, signInWithGoogle, signInWithInviteLink, loading } = useCashflowAuth();
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
      <section className="login-stage relative flex h-screen min-h-0 w-full overflow-hidden p-0">
        <div className="login-shell relative z-10 flex h-full min-h-0 w-full max-w-none overflow-hidden lg:grid lg:grid-cols-[30%_70%]">
          <div className="login-intro relative flex w-full flex-col justify-between overflow-hidden px-7 py-8 text-slate-900 sm:px-10 lg:px-8 lg:py-10">
            <div className="login-orbit login-orbit-one" />
            <div className="login-orbit login-orbit-two" />
            <div className="relative z-10">
            <div className="login-service-label">
              <span className="login-service-icon"><img src={ofstrideLogo} alt="Ofstride Services logo" /></span>
              <span className="login-service-copy"><strong>CashPulse</strong><small>by OFSTRIDE SERVICES</small></span>
            </div>
            <div className="login-inline-card">
              <h1>{authMode === "sign-in" ? "Sign in to your workspace" : "Get started in under a minute"}</h1>
              <p className="login-inline-subtitle">Unified payables, receivables, expenses & GST — one finance cockpit.</p>
              <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="name@company.com" className="login-inline-input" readOnly={Boolean(inviteToken && inviteEmail)} autoComplete="email" />
              {authMode === "sign-in" && !inviteToken ? <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="Password" className="login-inline-input" autoComplete="current-password" /> : null}
              <button type="button" onClick={authMode === "sign-in" && !inviteToken ? handlePasswordSignIn : handleEmailLink} disabled={submitting} className="login-inline-submit">{authMode === "sign-in" && !inviteToken ? "Sign In" : "Get Started"}</button>
              {authMode === "sign-in" && !inviteToken ? <button type="button" onClick={handlePasswordReset} disabled={submitting} className="mt-2 w-full text-center text-sm font-semibold text-blue-700 hover:text-blue-900 disabled:opacity-60">Set up or reset password</button> : null}
              {!inviteToken ? <button type="button" onClick={() => { setError(""); setInfo(""); setAuthMode((current) => current === "sign-in" ? "get-started" : "sign-in"); }} className="login-inline-switch">{authMode === "sign-in" ? "New user? Get started" : "Existing user? Sign in"}</button> : null}
              <div className="login-inline-divider"><span />OR<span /></div>
              <button type="button" onClick={handleGoogleSignIn} className="login-inline-google"><GoogleIcon className="h-4 w-4" /> Sign up with Google</button>
              {error ? <div className="login-inline-error">{error}</div> : null}
              {info ? <div className="login-inline-success">{info}</div> : null}
              <p className="login-inline-foot">OFSTRIDE SERVICES · No credit card needed.</p>
            </div>
            </div>
          </div>

          <div className="login-visual-panel relative flex min-h-0 w-full items-center justify-center overflow-hidden px-6 py-8 sm:px-10 lg:px-14 lg:py-8">
            <div className="login-orbit login-orbit-one" />
            <div className="login-orbit login-orbit-two" />
            <div className="login-visual-copy relative z-10">
              <span className="login-board-kicker">Your cashflow, in motion</span>
              <h2>See the signal<br /><span>behind every rupee.</span></h2>
              <p>Track inflow, outflow, and runway with a living view of your business finances.</p>
              <div className="login-finance-board" aria-label="Animated mock CashPulse dashboard">
              <div className="login-board-header"><div><span className="login-board-kicker">CashPulse pulse</span><strong>₹ 18.42L</strong><small>Net position <b>+12.8%</b> this month</small></div></div>
              <div className="login-board-chart">
                <div className="login-chart-grid"><span>20L</span><span>15L</span><span>10L</span><span>5L</span><span>0</span></div>
                <svg viewBox="0 0 540 170" role="img" aria-label="Rising inflow and outflow trend graph" preserveAspectRatio="none">
                  <defs><linearGradient id="loginArea" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor="#38bdf8" stopOpacity=".35" /><stop offset="1" stopColor="#38bdf8" stopOpacity="0" /></linearGradient></defs>
                  <path className="login-chart-area" d="M0 145 C30 135 45 130 70 136 S105 105 130 115 S165 100 190 104 S225 80 250 93 S280 55 310 70 S350 40 380 53 S420 28 450 38 S500 12 540 20 L540 170 L0 170Z" />
                  <path className="login-chart-line" d="M0 145 C30 135 45 130 70 136 S105 105 130 115 S165 100 190 104 S225 80 250 93 S280 55 310 70 S350 40 380 53 S420 28 450 38 S500 12 540 20" />
                  <circle className="login-chart-dot" cx="450" cy="38" r="5" /><circle className="login-chart-dot login-chart-dot-pulse" cx="450" cy="38" r="10" />
                </svg>
                <div className="login-chart-months"><span>Apr</span><span>May</span><span>Jun</span><span>Jul</span><span>Aug</span></div>
                <div className="login-chart-scan" />
              </div>
              <div className="login-board-bottom">
                <div className="login-mini-stat"><span>Inflow</span><strong>₹ 26.8L</strong><b className="positive">↗ 18.4%</b></div>
                <div className="login-mini-bars" aria-label="Animated inflow and outflow bars">{[42, 68, 51, 82, 63, 94, 76].map((height, index) => <i key={index} style={{ '--bar-height': `${height}%` }} />)}</div>
                <div className="login-mini-stat"><span>Outflow</span><strong>₹ 8.3L</strong><b>↘ 4.2%</b></div>
              </div>
              <div className="login-board-table"><span>RECENT MOVEMENTS</span><div><b>Vendor payouts</b><strong>− ₹ 2.4L</strong></div><div><b>Client receipts</b><strong className="positive">+ ₹ 6.8L</strong></div></div>
            </div>
          </div>
        </div>
        </div>

      {authModalOpen && inviteToken ? (
        <div className="login-auth-overlay fixed inset-0 z-[90] flex items-center justify-center px-4 py-6 backdrop-blur-sm">
          <div className="login-auth-card w-full max-w-md rounded-[1.75rem] px-6 py-7 sm:px-8 sm:py-8">
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

            <div className="login-auth-fields mt-7 rounded-2xl p-3 sm:p-4">
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
              <GoogleIcon className="h-5 w-5" />
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

            <p className="mt-6 text-center text-sm text-slate-500">OFSTRIDE SERVICES · Secure workspace access · No credit card needed.</p>
          </div>
        </div>
      ) : null}
    </section>
  );
}

export default CashflowLogin;