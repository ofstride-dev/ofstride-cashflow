BEGIN;

DO $$
DECLARE
  v_company UUID;
BEGIN
  v_company := NULLIF(trim('YOUR-COMPANY-UUID'), '')::uuid;
  DELETE FROM public.cashflow_bank_reconcile_rows WHERE company_id = v_company;
  DELETE FROM public.cashflow_bank_reconcile_runs WHERE company_id = v_company;
  DELETE FROM public.cashflow_transactions WHERE company_id = v_company;
  DELETE FROM public.cashflow_tally_records WHERE company_id = v_company;
  DELETE FROM public.cashflow_invoices WHERE company_id = v_company;
  DELETE FROM public.cashflow_bills WHERE company_id = v_company;
  DELETE FROM public.cashflow_petty_cash WHERE company_id = v_company;
  DELETE FROM public.expense_status_history WHERE company_id = v_company;
  DELETE FROM public.expense_attachments WHERE company_id = v_company;
  DELETE FROM public.expenses WHERE company_id = v_company;
  DELETE FROM public.cashflow_entities WHERE company_id = v_company;
  DELETE FROM public.cashflow_audit WHERE company_id = v_company;
END $$;

COMMIT;
