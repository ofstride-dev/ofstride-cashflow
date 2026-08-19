-- ============================================================================
-- OfStride Careers: Supabase Schema & Row-Level Security
-- Run this ENTIRE script in the Supabase SQL Editor (one-time setup)
-- ============================================================================
-- NOTE: Run this as a single batch. Do NOT run line by line.
-- Order matters: companies must exist before user_roles references it.
-- ============================================================================

-- 1. Companies (for employer accounts) -- MUST be created first
CREATE TABLE IF NOT EXISTS public.companies (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    website TEXT,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. User Roles (links auth.users to application roles)
--    References companies.id from step 1, so companies must exist first
CREATE TABLE IF NOT EXISTS public.user_roles (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('admin', 'employer', 'jobseeker')),
    company_id UUID REFERENCES public.companies(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, role)
);

-- 3. Enable Row-Level Security
ALTER TABLE public.user_roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.companies ENABLE ROW LEVEL SECURITY;

-- 4. RLS Policies for user_roles
CREATE POLICY "Users can read own roles"
    ON public.user_roles
    FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Admins can manage all roles"
    ON public.user_roles
    USING (
        EXISTS (
            SELECT 1 FROM public.user_roles
            WHERE user_id = auth.uid() AND role = 'admin'
        )
    );

-- 5. RLS Policies for companies
CREATE POLICY "Anyone can read companies"
    ON public.companies
    FOR SELECT
    USING (true);

CREATE POLICY "Admins can manage companies"
    ON public.companies
    USING (
        EXISTS (
            SELECT 1 FROM public.user_roles
            WHERE user_id = auth.uid() AND role = 'admin'
        )
    );

-- 6. Helper function: get current user's role
CREATE OR REPLACE FUNCTION public.get_user_role()
RETURNS TEXT
LANGUAGE SQL STABLE
AS $$
    SELECT role FROM public.user_roles WHERE user_id = auth.uid() LIMIT 1;
$$;

-- 7. Helper function: get current user's company_id
CREATE OR REPLACE FUNCTION public.get_user_company_id()
RETURNS UUID
LANGUAGE SQL STABLE
AS $$
    SELECT company_id FROM public.user_roles WHERE user_id = auth.uid() LIMIT 1;
$$;

-- 8. Trigger: auto-create jobseeker role on signup
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER SET search_path = public
AS $$
BEGIN
    INSERT INTO public.user_roles (user_id, role)
    VALUES (NEW.id, 'jobseeker')
    ON CONFLICT (user_id, role) DO NOTHING;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW
    EXECUTE FUNCTION public.handle_new_user();

-- ============================================================================
-- CAREERS TABLES (Jobs, Applications, Analysis, Admin Audit Log)
-- Run this section AFTER the auth/roles tables above.
-- ============================================================================

-- 9. Jobs (Job Descriptions posted by admin/employer)
CREATE TABLE IF NOT EXISTS public.careers_jobs (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    department TEXT,
    location TEXT,
    employment_type TEXT,
    jd_markdown TEXT,
    jd_raw_text TEXT NOT NULL,
    jd_blob_path TEXT,
    jd_blob_container TEXT,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'active', 'archived')),
    ai_assisted_version TEXT,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.careers_jobs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Admins and employers can manage jobs"
    ON public.careers_jobs
    FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM public.user_roles
            WHERE user_id = auth.uid() AND role IN ('admin', 'employer')
        )
    );

CREATE POLICY "Anyone can read active jobs"
    ON public.careers_jobs
    FOR SELECT
    USING (status = 'active');

