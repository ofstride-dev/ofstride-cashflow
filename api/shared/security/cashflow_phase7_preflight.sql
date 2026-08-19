-- OfStride Cashflow Phase 7: ownership preflight and quarantine
--
-- This migration is deliberately fail-closed. It never guesses which company
-- owns an orphaned or legacy-default row. Resolve rows in the quarantine
-- tables, then re-run this file to apply the constraints.
--
-- Run after cash_flow_table.sql, expenses.sql, and cashflow_audit.sql.
-- This file commits the quarantine evidence. Do not skip it.

CREATE TABLE IF NOT EXISTS public.cashflow_phase7_quarantine (
    id BIGSERIAL PRIMARY KEY,
    table_name TEXT NOT NULL,
    row_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    row_data JSONB NOT NULL,
    quarantined_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ,
    UNIQUE (table_name, row_id, reason)
);

-- Child rows inherit ownership from their tenant-scoped parent.
ALTER TABLE public.expense_status_history
    ADD COLUMN IF NOT EXISTS company_id UUID;
ALTER TABLE public.expense_attachments
    ADD COLUMN IF NOT EXISTS company_id UUID;
ALTER TABLE public.cashflow_bank_reconcile_rows
    ADD COLUMN IF NOT EXISTS company_id UUID;

UPDATE public.expense_status_history h
SET company_id = e.company_id
FROM public.expenses e
WHERE h.expense_id = e.id AND h.company_id IS NULL;

UPDATE public.expense_attachments a
SET company_id = e.company_id
FROM public.expenses e
WHERE a.expense_id = e.id AND a.company_id IS NULL;

UPDATE public.cashflow_bank_reconcile_rows r
SET company_id = x.company_id
FROM public.cashflow_bank_reconcile_runs x
WHERE r.run_id = x.id AND r.company_id IS NULL;

-- Preserve evidence for every row that prevents safe enforcement. The INSERTs
-- are idempotent and include the current row snapshot for operator repair.
INSERT INTO public.cashflow_phase7_quarantine (table_name, row_id, reason, row_data)
SELECT 'cashflow_entities', id::text, 'missing_company_id', to_jsonb(t)
FROM public.cashflow_entities t WHERE company_id IS NULL
ON CONFLICT DO NOTHING;
INSERT INTO public.cashflow_phase7_quarantine (table_name, row_id, reason, row_data)
SELECT 'cashflow_bills', id::text, 'missing_company_id', to_jsonb(t)
FROM public.cashflow_bills t WHERE company_id IS NULL
ON CONFLICT DO NOTHING;
INSERT INTO public.cashflow_phase7_quarantine (table_name, row_id, reason, row_data)
SELECT 'cashflow_invoices', id::text, 'missing_company_id', to_jsonb(t)
FROM public.cashflow_invoices t WHERE company_id IS NULL
ON CONFLICT DO NOTHING;
INSERT INTO public.cashflow_phase7_quarantine (table_name, row_id, reason, row_data)
SELECT 'cashflow_transactions', id::text, 'missing_company_id', to_jsonb(t)
FROM public.cashflow_transactions t WHERE company_id IS NULL
ON CONFLICT DO NOTHING;
INSERT INTO public.cashflow_phase7_quarantine (table_name, row_id, reason, row_data)
SELECT 'cashflow_petty_cash', id::text, 'missing_company_id', to_jsonb(t)
FROM public.cashflow_petty_cash t WHERE company_id IS NULL
ON CONFLICT DO NOTHING;
INSERT INTO public.cashflow_phase7_quarantine (table_name, row_id, reason, row_data)
SELECT 'cashflow_bank_reconcile_runs', id::text, 'missing_company_id', to_jsonb(t)
FROM public.cashflow_bank_reconcile_runs t WHERE company_id IS NULL
ON CONFLICT DO NOTHING;
INSERT INTO public.cashflow_phase7_quarantine (table_name, row_id, reason, row_data)
SELECT 'cashflow_bank_reconcile_rows', id::text, 'missing_company_id', to_jsonb(t)
FROM public.cashflow_bank_reconcile_rows t WHERE company_id IS NULL
ON CONFLICT DO NOTHING;
INSERT INTO public.cashflow_phase7_quarantine (table_name, row_id, reason, row_data)
SELECT 'cashflow_period_close', id::text, 'missing_company_id', to_jsonb(t)
FROM public.cashflow_period_close t WHERE company_id IS NULL
ON CONFLICT DO NOTHING;
INSERT INTO public.cashflow_phase7_quarantine (table_name, row_id, reason, row_data)
SELECT 'expenses', id::text, 'legacy_default_company', to_jsonb(t)
FROM public.expenses t
WHERE company_id = '00000000-0000-0000-0000-000000000001'::uuid
ON CONFLICT DO NOTHING;
INSERT INTO public.cashflow_phase7_quarantine (table_name, row_id, reason, row_data)
SELECT 'expenses', id::text, 'missing_company_id', to_jsonb(t)
FROM public.expenses t WHERE company_id IS NULL
ON CONFLICT DO NOTHING;
INSERT INTO public.cashflow_phase7_quarantine (table_name, row_id, reason, row_data)
SELECT 'cashflow_audit', id::text, 'missing_company_id', to_jsonb(t)
FROM public.cashflow_audit t WHERE company_id IS NULL
ON CONFLICT DO NOTHING;
INSERT INTO public.cashflow_phase7_quarantine (table_name, row_id, reason, row_data)
SELECT 'expense_status_history', id::text, 'missing_company_id', to_jsonb(t)
FROM public.expense_status_history t WHERE company_id IS NULL
ON CONFLICT DO NOTHING;
INSERT INTO public.cashflow_phase7_quarantine (table_name, row_id, reason, row_data)
SELECT 'expense_attachments', id::text, 'missing_company_id', to_jsonb(t)
FROM public.expense_attachments t WHERE company_id IS NULL
ON CONFLICT DO NOTHING;
INSERT INTO public.cashflow_phase7_quarantine (table_name, row_id, reason, row_data)
SELECT 'cashflow_bank_reconcile_rows', id::text, 'missing_parent_run', to_jsonb(t)
FROM public.cashflow_bank_reconcile_rows t
WHERE NOT EXISTS (
    SELECT 1 FROM public.cashflow_bank_reconcile_runs r WHERE r.id = t.run_id
)
ON CONFLICT DO NOTHING;

COMMIT;