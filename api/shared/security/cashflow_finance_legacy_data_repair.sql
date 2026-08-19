-- One-time repair for data created before Cashflow tenant isolation.
--
-- Policy: all existing Cashflow/expense data is the Finance workspace's
-- historical data. Product/Test (and every other workspace) must start empty.
-- This migration is deliberately guarded by the Finance owner's email and
-- updates only ownership columns; it does not delete business records.
-- Run after the Cashflow tables and company schema exist.

BEGIN;

DO $$
DECLARE
    v_finance_company uuid;
    v_finance_count integer;
BEGIN
    SELECT count(*) INTO v_finance_count
    FROM public.companies c
    JOIN auth.users u ON u.id = c.owner_user_id
    WHERE lower(u.email) = 'ofstride@gmail.com';

    IF v_finance_count <> 1 THEN
        RAISE EXCEPTION
            'Expected exactly one company owned by ofstride@gmail.com, found %; no repair performed',
            v_finance_count;
    END IF;

    SELECT c.id INTO v_finance_company
    FROM public.companies c
    JOIN auth.users u ON u.id = c.owner_user_id
    WHERE lower(u.email) = 'ofstride@gmail.com';

    -- Move all historical tenant-bearing data to Finance. This deliberately
    -- includes rows currently attached to another workspace: those rows were
    -- created before the tenant gate and the requested outcome is a blank
    -- slate for Product/Test.
    UPDATE public.cashflow_entities SET company_id = v_finance_company;
    UPDATE public.cashflow_bills SET company_id = v_finance_company;
    UPDATE public.cashflow_invoices SET company_id = v_finance_company;
    UPDATE public.cashflow_transactions SET company_id = v_finance_company;
    UPDATE public.cashflow_petty_cash SET company_id = v_finance_company;
    UPDATE public.cashflow_bank_reconcile_runs SET company_id = v_finance_company;
    UPDATE public.cashflow_bank_reconcile_rows SET company_id = v_finance_company;
    UPDATE public.cashflow_period_close SET company_id = v_finance_company;
    UPDATE public.expenses SET company_id = v_finance_company;
    UPDATE public.expense_status_history SET company_id = v_finance_company;
    UPDATE public.expense_attachments SET company_id = v_finance_company;
    UPDATE public.cashflow_audit SET company_id = v_finance_company;

    -- New rows must always provide an explicit tenant. Never recreate the old
    -- phantom/default company behavior.
    ALTER TABLE public.expenses ALTER COLUMN company_id DROP DEFAULT;
    ALTER TABLE public.profiles ALTER COLUMN company_id DROP DEFAULT;
END $$;

COMMIT;

-- Verification (run separately after the transaction):
-- SELECT c.name, count(e.id) FROM public.companies c
-- LEFT JOIN public.expenses e ON e.company_id = c.id
-- GROUP BY c.id, c.name ORDER BY c.name;
-- Repeat the count query for each cashflow_* table.