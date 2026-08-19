import { cashflowFetch, parseCashflowResponse } from "./cashflowApi";
import { supabase } from "./supabase";

const DEFAULT_DEMO_EMAIL = "demo-owner@ofstride-demo.com";
const DEFAULT_DEMO_PASSWORD = "OfstrideDemo123!";
const DEFAULT_DEMO_COMPANY = "OfStride Demo Workspace";

function firstRow<T>(value: T | T[] | null | undefined): T | null {
  if (Array.isArray(value)) {
    return value[0] || null;
  }
  return value ?? null;
}

export function getDemoCredentials() {
  return {
    email: String(import.meta.env.VITE_DEMO_LOGIN_EMAIL || DEFAULT_DEMO_EMAIL).trim(),
    password: String(import.meta.env.VITE_DEMO_LOGIN_PASSWORD || DEFAULT_DEMO_PASSWORD),
    companyName: String(import.meta.env.VITE_DEMO_COMPANY_NAME || DEFAULT_DEMO_COMPANY).trim(),
  };
}

export async function getMyCashflowProfile() {
  const { data, error } = await supabase.rpc("get_my_profile");
  if (error) {
    throw error;
  }
  return firstRow<any>(data);
}

export async function bootstrapCompanyOwner(companyName: string, fullName: string, isDemo = false, companyEmail?: string | null) {
  const { data, error } = await supabase.rpc("bootstrap_company_owner", {
    p_company_name: companyName,
    p_full_name: fullName || null,
    p_is_demo: isDemo,
    p_company_email: companyEmail || null,
  });
  if (error) {
    throw error;
  }
  return firstRow<any>(data) || data;
}

export async function listCompanyInvites() {
  const { data, error } = await supabase.rpc("list_company_invites");
  if (error) {
    throw error;
  }
  return Array.isArray(data) ? data : [];
}

export async function acceptCompanyInvite(inviteToken: string, fullName: string) {
  const { data, error } = await supabase.rpc("accept_company_invite", {
    p_invite_token: inviteToken,
    p_full_name: fullName || null,
  });
  if (error) {
    throw error;
  }
  return firstRow<any>(data) || data;
}

export async function revokeCompanyInvite(inviteToken: string) {
  const { data, error } = await supabase.rpc("revoke_company_invite", {
    p_invite_token: inviteToken,
  });
  if (error) {
    throw error;
  }
  return firstRow<any>(data) || data;
}

export async function createCompanyInvite(email: string, role: "admin" | "employee" = "employee") {
  const normalizedEmail = email.trim().toLowerCase();
  const { data, error } = await supabase.rpc("create_company_invite", {
    p_email: normalizedEmail,
    p_role: role,
  });
  if (error) {
    throw error;
  }

  const invite = firstRow<any>(data) || data;
  const acceptUrl = `${window.location.origin}/cashflow/expense/accept-invite?token=${encodeURIComponent(
    String(invite?.invite_token || "")
  )}&email=${encodeURIComponent(normalizedEmail)}&role=${encodeURIComponent(String(invite?.role || role))}`;

  const notifyRes = await cashflowFetch("/cashflow/invites/notify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      email: normalizedEmail,
      invite_token: invite?.invite_token,
      company_name: invite?.company_name,
      role: invite?.role || role,
      accept_url: acceptUrl,
    }),
  });
  const parsed = await parseCashflowResponse<{ support_sent?: boolean }>(notifyRes);
  if (!parsed.ok) {
    try {
      await revokeCompanyInvite(String(invite?.invite_token || ""));
    } catch {
      // Preserve the delivery error; the server-side revoke remains best effort.
    }
    throw new Error(parsed.error || "Invite email could not be sent.");
  }

  return {
    ...(invite || {}),
    accept_url: acceptUrl,
  };
}
