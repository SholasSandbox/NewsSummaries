-- NewsSummaries – Supabase schema
-- Run this once against your Supabase project:
--   psql $DATABASE_URL -f supabase/schema.sql
-- Or paste into the Supabase SQL Editor.

-- ── Extensions ────────────────────────────────────────────────────────────

-- pgvector enables storing and querying float vector embeddings.
create extension if not exists vector;

-- ── news_vectors ──────────────────────────────────────────────────────────
-- One row per scraped news article.
-- url_hash (SHA-256 prefix) is the deduplication key checked on every ingest.

create table if not exists news_vectors (
  id               uuid        default gen_random_uuid() primary key,
  url_hash         text        not null,
  url              text        not null,
  title            text        not null default '',
  content_markdown text        not null default '',
  -- text-embedding-3-small produces 1536-dimensional vectors
  embedding        vector(1536),
  created_at       timestamptz not null default now()
);

-- Fast deduplication lookups
create unique index if not exists news_vectors_url_hash_idx
  on news_vectors (url_hash);

-- Approximate nearest-neighbour search (cosine similarity)
create index if not exists news_vectors_embedding_idx
  on news_vectors using ivfflat (embedding vector_cosine_ops)
  with (lists = 100);

-- ── unified_summaries ─────────────────────────────────────────────────────
-- One row per distillation run (one Claude call = one row).

create table if not exists unified_summaries (
  id            uuid        default gen_random_uuid() primary key,
  summary       text        not null,
  source_urls   text[]      not null default '{}',
  article_count integer     not null default 0,
  embedding     vector(1536),
  created_at    timestamptz not null default now()
);

create index if not exists unified_summaries_embedding_idx
  on unified_summaries using ivfflat (embedding vector_cosine_ops)
  with (lists = 10);

-- ── Row-Level Security ────────────────────────────────────────────────────
-- The service-role key used by the Next.js app bypasses RLS.
-- If you expose these tables through the anon key, add appropriate policies.

alter table news_vectors     enable row level security;
alter table unified_summaries enable row level security;
