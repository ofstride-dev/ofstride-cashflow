-- Migration: 20260729000000_cashflow_v1.sql
-- Description: Cashflow Module v1 Tables, RLS, and Read-Only Expense View Mapping

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 1. ENUMS
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'cashflow_party_type') THEN
        CREATE TYPE cashflow_party_type AS ENUM ('vendor', 'customer');
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'cashflow_status') THEN
        CREATE TYPE cashflow_status AS ENUM ('draft', 'pending', 'approved', 'paid', 'overdue', 'cancelled');
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'msme_category_enum') THEN
        CREATE TYPE msme_category_enum AS ENUM ('none', 'micro', 'small', 'medium');
    END IF;
END
$$;

-- 2. VENDORS & CUSTOMERS
CREATE TABLE IF NOT EXISTS public.cashflow_entities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID REFERENCES public.companies(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    entity_type cashflow_party_type NOT NULL,
    pan TEXT,
    gstin TEXT,
    msme_category msme_category_enum DEFAULT 'none',
    msme_registered BOOLEAN DEFAULT FALSE,
    bank_details JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. AP BILLS (Vendors)
CREATE TABLE IF NOT EXISTS public.cashflow_bills (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID REFERENCES public.companies(id) ON DELETE CASCADE,
    vendor_id UUID REFERENCES public.cashflow_entities(id) ON DELETE RESTRICT,
    bill_number TEXT NOT NULL,
    bill_date DATE NOT NULL,
    due_date DATE NOT NULL,
    amount NUMERIC(12, 2) NOT NULL CHECK (amount >= 0),
    gst_amount NUMERIC(12, 2) DEFAULT 0.00,
    tds_amount NUMERIC(12, 2) DEFAULT 0.00,
    status cashflow_status DEFAULT 'pending',
    ocr_raw_data JSONB DEFAULT '{}'::jsonb,
    created_by UUID REFERENCES auth.users(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 4. AR INVOICES (Customers)
CREATE TABLE IF NOT EXISTS public.cashflow_invoices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID REFERENCES public.companies(id) ON DELETE CASCADE,
    customer_id UUID REFERENCES public.cashflow_entities(id) ON DELETE RESTRICT,
    invoice_number TEXT NOT NULL UNIQUE,
    invoice_date DATE NOT NULL,
    due_date DATE NOT NULL,
    amount NUMERIC(12, 2) NOT NULL CHECK (amount >= 0),
    gst_amount NUMERIC(12, 2) DEFAULT 0.00,
    status cashflow_status DEFAULT 'pending',
    irn_number TEXT,
    is_proforma BOOLEAN DEFAULT FALSE,
    created_by UUID REFERENCES auth.users(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 4B. AR ENHANCEMENTS (idempotent)
-- Supports multi-item invoice input from frontend and optional freeform notes.
ALTER TABLE public.cashflow_invoices
    ADD COLUMN IF NOT EXISTS item_services JSONB DEFAULT '[]'::jsonb;

ALTER TABLE public.cashflow_invoices
    ADD COLUMN IF NOT EXISTS notes TEXT;

-- 5. PAYMENTS & COLLECTIONS
CREATE TABLE IF NOT EXISTS public.cashflow_transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID REFERENCES public.companies(id) ON DELETE CASCADE,
    bill_id UUID REFERENCES public.cashflow_bills(id) ON DELETE SET NULL,
    invoice_id UUID REFERENCES public.cashflow_invoices(id) ON DELETE SET NULL,
    transaction_date DATE NOT NULL,
    amount NUMERIC(12, 2) NOT NULL,
    payment_mode TEXT NOT NULL DEFAULT 'bank_transfer',
    reference_no TEXT,
    created_by UUID REFERENCES auth.users(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 6. PETTY CASH & AUTOCATEGORIZATION LEDGER
CREATE TABLE IF NOT EXISTS public.cashflow_petty_cash (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID REFERENCES public.companies(id) ON DELETE CASCADE,
    entry_date DATE NOT NULL DEFAULT CURRENT_DATE,
    description TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'Uncategorized',
    auto_categorized BOOLEAN DEFAULT FALSE,
    cash_in NUMERIC(12, 2) DEFAULT 0.00 CHECK (cash_in >= 0),
    cash_out NUMERIC(12, 2) DEFAULT 0.00 CHECK (cash_out >= 0),
    status cashflow_status DEFAULT 'pending',
    approved_at TIMESTAMPTZ,
    recorded_by UUID REFERENCES auth.users(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE public.cashflow_petty_cash
    ADD COLUMN IF NOT EXISTS status cashflow_status DEFAULT 'pending';

ALTER TABLE public.cashflow_petty_cash
    ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ;

ALTER TABLE public.cashflow_entities
    ADD COLUMN IF NOT EXISTS company_id UUID REFERENCES public.companies(id) ON DELETE CASCADE;

ALTER TABLE public.cashflow_bills
    ADD COLUMN IF NOT EXISTS company_id UUID REFERENCES public.companies(id) ON DELETE CASCADE;

ALTER TABLE public.cashflow_invoices
    ADD COLUMN IF NOT EXISTS company_id UUID REFERENCES public.companies(id) ON DELETE CASCADE;

ALTER TABLE public.cashflow_transactions
    ADD COLUMN IF NOT EXISTS company_id UUID REFERENCES public.companies(id) ON DELETE CASCADE;

ALTER TABLE public.cashflow_petty_cash
    ADD COLUMN IF NOT EXISTS company_id UUID REFERENCES public.companies(id) ON DELETE CASCADE;

ALTER TABLE public.cashflow_bank_reconcile_runs
    ADD COLUMN IF NOT EXISTS company_id UUID REFERENCES public.companies(id) ON DELETE CASCADE;

ALTER TABLE public.cashflow_bank_reconcile_rows
    ADD COLUMN IF NOT EXISTS company_id UUID REFERENCES public.companies(id) ON DELETE CASCADE;

ALTER TABLE public.cashflow_period_close
    ADD COLUMN IF NOT EXISTS company_id UUID REFERENCES public.companies(id) ON DELETE CASCADE;

UPDATE public.cashflow_petty_cash
SET status = 'pending'
WHERE status IS NULL;

-- 6B. BANK STATEMENT IMPORT / RECONCILIATION RUNS
CREATE TABLE IF NOT EXISTS public.cashflow_bank_reconcile_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID REFERENCES public.companies(id) ON DELETE CASCADE,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    source_file_name TEXT,
    source_file_type TEXT,
    summary JSONB DEFAULT '{}'::jsonb,
    created_by UUID REFERENCES auth.users(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.cashflow_bank_reconcile_rows (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID REFERENCES public.companies(id) ON DELETE CASCADE,
    run_id UUID NOT NULL REFERENCES public.cashflow_bank_reconcile_runs(id) ON DELETE CASCADE,
    source_side TEXT NOT NULL CHECK (source_side IN ('bank', 'platform')),
    voucher_type TEXT,
    voucher_number TEXT,
    voucher_date DATE,
    party_name TEXT,
    amount NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
    status TEXT NOT NULL CHECK (status IN ('matched', 'amount_mismatch', 'missing_in_bank_statement', 'unexpected_in_bank_statement')),
    notes TEXT,
    raw_data JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cashflow_bank_rows_run_id ON public.cashflow_bank_reconcile_rows(run_id);
CREATE INDEX IF NOT EXISTS idx_cashflow_bank_rows_status ON public.cashflow_bank_reconcile_rows(status);
CREATE INDEX IF NOT EXISTS idx_cashflow_entities_company_id ON public.cashflow_entities(company_id);
CREATE INDEX IF NOT EXISTS idx_cashflow_bills_company_id ON public.cashflow_bills(company_id);
CREATE INDEX IF NOT EXISTS idx_cashflow_invoices_company_id ON public.cashflow_invoices(company_id);
CREATE INDEX IF NOT EXISTS idx_cashflow_transactions_company_id ON public.cashflow_transactions(company_id);
CREATE INDEX IF NOT EXISTS idx_cashflow_petty_cash_company_id ON public.cashflow_petty_cash(company_id);
CREATE INDEX IF NOT EXISTS idx_cashflow_bank_runs_company_id ON public.cashflow_bank_reconcile_runs(company_id);
CREATE INDEX IF NOT EXISTS idx_cashflow_bank_rows_company_id ON public.cashflow_bank_reconcile_rows(company_id);
CREATE INDEX IF NOT EXISTS idx_cashflow_period_close_company_id ON public.cashflow_period_close(company_id);

-- 6C. SOFT PERIOD CLOSE TRACKING (NO HARD LOCK YET)
CREATE TABLE IF NOT EXISTS public.cashflow_period_close (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID REFERENCES public.companies(id) ON DELETE CASCADE,
    period_month DATE NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('open', 'soft_closed', 'hard_closed')) DEFAULT 'open',
    notes TEXT,
    closed_by UUID REFERENCES auth.users(id),
    closed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (period_month)
);

-- 7. READ-ONLY EXPENSE MAPPER VIEW
-- Maps existing expense claims transparently into cashflow operational cash outflows
CREATE OR REPLACE VIEW public.vw_cashflow_expense_outflows AS
SELECT 
    id AS source_id,
    'employee_expense' AS source_type,
    amount,
    spend_date AS transaction_date,
    category,
    description,
    status,
    company_id,
    user_id,
    created_at
FROM public.expenses;

-- 8. ROW LEVEL SECURITY (RLS)
ALTER TABLE public.cashflow_entities ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.cashflow_bills ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.cashflow_invoices ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.cashflow_transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.cashflow_petty_cash ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.cashflow_bank_reconcile_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.cashflow_bank_reconcile_rows ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.cashflow_period_close ENABLE ROW LEVEL SECURITY;

-- Security Policies (Admin / Finance Access)
DROP POLICY IF EXISTS cashflow_admin_all ON public.cashflow_entities;
CREATE POLICY cashflow_admin_all ON public.cashflow_entities FOR ALL TO authenticated USING (public.is_admin() AND company_id = public.my_company_id()) WITH CHECK (public.is_admin() AND company_id = public.my_company_id());

DROP POLICY IF EXISTS cashflow_bills_all ON public.cashflow_bills;
CREATE POLICY cashflow_bills_all ON public.cashflow_bills FOR ALL TO authenticated USING (company_id = public.my_company_id()) WITH CHECK (company_id = public.my_company_id());

DROP POLICY IF EXISTS cashflow_invoices_all ON public.cashflow_invoices;
CREATE POLICY cashflow_invoices_all ON public.cashflow_invoices FOR ALL TO authenticated USING (company_id = public.my_company_id()) WITH CHECK (company_id = public.my_company_id());

DROP POLICY IF EXISTS cashflow_transactions_all ON public.cashflow_transactions;
CREATE POLICY cashflow_transactions_all ON public.cashflow_transactions FOR ALL TO authenticated USING (company_id = public.my_company_id()) WITH CHECK (company_id = public.my_company_id());

DROP POLICY IF EXISTS cashflow_petty_cash_all ON public.cashflow_petty_cash;
CREATE POLICY cashflow_petty_cash_all ON public.cashflow_petty_cash FOR ALL TO authenticated USING (company_id = public.my_company_id()) WITH CHECK (company_id = public.my_company_id());

DROP POLICY IF EXISTS cashflow_bank_runs_all ON public.cashflow_bank_reconcile_runs;
CREATE POLICY cashflow_bank_runs_all ON public.cashflow_bank_reconcile_runs FOR ALL TO authenticated USING (company_id = public.my_company_id()) WITH CHECK (company_id = public.my_company_id());

DROP POLICY IF EXISTS cashflow_bank_rows_all ON public.cashflow_bank_reconcile_rows;
CREATE POLICY cashflow_bank_rows_all ON public.cashflow_bank_reconcile_rows FOR ALL TO authenticated USING (company_id = public.my_company_id()) WITH CHECK (company_id = public.my_company_id());

DROP POLICY IF EXISTS cashflow_period_close_all ON public.cashflow_period_close;
CREATE POLICY cashflow_period_close_all ON public.cashflow_period_close FOR ALL TO authenticated USING (company_id = public.my_company_id()) WITH CHECK (company_id = public.my_company_id());

COMMIT;