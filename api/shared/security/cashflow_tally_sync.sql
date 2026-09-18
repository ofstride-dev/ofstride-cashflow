-- Tally Sync source identity and audit data.
BEGIN;

CREATE TABLE IF NOT EXISTS public.cashflow_tally_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES public.companies(id) ON DELETE CASCADE,
    invoice_id TEXT NOT NULL,
    remote_id TEXT,
    voucher_type TEXT NOT NULL,
    voucher_date DATE NOT NULL,
    total_amount NUMERIC(12, 2) NOT NULL DEFAULT 0,
    direction TEXT NOT NULL CHECK (direction IN ('debit', 'credit')),
    raw_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by UUID REFERENCES auth.users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (company_id, invoice_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS cashflow_tally_records_remote_key
    ON public.cashflow_tally_records(company_id, remote_id)
    WHERE remote_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS cashflow_tally_records_company_date
    ON public.cashflow_tally_records(company_id, voucher_date DESC);

ALTER TABLE public.cashflow_tally_records ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS cashflow_tally_records_select_own ON public.cashflow_tally_records;
CREATE POLICY cashflow_tally_records_select_own ON public.cashflow_tally_records
    FOR SELECT TO authenticated USING (company_id = public.my_company_id());

COMMIT;