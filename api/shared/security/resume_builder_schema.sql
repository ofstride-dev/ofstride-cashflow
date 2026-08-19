-- Resume Builder — Supabase schema (Phase 1)
--
-- Provisioned once per Supabase project. The SQLite fallback store
-- (persistence/resume_builder_store.py) auto-creates its own tables, so this
-- file only documents/creates the PostgREST-backed tables used when
-- SUPABASE_URL + SUPABASE_SERVICE_KEY are configured.
--
-- JSONB columns hold the ResumeData / ATS payloads directly.

create table if not exists public.careers_resume_drafts (
    id               text primary key,
    created_by       text,
    title            text not null,
    resume_data     jsonb not null default '{}'::jsonb,
    source_filename  text,
    source_blob_path text,
    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now()
);

create table if not exists public.careers_resume_versions (
    id                text primary key,
    draft_id          text not null references public.careers_resume_drafts(id) on delete cascade,
    version_number    integer not null,
    jd_text           text,
    jd_keywords       jsonb default '{}'::jsonb,
    tailored_resume   jsonb not null default '{}'::jsonb,
    ats_score         jsonb default '{}'::jsonb,
    applied_changes   jsonb default '[]'::jsonb,
    skipped_changes   jsonb default '[]'::jsonb,
    strategy_notes    text default '',
    ai_used           boolean not null default false,
    ai_provider       text,
    ai_error          text,
    created_at        timestamptz not null default now()
);

create index if not exists ix_resume_versions_draft
    on public.careers_resume_versions(draft_id);

-- Updated-at trigger for the drafts table.
create or replace function public.touch_resume_draft_updated_at()
returns trigger as $$
begin
    new.updated_at = now();
    return new;
end;
$$ language plpgsql;

drop trigger if exists trg_resume_drafts_touch on public.careers_resume_drafts;
create trigger trg_resume_drafts_touch
    before update on public.careers_resume_drafts
    for each row execute function public.touch_resume_draft_updated_at();
