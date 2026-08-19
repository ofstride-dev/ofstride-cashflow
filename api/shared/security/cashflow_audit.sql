-- ============================================================================
-- OfStride CashFlow — tenant-scoped action audit (idempotent, additive)
-- Deploy after cashflow_* tables exist. Stores user/company/action/resource
-- telemetry for every Cashflow operation so tenant behavior is observable.
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.cashflow_audit (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID REFERENCES public.companies(id) ON DELETE CASCADE,
    user_id UUID NOT NULL,
    role TEXT,
    action TEXT NOT NULL,
    resource_type TEXT,
    resource_id TEXT,
    result TEXT NOT NULL DEFAULT 'success',
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cashflow_audit_company_created
    ON public.cashflow_audit (company_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_cashflow_audit_company_resource
    ON public.cashflow_audit (company_id, resource_type, resource_id);

ALTER TABLE public.cashflow_audit ENABLE ROW LEVEL SECURITY;

-- Users may read audit records for their own company.
DROP POLICY IF EXISTS cashflow_audit_select_own ON public.cashflow_audit;
CREATE POLICY cashflow_audit_select_own ON public.cashflow_audit
    AS PERMISSIVE FOR SELECT TO authenticated
    USING (company_id = public.my_company_id());

-- Server-side insert via a SECURITY DEFINER function. SECURITY DEFINER can
-- bypass RLS, so the function re-validates company ownership against the
-- caller's membership rather than trusting the supplied company_id.
CREATE OR REPLACE FUNCTION public.record_cashflow_audit(
    p_company_id uuid,
    p_user_id uuid,
    p_role text,
    p_action text,
    p_resource_type text,
    p_resource_id text,
    p_result text,
    p_details jsonb
) RETURNS public.cashflow_audit
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_row public.cashflow_audit;
BEGIN
    IF p_company_id IS DISTINCT FROM public.my_company_id() THEN
        RAISE EXCEPTION 'cross-company audit rejected';
    END IF;

    INSERT INTO public.cashflow_audit (
        company_id, user_id, role, action,
        resource_type, resource_id, result, details
    ) VALUES (
        p_company_id,
        COALESCE(p_user_id, auth.uid()),
        p_role,
        COALESCE(NULLIF(p_action, ''), 'unknown'),
        p_resource_type,
        p_resource_id,
        COALESCE(NULLIF(p_result, ''), 'success'),
        COALESCE(p_details, '{}'::jsonb)
    )
    RETURNING * INTO v_row;

    RETURN v_row;
END;
$$;