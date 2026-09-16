-- Structured invoice/bill details for dynamic line items and invoice-style exports.
-- Safe to run on existing tenants; existing rows receive empty JSON objects/arrays.

ALTER TABLE public.cashflow_invoices
    ADD COLUMN IF NOT EXISTS line_items JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE public.cashflow_invoices
    ADD COLUMN IF NOT EXISTS party_details JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE public.cashflow_bills
    ADD COLUMN IF NOT EXISTS line_items JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE public.cashflow_bills
    ADD COLUMN IF NOT EXISTS party_details JSONB NOT NULL DEFAULT '{}'::jsonb;
