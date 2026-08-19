-- OfStride Cashflow Phase 9: invite lifecycle and isolation hardening
-- Run after cashflow_phase8_memberships.sql and the expenses/company invite
-- schema. This replaces the invite RPCs without changing frontend routes.

BEGIN;

CREATE OR REPLACE FUNCTION public.list_company_invites()
RETURNS TABLE (
  id uuid,
  email text,
  role text,
  status text,
  invite_token text,
  expires_at timestamptz,
  created_at timestamptz
) AS $$
BEGIN
  IF auth.uid() IS NULL THEN
    RAISE EXCEPTION 'Authentication required';
  END IF;

  IF lower(coalesce(public.my_role(), '')) NOT IN ('owner','admin','finance') THEN
    RAISE EXCEPTION 'Only company admins can view invites';
  END IF;

  -- Expired invites must not remain apparently pending in the admin UI.
  UPDATE public.company_invites
  SET status = 'expired'
  WHERE company_id = public.my_company_id()
    AND status = 'pending'
    AND expires_at <= now();

  RETURN QUERY
    SELECT ci.id, ci.email, (ci.role)::text, ci.status,
           ci.invite_token, ci.expires_at, ci.created_at
    FROM public.company_invites ci
    WHERE ci.company_id = public.my_company_id()
    ORDER BY ci.created_at DESC;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path TO 'public';

CREATE OR REPLACE FUNCTION public.accept_company_invite(
  p_invite_token text,
  p_full_name text DEFAULT NULL
) RETURNS jsonb AS $$
DECLARE
  v_user_id uuid := auth.uid();
  v_email text := lower(coalesce(auth.jwt()->>'email', ''));
  v_invite public.company_invites%rowtype;
  v_existing_company uuid;
BEGIN
  IF v_user_id IS NULL THEN
    RAISE EXCEPTION 'Authentication required';
  END IF;

  IF v_email = '' THEN
    RAISE EXCEPTION 'Authenticated email is required';
  END IF;

  -- Row lock makes acceptance one-time even when two requests use the token
  -- concurrently. The status check happens while the lock is held.
  SELECT * INTO v_invite
  FROM public.company_invites
  WHERE invite_token = trim(coalesce(p_invite_token, ''))
  FOR UPDATE;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'Invite not found';
  END IF;

  IF v_invite.status <> 'pending' THEN
    RAISE EXCEPTION 'Invite is no longer active';
  END IF;

  IF v_invite.expires_at <= now() THEN
    UPDATE public.company_invites
    SET status = 'expired'
    WHERE id = v_invite.id;
    RAISE EXCEPTION 'Invite has expired';
  END IF;

  IF lower(v_invite.email) <> v_email THEN
    RAISE EXCEPTION 'Invite email does not match the signed-in account';
  END IF;

  SELECT p.company_id INTO v_existing_company
  FROM public.profiles p
  WHERE p.id = v_user_id
  FOR UPDATE;

  -- Never move an existing user between companies as a side effect of invite
  -- acceptance. Company switching requires the explicit membership flow.
  IF v_existing_company IS NOT NULL AND v_existing_company <> v_invite.company_id THEN
    RAISE EXCEPTION 'User already belongs to another workspace';
  END IF;

  INSERT INTO public.profiles (id, full_name, email, role, company_id)
  VALUES (
    v_user_id,
    coalesce(nullif(trim(p_full_name), ''), 'Team Member'),
    v_email,
    (v_invite.role)::text,
    v_invite.company_id
  )
  ON CONFLICT (id) DO UPDATE
    SET full_name = coalesce(nullif(trim(p_full_name), ''), public.profiles.full_name),
        email = v_email,
        -- The server-verified invite role is authoritative for this
        -- workspace. The old condition preserved a stale admin role on a
        -- profile created before invite acceptance, causing employee invites
        -- to receive admin privileges despite the membership being employee.
        role = excluded.role,
        company_id = coalesce(public.profiles.company_id, excluded.company_id);

  -- Phase 8 membership state must be updated atomically with invite acceptance.
  INSERT INTO public.company_memberships (user_id, company_id, role, status)
  VALUES (v_user_id, v_invite.company_id, (v_invite.role)::text, 'active')
  ON CONFLICT (user_id, company_id) DO UPDATE
    SET role = excluded.role,
        status = 'active',
        updated_at = now();

  UPDATE public.company_invites
  SET status = 'accepted',
      accepted_at = now(),
      accepted_by = v_user_id
  WHERE id = v_invite.id
    AND status = 'pending';

  IF NOT FOUND THEN
    RAISE EXCEPTION 'Invite is no longer active';
  END IF;

  RETURN jsonb_build_object(
    'company_id', v_invite.company_id,
    'role', (v_invite.role)::text,
    'accepted', true
  );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path TO 'public';

REVOKE ALL ON FUNCTION public.list_company_invites() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.accept_company_invite(text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.list_company_invites() TO authenticated;
GRANT EXECUTE ON FUNCTION public.accept_company_invite(text, text) TO authenticated;

CREATE OR REPLACE FUNCTION public.revoke_company_invite(p_invite_token text)
RETURNS jsonb AS $$
DECLARE
  v_company_id uuid := public.my_company_id();
  v_role text := lower(coalesce(public.my_role(), ''));
  v_count integer;
BEGIN
  IF auth.uid() IS NULL THEN
    RAISE EXCEPTION 'Authentication required';
  END IF;
  IF v_role NOT IN ('owner','admin','finance') THEN
    RAISE EXCEPTION 'Only company admins can revoke invites';
  END IF;

  UPDATE public.company_invites
  SET status = 'revoked'
  WHERE invite_token = trim(coalesce(p_invite_token, ''))
    AND company_id = v_company_id
    AND status = 'pending';
  GET DIAGNOSTICS v_count = ROW_COUNT;

  IF v_count = 0 THEN
    RAISE EXCEPTION 'Pending invite not found for this workspace';
  END IF;

  RETURN jsonb_build_object('revoked', true);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path TO 'public';

REVOKE ALL ON FUNCTION public.revoke_company_invite(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.revoke_company_invite(text) TO authenticated;

COMMIT;