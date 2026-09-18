-- Fast tenant-scoped duplicate keys for manually uploaded and imported documents.
BEGIN;

UPDATE public.cashflow_bills
SET normalized_bill_number = lower(regexp_replace(trim(bill_number), '[^a-zA-Z0-9]', '', 'g'))
WHERE normalized_bill_number IS NULL AND NULLIF(trim(bill_number), '') IS NOT NULL;

UPDATE public.cashflow_invoices
SET normalized_invoice_number = lower(regexp_replace(trim(invoice_number), '[^a-zA-Z0-9]', '', 'g'))
WHERE normalized_invoice_number IS NULL AND NULLIF(trim(invoice_number), '') IS NOT NULL;

WITH ranked_bills AS (
    SELECT id, row_number() OVER (
        PARTITION BY company_id, vendor_id, normalized_bill_number
        ORDER BY created_at, id
    ) AS duplicate_rank
    FROM public.cashflow_bills
    WHERE normalized_bill_number IS NOT NULL AND normalized_bill_number <> ''
)
UPDATE public.cashflow_bills bills
SET dedup_override = TRUE
FROM ranked_bills ranked
WHERE bills.id = ranked.id AND ranked.duplicate_rank > 1;

WITH ranked_invoices AS (
    SELECT id, row_number() OVER (
        PARTITION BY company_id, customer_id, normalized_invoice_number
        ORDER BY created_at, id
    ) AS duplicate_rank
    FROM public.cashflow_invoices
    WHERE normalized_invoice_number IS NOT NULL AND normalized_invoice_number <> ''
)
UPDATE public.cashflow_invoices invoices
SET dedup_override = TRUE
FROM ranked_invoices ranked
WHERE invoices.id = ranked.id AND ranked.duplicate_rank > 1;

CREATE UNIQUE INDEX IF NOT EXISTS cashflow_bills_company_vendor_number_key
    ON public.cashflow_bills(company_id, vendor_id, normalized_bill_number)
    WHERE normalized_bill_number IS NOT NULL AND normalized_bill_number <> '' AND dedup_override = FALSE;

CREATE UNIQUE INDEX IF NOT EXISTS cashflow_bills_company_fingerprint_key
    ON public.cashflow_bills(company_id, dedup_fingerprint)
    WHERE dedup_fingerprint IS NOT NULL AND dedup_override = FALSE;

CREATE UNIQUE INDEX IF NOT EXISTS cashflow_invoices_company_customer_number_key
    ON public.cashflow_invoices(company_id, customer_id, normalized_invoice_number)
    WHERE normalized_invoice_number IS NOT NULL AND normalized_invoice_number <> '' AND dedup_override = FALSE;

CREATE UNIQUE INDEX IF NOT EXISTS cashflow_invoices_company_fingerprint_key
    ON public.cashflow_invoices(company_id, dedup_fingerprint)
    WHERE dedup_fingerprint IS NOT NULL AND dedup_override = FALSE;

CREATE INDEX IF NOT EXISTS cashflow_bills_dedup_lookup
    ON public.cashflow_bills(company_id, vendor_id, bill_date, amount);
CREATE INDEX IF NOT EXISTS cashflow_invoices_dedup_lookup
    ON public.cashflow_invoices(company_id, customer_id, invoice_date, amount);

COMMIT;