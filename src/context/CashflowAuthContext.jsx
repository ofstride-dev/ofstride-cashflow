import { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";
import {
  acceptCompanyInvite,
  bootstrapCompanyOwner,
  createCompanyInvite,
  getDemoCredentials,
  getMyCashflowProfile,
  listCompanyInvites,
} from "../services/cashflowTenantApi";
import {
  signInWithEmail,
  signInWithGoogle,
  signInWithOtp,
  signOut as supabaseSignOut,
  supabase,
} from "../services/supabase";
import { canApproveCashflow, canUseCashflow } from "../auth/cashflowPermissions";

const CashflowAuthContext = createContext(undefined);
const CASHFLOW_PROFILE_CACHE_KEY = "ofstride_cashflow_profile";

export function getCashflowPostAuthRoute({ session, profile, profileError, invitePath = null }) {
  if (!session) {
    return "/cashflow/login";
  }
  if (profileError || !profile) {
    return null;
  }
  if (invitePath) {
    return invitePath;
  }
  if (!profile.company_id) {
    return "/cashflow/expense/onboarding";
  }
  if (profile.is_setup_complete === false) {
    return "/cashflow/expense/company-profile";
  }
  return "/cashflow/dashboard";
}

function cacheProfile(profile) {
  if (typeof window === "undefined") {
    return;
  }

  if (!profile) {
    window.localStorage.removeItem(CASHFLOW_PROFILE_CACHE_KEY);
    return;
  }

  window.localStorage.setItem(CASHFLOW_PROFILE_CACHE_KEY, JSON.stringify(profile));
}

async function fetchProfile(userId) {
  if (!userId) {
    return null;
  }
  
  let data = null;
  let error = null;

  try {
    data = await getMyCashflowProfile();
  } catch (rpcError) {
    error = rpcError;
  }

  if (error) {
    return { error };
  }

  if (!data) {
    // Get the user's email from the session if available
    let userEmail = null;
    try {
      const { data: sessionData } = await supabase.auth.getSession();
      userEmail = sessionData?.session?.user?.email || sessionData?.session?.user?.user_metadata?.email || null;
    } catch {
      userEmail = null;
    }

    const defaultProfile = {
      id: userId,
      full_name: "Team Member",
      role: "employee",
      company_id: null,
      company_name: null,
      company_slug: null,
      email: userEmail,
    };

    const { data: createdProfile, error: createError } = await supabase
      .from("profiles")
      .upsert({ ...defaultProfile, email: userEmail })
      .select("id, full_name, role, company_id, email, created_at, updated_at")
      .maybeSingle();

    if (createError) {
      return defaultProfile;
    }

    return createdProfile;
  }

  return data;
}

export function CashflowAuthProvider({ children }) {
  const [session, setSession] = useState(null);
  const [profile, setProfile] = useState(null);
  const [invites, setInvites] = useState([]);
  const [profileError, setProfileError] = useState(null);
  const [loading, setLoading] = useState(true);
  const activeUserIdRef = useRef(null);

  const refreshProfile = async (userId) => {
    if (!userId) {
      setProfile(null);
      setInvites([]);
      return null;
    }

    const result = await fetchProfile(userId);
    if (result?.error) {
      setProfile(null);
      setProfileError(result.error);
      setInvites([]);
      cacheProfile(null);
      return null;
    }

    setProfile(result);
    setProfileError(null);
    cacheProfile(result);

    const role = String(result?.role || "").toLowerCase();
    if (role === "owner" || role === "admin" || role === "finance") {
      try {
        const nextInvites = await listCompanyInvites();
        setInvites(nextInvites);
      } catch {
        setInvites([]);
      }
    } else {
      setInvites([]);
    }

    return result;
  };

  useEffect(() => {
    let isMounted = true;

    async function init() {
      const { data } = await supabase.auth.getSession();
      if (!isMounted) return;
      const nextUserId = data.session?.user?.id || null;
      activeUserIdRef.current = nextUserId;
      // Never let a previous user's tenant profile survive a new session.
      cacheProfile(null);
      setSession(data.session || null);
      if (nextUserId) {
        const result = await fetchProfile(nextUserId);
        if (isMounted) {
          if (activeUserIdRef.current !== nextUserId) return;
          if (result?.error) {
            setProfile(null);
            setProfileError(result.error);
            cacheProfile(null);
          } else {
            setProfile(result);
            setProfileError(null);
            cacheProfile(result);
            const role = String(result?.role || "").toLowerCase();
            if (role === "owner" || role === "admin" || role === "finance") {
              try {
                setInvites(await listCompanyInvites());
              } catch {
                setInvites([]);
              }
            }
          }
        }
      }
      if (isMounted) setLoading(false);
    }

    init();

    const { data: listener } = supabase.auth.onAuthStateChange(async (_event, newSession) => {
      if (!isMounted) return;
      const nextUserId = newSession?.user?.id || null;
      // Clear the previous company's cached identity before resolving the new
      // user's profile. This prevents a sign-in switch from reusing stale
      // role/company headers or rendering the old workspace temporarily.
      if (activeUserIdRef.current !== nextUserId) {
        activeUserIdRef.current = nextUserId;
        cacheProfile(null);
        setProfile(null);
        setProfileError(null);
        setInvites([]);
      }
      setSession(newSession || null);
      if (nextUserId) {
        const result = await fetchProfile(nextUserId);
        if (isMounted) {
          if (activeUserIdRef.current !== nextUserId) return;
          if (result?.error) {
            setProfile(null);
            setProfileError(result.error);
            cacheProfile(null);
          } else {
            setProfile(result);
            setProfileError(null);
            cacheProfile(result);
            const role = String(result?.role || "").toLowerCase();
            if (role === "owner" || role === "admin" || role === "finance") {
              try {
                setInvites(await listCompanyInvites());
              } catch {
                setInvites([]);
              }
            } else {
              setInvites([]);
            }
          }
        }
      } else {
        setProfile(null);
        setProfileError(null);
        setInvites([]);
        cacheProfile(null);
      }
      setLoading(false);
    });

    return () => {
      isMounted = false;
      listener.subscription.unsubscribe();
    };
  }, []);

  const signIn = async (email, password) => {
    const { user, error } = await signInWithEmail(email, password);
    return { user, error };
  };

  const signInWithGoogleProvider = async (redirectPath = "/cashflow/login") => signInWithGoogle(redirectPath);
  const signInWithInviteLink = async (email, redirectPath = "/cashflow/login") => signInWithOtp(email, redirectPath);

  const signUp = async (email, password, fullName, role = "employee") => {
    const { data, error } = await supabase.auth.signUp({
      email,
      password,
      options: {
        data: { full_name: fullName, role },
      },
    });
    if (error) {
      return { user: null, error: error.message };
    }
    return { user: data.user, error: null };
  };

  const signOut = async () => {
    await supabaseSignOut();
    setSession(null);
    setProfile(null);
    setInvites([]);
    setProfileError(null);
    cacheProfile(null);
  };

  const onboardOwner = async (companyName, fullName, isDemo = false, companyEmail = null) => {
    await bootstrapCompanyOwner(companyName, fullName, isDemo, companyEmail);
    return refreshProfile(session?.user?.id || null);
  };

  const inviteMember = async (email, role = "employee") => {
    const invite = await createCompanyInvite(email, role);
    try {
      setInvites(await listCompanyInvites());
    } catch {
      setInvites((prev) => [invite, ...prev]);
    }
    return invite;
  };

  const acceptInvite = async (inviteToken, fullName) => {
    const result = await acceptCompanyInvite(inviteToken, fullName);
    const nextProfile = await refreshProfile(session?.user?.id || null);
    return { ...result, profile: nextProfile };
  };

  const demoLogin = async () => {
    const { email, password, companyName } = getDemoCredentials();
    let result = await signInWithEmail(email, password);

    if (result.error) {
      const signUpResult = await signUp(email, password, "Demo Owner", "employee");
      if (signUpResult.error && !String(signUpResult.error).toLowerCase().includes("already registered")) {
        return signUpResult;
      }
      result = await signInWithEmail(email, password);
    }

    if (result.error) {
      return result;
    }

    const latestProfile = await refreshProfile(result.user?.id || null);
    if (!latestProfile?.company_id) {
      await onboardOwner(companyName, latestProfile?.full_name || "Demo Owner", true, email);
    }

    return { user: result.user, error: null };
  };

  const value = useMemo(() => ({
    session,
    user: session?.user || null,
    profile,
    invites,
    profileError,
    loading,
    signIn,
    signInWithGoogle: signInWithGoogleProvider,
    signInWithInviteLink,
    signUp,
    signOut,
    onboardOwner,
    inviteMember,
    acceptInvite,
    demoLogin,
    refreshProfile: () => refreshProfile(session?.user?.id || null),
    isOwner: String(profile?.role || "").toLowerCase() === "owner",
    isAdmin: canApproveCashflow(profile),
    hasCompany: canUseCashflow(profile),
  }), [session, profile, invites, profileError, loading]);

  return <CashflowAuthContext.Provider value={value}>{children}</CashflowAuthContext.Provider>;
}

export function useCashflowAuth() {
  const ctx = useContext(CashflowAuthContext);
  if (!ctx) {
    throw new Error("useCashflowAuth must be used inside CashflowAuthProvider");
  }
  return ctx;
}