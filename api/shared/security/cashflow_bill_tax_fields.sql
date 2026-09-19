-- Explicit AP supplier and tax fields used by GSTR-2B reconciliation.
BEGIN;
ALTER TABLE public.cashflow_bills ADD COLUMN IF NOT EXISTS supplier_gstin TEXT;
ALTER TABLE public.cashflow_bills ADD COLUMN IF NOT EXISTS taxable_value NUMERIC(12, 2);
ALTER TABLE public.cashflow_bills ADD COLUMN IF NOT EXISTS cgst_amount NUMERIC(12, 2) DEFAULT 0;
ALTER TABLE public.cashflow_bills ADD COLUMN IF NOT EXISTS sgst_amount NUMERIC(12, 2) DEFAULT 0;
ALTER TABLE public.cashflow_bills ADD COLUMN IF NOT EXISTS igst_amount NUMERIC(12, 2) DEFAULT 0;
COMMIT;