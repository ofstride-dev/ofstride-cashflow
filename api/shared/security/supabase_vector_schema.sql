-- ============================================================================
-- OfStride Retrieval: Supabase Vector Schema
-- Run this in Supabase SQL Editor when migrating vector storage from Qdrant.
-- ============================================================================

create extension if not exists vector;

create table if not exists public.rag_documents (
    id uuid primary key default gen_random_uuid(),
    collection text not null,
    page_content text not null,
    metadata jsonb not null default '{}'::jsonb,
    embedding vector(1536) not null,
    created_at timestamptz not null default now()
);

-- Ensure existing tables created with unbounded vector type are normalized.
alter table public.rag_documents
    alter column embedding type vector(1536)
    using embedding::vector(1536);

create index if not exists idx_rag_documents_collection
    on public.rag_documents(collection);

create index if not exists idx_rag_documents_metadata_gin
    on public.rag_documents using gin(metadata);

-- NOTE: Tune lists based on data size. Start with 100 for small-medium datasets.
create index if not exists idx_rag_documents_embedding_ivfflat
    on public.rag_documents
    using ivfflat (embedding vector_cosine_ops)
    with (lists = 100);

create or replace function public.match_rag_documents(
    query_embedding vector(1536),
    match_count integer default 5,
    match_threshold float default 0.4,
    match_collection text default null,
    metadata_filter jsonb default '{}'::jsonb
)
returns table (
    id uuid,
    page_content text,
    metadata jsonb,
    score float
)
language sql
stable
as $$
    select
        d.id,
        d.page_content,
        d.metadata,
        1 - (d.embedding <=> query_embedding) as score
    from public.rag_documents d
    where (match_collection is null or d.collection = match_collection)
      and (metadata_filter = '{}'::jsonb or d.metadata @> metadata_filter)
      and (1 - (d.embedding <=> query_embedding)) >= match_threshold
    order by d.embedding <=> query_embedding
    limit greatest(match_count, 1);
$$;
