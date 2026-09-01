-- Claimant-only deletion for draft/pending/submitted reimbursement claims.
BEGIN;

CREATE OR REPLACE FUNCTION public.delete_expense_claim(p_expense_id uuid)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public'
AS $$
DECLARE
  v_user_id uuid := auth.uid();
  v_company_id uuid;
  v_status text;
BEGIN
  IF v_user_id IS NULL THEN RAISE EXCEPTION 'Authentication required'; END IF;
  SELECT company_id, status INTO v_company_id, v_status
    FROM public.expenses WHERE id = p_expense_id AND user_id = v_user_id FOR UPDATE;
  IF v_company_id IS NULL THEN RAISE EXCEPTION 'Claim not found or not owned by the current user'; END IF;
  IF v_status NOT IN ('draft', 'pending', 'submitted') THEN
    RAISE EXCEPTION 'Only draft, pending, or submitted claims can be deleted';
  END IF;
  DELETE FROM public.expenses WHERE id = p_expense_id AND user_id = v_user_id;
  RETURN jsonb_build_object('deleted', true, 'expense_id', p_expense_id);
END;
$$;

REVOKE ALL ON FUNCTION public.delete_expense_claim(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.delete_expense_claim(uuid) TO authenticated;

CREATE OR REPLACE FUNCTION public.update_expense_claim(p_expense_id uuid, p_claim jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path TO 'public' AS $$
DECLARE v_user_id uuid := auth.uid(); v_status text; v_company_id uuid; v_row public.expenses;
BEGIN
  IF v_user_id IS NULL THEN RAISE EXCEPTION 'Authentication required'; END IF;
  SELECT status, company_id INTO v_status, v_company_id FROM public.expenses
    WHERE id = p_expense_id AND user_id = v_user_id FOR UPDATE;
  IF v_company_id IS NULL THEN RAISE EXCEPTION 'Claim not found or not owned by the current user'; END IF;
  IF v_status NOT IN ('draft', 'pending', 'submitted') THEN RAISE EXCEPTION 'Only draft, pending, or submitted claims can be edited'; END IF;
  UPDATE public.expenses SET amount = (p_claim->>'amount')::numeric, spend_date = (p_claim->>'spend_date')::date,
    category = p_claim->>'category', description = p_claim->>'description', client_project = NULLIF(p_claim->>'client_project',''),
    has_invoice = COALESCE((p_claim->>'has_invoice')::boolean, false), supplier_gstin = NULLIF(p_claim->>'supplier_gstin',''),
    invoice_number = NULLIF(p_claim->>'invoice_number',''), taxable_value = NULLIF(p_claim->>'taxable_value','')::numeric,
    cgst = NULLIF(p_claim->>'cgst','')::numeric, sgst = NULLIF(p_claim->>'sgst','')::numeric, igst = NULLIF(p_claim->>'igst','')::numeric,
    updated_at = now() WHERE id = p_expense_id AND user_id = v_user_id RETURNING * INTO v_row;
  RETURN to_jsonb(v_row);
END; $$;
REVOKE ALL ON FUNCTION public.update_expense_claim(uuid, jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.update_expense_claim(uuid, jsonb) TO authenticated;
COMMIT;