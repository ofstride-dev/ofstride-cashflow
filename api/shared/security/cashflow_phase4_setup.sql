-- ============================================================================
-- OfStride Cashflow — Phase 4 explicit company setup state
--
-- Run this entire file once in the Supabase SQL Editor.
-- Safe to re-run. Existing companies default to setup incomplete; newly
-- created companies are marked complete only after RPC validation succeeds.
-- ============================================================================

BEGIN;

-- 1. Explicit setup state for every company.
ALTER TABLE public.companies
  ADD COLUMN IF NOT EXISTS is_setup_complete boolean
  NOT NULL DEFAULT false;

-- 2. The return shape changed, so drop the old no-argument RPC before
-- recreating it. This is required by PostgreSQL for RETURNS TABLE changes.
DROP FUNCTION IF EXISTS public.get_my_profile();

CREATE FUNCTION public.get_my_profile()
RETURNS TABLE (
  id uuid,
  full_name text,
  email text,
  role text,
  company_id uuid,
  company_name text,
  company_slug text,
  is_demo boolean,
  is_setup_complete boolean,
  created_at timestamptz,
  updated_at timestamptz
)
LANGUAGE plpgsql
SECURITY DEFINER
STABLE
SET search_path TO 'public'
AS $$
BEGIN
  RETURN QUERY
    SELECT
      p.id,
      p.full_name,
      COALESCE(p.email, auth.jwt()->>'email') AS email,
      p.role::text,
      p.company_id,
      c.name,
      c.slug,
      COALESCE(c.is_demo, false),
      COALESCE(c.is_setup_complete, false),
      p.created_at,
      p.updated_at
    FROM public.profiles p
    LEFT JOIN public.companies c
      ON c.id = p.company_id
    WHERE p.id = auth.uid();
END;
$$;

-- 3. Secure company bootstrap/setup RPC.
-- The owner is always derived from auth.uid(); no client tenant or owner ID
-- is accepted. Required fields are validated before the company is inserted.
CREATE OR REPLACE FUNCTION public.bootstrap_company_owner(
  p_company_name text,
  p_full_name text DEFAULT NULL,
  p_is_demo boolean DEFAULT false,
  p_company_email text DEFAULT NULL
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public'
AS $$
DECLARE
  v_user_id uuid := auth.uid();
  v_company_id uuid;
  v_existing_company uuid;
  v_name text := NULLIF(trim(p_company_name), '');
  v_full_name text := NULLIF(trim(p_full_name), '');
  v_email text := lower(
    COALESCE(
      NULLIF(trim(p_company_email), ''),
      auth.jwt()->>'email',
      ''
    )
  );
  v_slug text;
BEGIN
  IF v_user_id IS NULL THEN
    RAISE EXCEPTION 'Authentication required';
  END IF;

  IF v_name IS NULL THEN
    RAISE EXCEPTION 'Company name is required';
  END IF;

  IF v_email IS NULL OR v_email = '' THEN
    RAISE EXCEPTION 'Company email is required';
  END IF;

  IF v_full_name IS NULL THEN
    RAISE EXCEPTION 'Full name is required';
  END IF;

  SELECT p.company_id
    INTO v_existing_company
    FROM public.profiles p
   WHERE p.id = v_user_id;

  IF v_existing_company IS NOT NULL THEN
    RETURN jsonb_build_object(
      'company_id', v_existing_company,
      'already_initialized', true
    );
  END IF;

  v_slug := lower(regexp_replace(v_name, '[^a-z0-9]+', '-', 'g'));
  v_slug := trim(both '-' FROM v_slug);

  IF v_slug = '' THEN
    v_slug := substr(replace(v_user_id::text, '-', ''), 1, 12);
  END IF;

  IF EXISTS (
    SELECT 1
      FROM public.companies
     WHERE slug = v_slug
  ) THEN
    v_slug := v_slug || '-' || substr(replace(v_user_id::text, '-', ''), 1, 6);
  END IF;

  INSERT INTO public.companies (
    name,
    email,
    slug,
    owner_user_id,
    is_demo,
    is_setup_complete
  )
  VALUES (
    v_name,
    v_email,
    v_slug,
    v_user_id,
    COALESCE(p_is_demo, false),
    true
  )
  RETURNING id INTO v_company_id;

  INSERT INTO public.profiles (
    id,
    full_name,
    email,
    role,
    company_id
  )
  VALUES (
    v_user_id,
    v_full_name,
    v_email,
    'owner',
    v_company_id
  )
  ON CONFLICT (id) DO UPDATE
    SET full_name = EXCLUDED.full_name,
        email = EXCLUDED.email,
        role = 'owner',
        company_id = v_company_id;

  RETURN jsonb_build_object(
    'company_id', v_company_id,
    'company_name', v_name,
    'company_slug', v_slug,
    'role', 'owner',
    'is_setup_complete', true
  );
END;
$$;

-- 4. Explicit RPC permissions for authenticated frontend users.
GRANT EXECUTE ON FUNCTION public.get_my_profile()
  TO authenticated;

GRANT EXECUTE ON FUNCTION public.bootstrap_company_owner(
  text,
  text,
  boolean,
  text
)
  TO authenticated;

COMMIT;