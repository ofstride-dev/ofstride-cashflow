-- Idempotent Tally Receipt/Payment identity for cashflow transactions.
BEGIN;

ALTER TABLE public.cashflow_transactions ADD COLUMN IF NOT EXISTS tally_voucher_number TEXT;
ALTER TABLE public.cashflow_transactions ADD COLUMN IF NOT EXISTS tally_remote_id TEXT;

UPDATE public.cashflow_transactions
SET tally_voucher_number = NULLIF(reference_no, '')
WHERE payment_mode = 'tally'
    AND tally_voucher_number IS NULL
    AND NULLIF(reference_no, '') IS NOT NULL;

WITH ranked AS (
        SELECT id, row_number() OVER (
                PARTITION BY company_id, tally_voucher_number, invoice_id, bill_id
                ORDER BY created_at, id
        ) AS duplicate_rank
        FROM public.cashflow_transactions
        WHERE payment_mode = 'tally' AND tally_voucher_number IS NOT NULL
)
DELETE FROM public.cashflow_transactions transactions
USING ranked
WHERE transactions.id = ranked.id AND ranked.duplicate_rank > 1;

-- Keep one payment allocation per Tally voucher and linked document. The
-- document component permits one receipt voucher to settle multiple bills.
DROP INDEX IF EXISTS cashflow_tally_payment_remote_key;
DROP INDEX IF EXISTS cashflow_tally_payment_voucher_key;

CREATE UNIQUE INDEX IF NOT EXISTS cashflow_tally_payment_remote_invoice_key
    ON public.cashflow_transactions(company_id, tally_remote_id, invoice_id)
    WHERE payment_mode = 'tally' AND tally_remote_id IS NOT NULL AND invoice_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS cashflow_tally_payment_remote_bill_key
    ON public.cashflow_transactions(company_id, tally_remote_id, bill_id)
    WHERE payment_mode = 'tally' AND tally_remote_id IS NOT NULL AND bill_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS cashflow_tally_payment_voucher_invoice_key
    ON public.cashflow_transactions(company_id, tally_voucher_number, invoice_id)
    WHERE payment_mode = 'tally' AND tally_voucher_number IS NOT NULL AND invoice_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS cashflow_tally_payment_voucher_bill_key
    ON public.cashflow_transactions(company_id, tally_voucher_number, bill_id)
    WHERE payment_mode = 'tally' AND tally_voucher_number IS NOT NULL AND bill_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS cashflow_tally_payment_remote_unlinked_key
    ON public.cashflow_transactions(company_id, tally_remote_id)
    WHERE payment_mode = 'tally' AND tally_remote_id IS NOT NULL AND invoice_id IS NULL AND bill_id IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS cashflow_tally_payment_voucher_unlinked_key
    ON public.cashflow_transactions(company_id, tally_voucher_number)
    WHERE payment_mode = 'tally' AND tally_voucher_number IS NOT NULL AND invoice_id IS NULL AND bill_id IS NULL;

COMMIT;