-- 10. Applications (Jobseeker applications against a specific job)
CREATE TABLE IF NOT EXISTS public.careers_applications (
    id TEXT PRIMARY KEY,
    reference_id TEXT UNIQUE,
    job_id TEXT NOT NULL REFERENCES public.careers_jobs(id) ON DELETE CASCADE,
    full_name TEXT NOT NULL,
    email TEXT NOT NULL,
    phone TEXT,
    linkedin_url TEXT,
    years_experience REAL,
    cover_note TEXT,
    consent_accepted INTEGER NOT NULL DEFAULT 0,
    resume_blob_path TEXT NOT NULL,
    resume_original_name TEXT NOT NULL,
    resume_content_type TEXT NOT NULL,
    resume_size_bytes INTEGER NOT NULL,
    submission_status TEXT NOT NULL DEFAULT 'submitted'
        CHECK (submission_status IN ('draft_upload_pending', 'submitted', 'upload_failed', 'under_review', 'shortlisted', 'rejected')),
    confirmation_email_sent INTEGER NOT NULL DEFAULT 0,
    applicant_email_sent_at TIMESTAMPTZ,
    hr_email_sent INTEGER NOT NULL DEFAULT 0,
    hr_email_sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    submitted_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.careers_applications ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Admins and employers can manage applications"
    ON public.careers_applications
    FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM public.user_roles
            WHERE user_id = auth.uid() AND role IN ('admin', 'employer')
        )
    );

CREATE POLICY "Jobseekers can insert own applications"
    ON public.careers_applications
    FOR INSERT
    WITH CHECK (true);

-- 11. Application Analysis (AI scoring and review results)
CREATE TABLE IF NOT EXISTS public.careers_application_analysis (
    id TEXT PRIMARY KEY,
    application_id TEXT NOT NULL UNIQUE REFERENCES public.careers_applications(id) ON DELETE CASCADE,
    analysis_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (analysis_status IN ('not_started', 'pending', 'completed')),
    match_score REAL,
    matched_skills_json TEXT,
    missing_skills_json TEXT,
    strengths_summary TEXT,
    gaps_summary TEXT,
    recommendation TEXT,
    analyzed_by TEXT,
    analyzed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.careers_application_analysis ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Admins and employers can manage analysis"
    ON public.careers_application_analysis
    FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM public.user_roles
            WHERE user_id = auth.uid() AND role IN ('admin', 'employer')
        )
    );

-- 12. Admin Action Log (Audit trail for all admin actions)
CREATE TABLE IF NOT EXISTS public.careers_admin_action_log (
    id TEXT PRIMARY KEY,
    admin_user_id TEXT NOT NULL,
    action_type TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    action_detail TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.careers_admin_action_log ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Admins can manage action log"
    ON public.careers_admin_action_log
    FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM public.user_roles
            WHERE user_id = auth.uid() AND role = 'admin'
        )
    );

-- 13. Indexes for performance
CREATE INDEX IF NOT EXISTS idx_careers_applications_job_id
    ON public.careers_applications(job_id);

CREATE INDEX IF NOT EXISTS idx_careers_applications_email_job_created
    ON public.careers_applications(email, job_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_careers_applications_status
    ON public.careers_applications(submission_status);

CREATE INDEX IF NOT EXISTS idx_careers_application_analysis_application_id
    ON public.careers_application_analysis(application_id);

CREATE INDEX IF NOT EXISTS idx_careers_admin_action_log_entity
    ON public.careers_admin_action_log(entity_type, entity_id);

-- 14. Auto-update updated_at trigger
CREATE OR REPLACE FUNCTION public.update_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

CREATE OR REPLACE TRIGGER careers_jobs_updated_at
    BEFORE UPDATE ON public.careers_jobs
    FOR EACH ROW
    EXECUTE FUNCTION public.update_updated_at();

CREATE OR REPLACE TRIGGER careers_applications_updated_at
    BEFORE UPDATE ON public.careers_applications
    FOR EACH ROW
    EXECUTE FUNCTION public.update_updated_at();

CREATE OR REPLACE TRIGGER careers_application_analysis_updated_at
    BEFORE UPDATE ON public.careers_application_analysis
    FOR EACH ROW
    EXECUTE FUNCTION public.update_updated_at();
