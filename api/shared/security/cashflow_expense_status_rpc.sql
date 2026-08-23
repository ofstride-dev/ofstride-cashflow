-- OfStride Cashflow — tenant-safe expense status transition
--
-- Run this migration in the Supabase SQL Editor after the expense tables and
-- Phase 7 company_id columns have been applied. It replaces the older RPC
-- that inserted expense_status_history rows without company_id.

BEGIN;

DROP FUNCTION IF EXISTS public.transition_expense_status(uuid, text, text, text);

CREATE FUNCTION public.transition_expense_status(
    p_expense_id uuid,
    p_from_status text,
    p_to_status text,
    p_comment text DEFAULT NULL
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public'
AS $$
DECLARE
    v_user_id uuid := auth.uid();
    v_company_id uuid;
    v_current_status text;
    v_comment text := NULLIF(trim(p_comment), '');
BEGIN
    IF v_user_id IS NULL THEN
        RAISE EXCEPTION 'Authentication required';
    END IF;

    SELECT e.company_id, e.status
      INTO v_company_id, v_current_status
      FROM public.expenses e
     WHERE e.id = p_expense_id
     FOR UPDATE;

    IF v_company_id IS NULL THEN
        RAISE EXCEPTION 'Expense claim not found or has no company';
    END IF;

    IF v_company_id IS DISTINCT FROM public.my_company_id() THEN
        RAISE EXCEPTION 'Expense claim belongs to another company';
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM public.profiles p
         WHERE p.id = v_user_id
           AND p.company_id = v_company_id
           AND lower(p.role::text) IN ('owner', 'admin', 'finance')
    ) THEN
        RAISE EXCEPTION 'Only company approvers can update expense claims';
    END IF;

    IF v_current_status IS DISTINCT FROM p_from_status THEN
        RAISE EXCEPTION 'Expense status changed; refresh and try again';
    END IF;

    IF p_to_status NOT IN ('approved', 'rejected', 'ready_for_payment', 'paid') THEN
        RAISE EXCEPTION 'Invalid expense status transition';
    END IF;

    IF NOT (
        (p_from_status = 'submitted' AND p_to_status IN ('approved', 'rejected')) OR
        (p_from_status = 'approved' AND p_to_status IN ('ready_for_payment', 'rejected')) OR
        (p_from_status = 'ready_for_payment' AND p_to_status = 'paid')
    ) THEN
        RAISE EXCEPTION 'Invalid expense status transition';
    END IF;

    UPDATE public.expenses
       SET status = p_to_status,
           admin_comment = COALESCE(v_comment, admin_comment),
           updated_at = now()
     WHERE id = p_expense_id;

    INSERT INTO public.expense_status_history (
        company_id,
        expense_id,
        from_status,
        to_status,
        comment,
        changed_by,
        changed_at
    ) VALUES (
        v_company_id,
        p_expense_id,
        p_from_status,
        p_to_status,
        v_comment,
        v_user_id,
        now()
    );

    RETURN jsonb_build_object(
        'expense_id', p_expense_id,
        'company_id', v_company_id,
        'from_status', p_from_status,
        'to_status', p_to_status
    );
END;
$$;

REVOKE ALL ON FUNCTION public.transition_expense_status(uuid, text, text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.transition_expense_status(uuid, text, text, text) TO authenticated;

COMMIT;