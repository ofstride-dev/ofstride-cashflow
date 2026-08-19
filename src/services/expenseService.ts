import { supabase } from "./supabase";

export const EXPENSE_CATEGORIES = [
  "Travel",
  "Client Meals/Entertainment",
  "Equipment/Hardware",
  "Software/Subscriptions",
  "Office/Misc",
];

export const EXPENSE_STATUSES = [
  "submitted",
  "approved",
  "rejected",
  "ready_for_payment",
  "paid",
];

export const STATUS_LABELS = {
  submitted: "Submitted",
  approved: "Approved",
  rejected: "Rejected",
  ready_for_payment: "Ready for Payment",
  paid: "Paid",
};

export const STATUS_BADGE_CLASSES = {
  submitted: "bg-slate-100 text-slate-700 border-slate-200",
  approved: "bg-emerald-50 text-emerald-700 border-emerald-200",
  rejected: "bg-red-50 text-red-700 border-red-200",
  ready_for_payment: "bg-blue-50 text-blue-700 border-blue-200",
  paid: "bg-accent/10 text-accent border-accent/30",
};

export const VALID_STATUS_TRANSITIONS = {
  submitted: ["approved", "rejected"],
  approved: ["ready_for_payment", "rejected"],
  ready_for_payment: ["paid"],
  rejected: [],
  paid: [],
};

export async function createExpense(payload: Record<string, unknown>) {
  const { data, error } = await supabase
    .from("expenses")
    .insert(payload)
    .select()
    .single();
  if (error) {
    throw error;
  }
  return data;
}

export async function listMyExpenses(userId: string) {
  const { data, error } = await supabase
    .from("expenses")
    .select("*")
    .eq("user_id", userId)
    .order("created_at", { ascending: false });
  if (error) {
    throw error;
  }
  return data || [];
}

export async function listAllExpenses({ status }: { status?: string } = {}) {
  let query = supabase.from("expenses").select("*").order("created_at", { ascending: false });
  if (status) {
    query = query.eq("status", status);
  }
  const { data, error } = await query;
  if (error) {
    throw error;
  }
  const expenses = data || [];

  const userIds = Array.from(new Set(expenses.map((expense) => expense.user_id).filter(Boolean)));
  if (userIds.length === 0) {
    return expenses;
  }

  // Use the SECURITY DEFINER RPC instead of querying profiles directly.
  // The profile_self_select RLS policy only allows id = auth.uid(), so a
  // direct query would return empty for other users. The RPC bypasses RLS
  // and is admin-only (enforced server-side).
  const { data: profiles, error: profilesError } = await supabase.rpc(
    "get_claimant_profiles",
    { p_user_ids: userIds }
  );
  if (profilesError) {
    throw profilesError;
  }

  const nameById = new Map(
    (profiles || []).map((profile: { id: string; full_name: string }) => [
      profile.id,
      profile.full_name,
    ])
  );
  return expenses.map((expense) => ({
    ...expense,
    claimant_name: nameById.get(expense.user_id) || null,
  }));
}

export async function getExpense(id: string) {
  const { data, error } = await supabase
    .from("expenses")
    .select("*")
    .eq("id", id)
    .single();
  if (error) {
    throw error;
  }
  return data;
}

// Atomic, server-validated status transition.
// Delegates to the `transition_expense_status` Postgres RPC so the status
// update + audit-history insert run in a single transaction, the legal state
// machine is enforced server-side, and optimistic concurrency (fromStatus)
// prevents two admins from clobbering each other.
//
// NOTE: `changedBy` is intentionally unused here — the RPC derives the actor
// from `auth.uid()` server-side, which is more trustworthy than a client arg.
export async function updateExpenseStatus(
  expenseId: string,
  fromStatus: string,
  toStatus: string,
  comment: string | null | undefined,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  _changedBy: string
) {
  const { data, error } = await supabase.rpc("transition_expense_status", {
    p_expense_id: expenseId,
    p_from_status: fromStatus,
    p_to_status: toStatus,
    p_comment: comment?.trim() || null,
  });
  if (error) {
    throw error;
  }
  return data;
}

export async function getExpenseHistory(expenseId: string) {
  const { data, error } = await supabase
    .from("expense_status_history")
    .select("*")
    .eq("expense_id", expenseId)
    .order("changed_at", { ascending: true });
  if (error) {
    throw error;
  }
  return data || [];
}
