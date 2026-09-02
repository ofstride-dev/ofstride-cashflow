-- Durable outbound-email deduplication and delivery state.
BEGIN;

CREATE TABLE IF NOT EXISTS public.email_deliveries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID REFERENCES public.companies(id) ON DELETE CASCADE,
    operation TEXT NOT NULL CHECK (operation = 'invite'),
    idempotency_key TEXT NOT NULL UNIQUE,
    recipient_addresses JSONB NOT NULL DEFAULT '[]'::jsonb,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'sending', 'sent', 'failed', 'unknown')),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    locked_until TIMESTAMPTZ,
    provider_message_id TEXT,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS email_deliveries_claim_idx
    ON public.email_deliveries(status, locked_until, created_at);
CREATE INDEX IF NOT EXISTS email_deliveries_company_idx
    ON public.email_deliveries(company_id, created_at DESC);

CREATE OR REPLACE FUNCTION public.set_email_delivery_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS email_deliveries_updated_at ON public.email_deliveries;
CREATE TRIGGER email_deliveries_updated_at
    BEFORE UPDATE ON public.email_deliveries
    FOR EACH ROW EXECUTE FUNCTION public.set_email_delivery_updated_at();

ALTER TABLE public.email_deliveries ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.email_deliveries FROM PUBLIC;

CREATE OR REPLACE FUNCTION public.claim_email_delivery(p_idempotency_key TEXT)
RETURNS TABLE (id UUID, status TEXT, payload JSONB) AS $$
BEGIN
    RETURN QUERY
    UPDATE public.email_deliveries AS d
    SET status = 'sending', attempt_count = d.attempt_count + 1,
        locked_until = now() + interval '5 minutes', updated_at = now()
    WHERE d.idempotency_key = trim(p_idempotency_key)
      AND (d.status IN ('pending', 'failed', 'unknown') OR (d.status = 'sending' AND d.locked_until < now()))
    RETURNING d.id, d.status, d.payload;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path TO 'public';

REVOKE ALL ON FUNCTION public.claim_email_delivery(TEXT) FROM PUBLIC;
COMMIT;