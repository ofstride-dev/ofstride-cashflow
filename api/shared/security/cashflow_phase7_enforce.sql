-- OfStride Cashflow Phase 7: ownership enforcement
-- Run only after cashflow_phase7_preflight.sql and after all unresolved
-- quarantine rows have been repaired and marked with resolved_at.

BEGIN;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.cashflow_phase7_quarantine WHERE resolved_at IS NULL) THEN
        RAISE EXCEPTION 'Phase 7 stopped: resolve rows in public.cashflow_phase7_quarantine first';
    END IF;
END $$;

ALTER TABLE public.cashflow_entities ALTER COLUMN company_id SET NOT NULL;
ALTER TABLE public.cashflow_bills ALTER COLUMN company_id SET NOT NULL;
ALTER TABLE public.cashflow_invoices ALTER COLUMN company_id SET NOT NULL;
ALTER TABLE public.cashflow_transactions ALTER COLUMN company_id SET NOT NULL;
ALTER TABLE public.cashflow_petty_cash ALTER COLUMN company_id SET NOT NULL;
ALTER TABLE public.cashflow_bank_reconcile_runs ALTER COLUMN company_id SET NOT NULL;
ALTER TABLE public.cashflow_bank_reconcile_rows ALTER COLUMN company_id SET NOT NULL;
ALTER TABLE public.cashflow_period_close ALTER COLUMN company_id SET NOT NULL;
ALTER TABLE public.expenses ALTER COLUMN company_id SET NOT NULL;
ALTER TABLE public.expense_status_history ALTER COLUMN company_id SET NOT NULL;
ALTER TABLE public.expense_attachments ALTER COLUMN company_id SET NOT NULL;
ALTER TABLE public.cashflow_audit ALTER COLUMN company_id SET NOT NULL;
ALTER TABLE public.expenses ALTER COLUMN company_id DROP DEFAULT;

DO $$
DECLARE item RECORD;
BEGIN
    FOR item IN SELECT * FROM (VALUES
        ('cashflow_entities', 'cashflow_entities_company_id_fkey'),
        ('cashflow_bills', 'cashflow_bills_company_id_fkey'),
        ('cashflow_invoices', 'cashflow_invoices_company_id_fkey'),
        ('cashflow_transactions', 'cashflow_transactions_company_id_fkey'),
        ('cashflow_petty_cash', 'cashflow_petty_cash_company_id_fkey'),
        ('cashflow_bank_reconcile_runs', 'cashflow_bank_reconcile_runs_company_id_fkey'),
        ('cashflow_bank_reconcile_rows', 'cashflow_bank_reconcile_rows_company_id_fkey'),
        ('cashflow_period_close', 'cashflow_period_close_company_id_fkey'),
        ('expenses', 'expenses_company_id_fkey'),
        ('expense_status_history', 'expense_status_history_company_id_fkey'),
        ('expense_attachments', 'expense_attachments_company_id_fkey')
    ) AS v(table_name, constraint_name) LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = item.constraint_name) THEN
            EXECUTE format('ALTER TABLE public.%I ADD CONSTRAINT %I FOREIGN KEY (company_id) REFERENCES public.companies(id) ON DELETE CASCADE', item.table_name, item.constraint_name);
        END IF;
    END LOOP;
END $$;

CREATE INDEX IF NOT EXISTS cashflow_entities_company_id_idx ON public.cashflow_entities(company_id);
CREATE INDEX IF NOT EXISTS cashflow_bills_company_id_idx ON public.cashflow_bills(company_id);
CREATE INDEX IF NOT EXISTS cashflow_invoices_company_id_idx ON public.cashflow_invoices(company_id);
CREATE INDEX IF NOT EXISTS cashflow_transactions_company_id_idx ON public.cashflow_transactions(company_id);
CREATE INDEX IF NOT EXISTS cashflow_petty_cash_company_id_idx ON public.cashflow_petty_cash(company_id);
CREATE INDEX IF NOT EXISTS cashflow_reconcile_runs_company_id_idx ON public.cashflow_bank_reconcile_runs(company_id);
CREATE INDEX IF NOT EXISTS cashflow_reconcile_rows_company_id_idx ON public.cashflow_bank_reconcile_rows(company_id);
CREATE INDEX IF NOT EXISTS cashflow_period_close_company_id_idx ON public.cashflow_period_close(company_id);
CREATE INDEX IF NOT EXISTS expense_status_history_company_id_idx ON public.expense_status_history(company_id);
CREATE INDEX IF NOT EXISTS expense_attachments_company_id_idx ON public.expense_attachments(company_id);

ALTER TABLE public.cashflow_invoices DROP CONSTRAINT IF EXISTS cashflow_invoices_invoice_number_key;
ALTER TABLE public.cashflow_period_close DROP CONSTRAINT IF EXISTS cashflow_period_close_period_month_key;
CREATE UNIQUE INDEX IF NOT EXISTS cashflow_invoices_company_number_key ON public.cashflow_invoices(company_id, invoice_number);
CREATE UNIQUE INDEX IF NOT EXISTS cashflow_period_close_company_month_key ON public.cashflow_period_close(company_id, period_month);

COMMIT;