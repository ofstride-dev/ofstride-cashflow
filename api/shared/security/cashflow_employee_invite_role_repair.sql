-- Repair profiles that accepted an employee invite while retaining a stale
-- admin role from an earlier profile/signup record.
-- Run after cashflow_phase9_invite_hardening.sql.

BEGIN;

UPDATE public.profiles p
SET role = 'employee'
FROM public.company_invites ci
WHERE ci.accepted_by = p.id
  AND ci.status = 'accepted'
  AND lower((ci.role)::text) = 'employee'
  AND p.company_id = ci.company_id
  AND lower((p.role)::text) IN ('admin', 'finance');

UPDATE public.company_memberships m
SET role = 'employee', updated_at = now()
FROM public.company_invites ci
WHERE ci.accepted_by = m.user_id
  AND ci.status = 'accepted'
  AND lower((ci.role)::text) = 'employee'
  AND m.company_id = ci.company_id
  AND lower(m.role) IN ('admin', 'finance');

COMMIT;