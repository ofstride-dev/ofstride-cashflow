-- OfStride Cashflow Phase 8: membership boundary (targeted first slice)
--
-- Additive only. Current Cashflow requests continue to resolve their active
-- tenant through the existing profile/TenantContext path. This migration adds
-- the durable membership model needed before multi-company switching is
-- enabled; it does not change current routes or silently switch tenants.

BEGIN;

CREATE TABLE IF NOT EXISTS public.company_memberships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    company_id UUID NOT NULL REFERENCES public.companies(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('owner', 'admin', 'finance', 'employee')),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'invited', 'suspended', 'revoked')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, company_id)
);

CREATE INDEX IF NOT EXISTS company_memberships_user_status_idx
    ON public.company_memberships(user_id, status);
CREATE INDEX IF NOT EXISTS company_memberships_company_status_idx
    ON public.company_memberships(company_id, status);

-- Backfill the current one-profile/one-company assignments. Existing valid
-- memberships are preserved and never overwritten by a later re-run.
INSERT INTO public.company_memberships (user_id, company_id, role, status)
SELECT p.id, p.company_id, p.role, 'active'
FROM public.profiles p
JOIN public.companies c ON c.id = p.company_id
WHERE p.company_id IS NOT NULL
  AND p.role IN ('owner', 'admin', 'finance', 'employee')
ON CONFLICT (user_id, company_id) DO NOTHING;

ALTER TABLE public.company_memberships ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS company_memberships_select_own ON public.company_memberships;
CREATE POLICY company_memberships_select_own ON public.company_memberships
    FOR SELECT TO authenticated
    USING (user_id = auth.uid());

-- Membership writes remain server-controlled during this first slice. Invite
-- acceptance and company switching must use a reviewed RPC in a later slice;
-- clients must not assign themselves roles or companies through table writes.
DROP POLICY IF EXISTS company_memberships_no_client_insert ON public.company_memberships;
CREATE POLICY company_memberships_no_client_insert ON public.company_memberships
    FOR INSERT TO authenticated
    WITH CHECK (false);

DROP POLICY IF EXISTS company_memberships_no_client_update ON public.company_memberships;
CREATE POLICY company_memberships_no_client_update ON public.company_memberships
    FOR UPDATE TO authenticated
    USING (false)
    WITH CHECK (false);

DROP POLICY IF EXISTS company_memberships_no_client_delete ON public.company_memberships;
CREATE POLICY company_memberships_no_client_delete ON public.company_memberships
    FOR DELETE TO authenticated
    USING (false);

CREATE OR REPLACE FUNCTION public.get_my_company_memberships()
RETURNS TABLE (
    membership_id UUID,
    company_id UUID,
    company_name TEXT,
    company_slug TEXT,
    role TEXT,
    status TEXT
)
LANGUAGE sql
SECURITY DEFINER
STABLE
SET search_path TO 'public'
AS $$
    SELECT
        m.id,
        m.company_id,
        c.name,
        c.slug,
        m.role,
        m.status
    FROM public.company_memberships m
    JOIN public.companies c ON c.id = m.company_id
    WHERE m.user_id = auth.uid()
    ORDER BY c.name, m.company_id;
$$;

REVOKE ALL ON FUNCTION public.get_my_company_memberships() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.get_my_company_memberships() TO authenticated;

-- Validate a requested active company without trusting a client-supplied
-- company_id. This is read-only in the first slice; the current profile-based
-- TenantContext resolver remains unchanged until the switch UI is introduced.
CREATE OR REPLACE FUNCTION public.resolve_active_company_membership(p_membership_id uuid)
RETURNS TABLE (
    membership_id UUID,
    company_id UUID,
    company_name TEXT,
    company_slug TEXT,
    role TEXT,
    status TEXT
)
LANGUAGE sql
SECURITY DEFINER
STABLE
SET search_path TO 'public'
AS $$
    SELECT
        m.id,
        m.company_id,
        c.name,
        c.slug,
        m.role,
        m.status
    FROM public.company_memberships m
    JOIN public.companies c ON c.id = m.company_id
    WHERE m.id = p_membership_id
      AND m.user_id = auth.uid()
      AND m.status = 'active';
$$;

REVOKE ALL ON FUNCTION public.resolve_active_company_membership(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.resolve_active_company_membership(uuid) TO authenticated;

COMMIT;