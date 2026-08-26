-- Scheduled weekly report opt-in and idempotency state.
CREATE TABLE IF NOT EXISTS public.company_report_settings (
    company_id UUID PRIMARY KEY REFERENCES public.companies(id) ON DELETE CASCADE,
    weekly_reports_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    last_weekly_period_end DATE,
    updated_by UUID REFERENCES auth.users(id),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS company_report_settings_enabled_idx
    ON public.company_report_settings(weekly_reports_enabled);