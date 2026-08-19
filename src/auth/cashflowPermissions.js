export const CASHFLOW_ROLES = ["owner", "admin", "finance", "employee"];
export const CASHFLOW_APPROVER_ROLES = ["owner", "admin", "finance"];

function normalizeRole(role) {
  return String(role || "").trim().toLowerCase();
}

export function canUseCashflow(profile) {
  return Boolean(profile?.company_id && CASHFLOW_ROLES.includes(normalizeRole(profile?.role)));
}

export function canApproveCashflow(profile) {
  return CASHFLOW_APPROVER_ROLES.includes(normalizeRole(profile?.role));
}

export function canManageInvites(profile) {
  return canApproveCashflow(profile);
}

export function canCreatePayments(profile) {
  return canApproveCashflow(profile);
}

export function canViewExpenseAdminQueue(profile) {
  return canApproveCashflow(profile);
}

export function hasCashflowRole(profile, requiredRoles) {
  const roles = Array.isArray(requiredRoles) ? requiredRoles.map(normalizeRole) : [];
  return roles.length === 0 || roles.includes(normalizeRole(profile?.role));
}