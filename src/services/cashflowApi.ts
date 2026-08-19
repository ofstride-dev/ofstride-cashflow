import { supabase } from "./supabase";

const CASHFLOW_LOCAL_ID_KEY = "ofstride_cashflow_user_id";
const CASHFLOW_PROFILE_CACHE_KEY = "ofstride_cashflow_profile";

function getOrCreateCashflowLocalId(): string {
  const existing = localStorage.getItem(CASHFLOW_LOCAL_ID_KEY);
  if (existing) {
    return existing;
  }

  const nextId = crypto.randomUUID();
  localStorage.setItem(CASHFLOW_LOCAL_ID_KEY, nextId);
  return nextId;
}

function getCachedCashflowProfile(): Record<string, any> | null {
  if (typeof window === "undefined") {
    return null;
  }

  try {
    const raw = window.localStorage.getItem(CASHFLOW_PROFILE_CACHE_KEY);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    return null;
  }
}

export const CASHFLOW_API_BASE =
  (import.meta.env.VITE_CASHFLOW_API_BASE_URL as string | undefined) || "/api";

async function cashflowIdentityHeaders(): Promise<HeadersInit> {
  let session = null;
  let user = null;

  try {
    const { data } = await supabase.auth.getSession();
    session = data.session || null;
    user = session?.user || null;
  } catch {
    session = null;
    user = null;
  }

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
  };

  if (session?.access_token) {
    headers["Authorization"] = `Bearer ${session.access_token}`;
  }

  const cachedProfile = getCachedCashflowProfile();
  const cachedRole = String(cachedProfile?.role || "").trim().toLowerCase();
  const cachedCompanyId = String(cachedProfile?.company_id || "").trim();
  const cachedUserId = String(cachedProfile?.id || cachedProfile?.user_id || "").trim();

  // Prefer the authenticated Supabase user id, but preserve cached profile ids
  // for local/dev flows where the profile record is created independently.
  const identityUserId = user?.id || cachedUserId || getOrCreateCashflowLocalId();

  headers["x-user-id"] = identityUserId;
  headers["x-cashflow-user-id"] = identityUserId;

  // Once Supabase has authenticated the user, the API must resolve role and
  // company from the bearer token/profile. Do not send cached tenant headers
  // for an authenticated session: those values can belong to a prior company
  // or role and must never influence Cashflow authorization.
  if (!user?.id) {
    headers["x-app-role"] = cachedRole || "employee";
    if (cachedCompanyId) {
      headers["x-company-id"] = cachedCompanyId;
    }
  }

  return headers;
}

export async function cashflowFetch(
  path: string,
  init: RequestInit = {}
): Promise<Response> {
  const normalizedBase = CASHFLOW_API_BASE.replace(/\/+$/, "");
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;

  const baseHeaders = await cashflowIdentityHeaders();
  const mergedHeaders: HeadersInit = {
    ...(baseHeaders as Record<string, string>),
    ...((init.headers || {}) as Record<string, string>),
  };

  return fetch(`${normalizedBase}${normalizedPath}`, {
    ...init,
    cache: "no-store",
    headers: mergedHeaders,
  });
}

export async function parseCashflowResponse<T = any>(res: Response): Promise<{
  ok: boolean;
  status: number;
  data: T | null;
  error: string | null;
}> {
  const contentType = res.headers.get("content-type") || "";
  const raw = await res.text();

  let payload: any = null;
  if (raw && contentType.toLowerCase().includes("application/json")) {
    try {
      payload = JSON.parse(raw);
    } catch {
      payload = null;
    }
  }

  if (res.ok && payload?.ok === true) {
    return {
      ok: true,
      status: res.status,
      data: (payload.data ?? null) as T | null,
      error: null,
    };
  }

  const messageFromPayload =
    payload?.error?.message
    || payload?.error
    || payload?.message
    || null;

  const fallback = raw
    ? `HTTP ${res.status}: ${raw.slice(0, 240)}`
    : `HTTP ${res.status}: Empty response`;

  return {
    ok: false,
    status: res.status,
    data: null,
    error: String(messageFromPayload || fallback),
  };
}
