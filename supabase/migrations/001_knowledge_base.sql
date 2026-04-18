-- ============================================================
-- Knowledge Base RAG — Schema
-- BIM Consultivo | Agente Telegram com RAG sobre PDFs e Notion
-- ============================================================

-- 1. Habilitar extensão pgvector
create extension if not exists vector;

-- 2. Tabela de fontes de conhecimento
create table if not exists knowledge_sources (
  id          uuid primary key default gen_random_uuid(),
  name        text not null,
  type        text not null check (type in ('pdf', 'notion', 'manual')),
  filename    text,
  description text,
  version     text,
  created_at  timestamptz default now()
);

-- 3. Tabela de chunks com embeddings vetoriais
create table if not exists knowledge_chunks (
  id          uuid primary key default gen_random_uuid(),
  source_id   uuid references knowledge_sources(id) on delete cascade,
  content     text not null,
  embedding   vector(1024),
  chunk_index int,
  chunk_type  text default 'text' check (chunk_type in ('text', 'table', 'image_description', 'heading')),
  page_number int,
  section     text,
  image_path  text,
  metadata    jsonb default '{}'
);

-- 4. Índice IVFFlat para busca por similaridade cosseno
create index if not exists knowledge_chunks_embedding_idx
  on knowledge_chunks
  using ivfflat (embedding vector_cosine_ops)
  with (lists = 100);

-- 5. Função RPC de busca semântica
create or replace function search_chunks(
  query_embedding vector(1024),
  match_count      int default 5,
  min_similarity   float default 0.70
)
returns table (
  id          uuid,
  content     text,
  chunk_type  text,
  section     text,
  source_name text,
  image_path  text,
  similarity  float
)
language sql stable as $$
  select
    kc.id,
    kc.content,
    kc.chunk_type,
    kc.section,
    ks.name as source_name,
    kc.image_path,
    1 - (kc.embedding <=> query_embedding) as similarity
  from knowledge_chunks kc
  join knowledge_sources ks on ks.id = kc.source_id
  where 1 - (kc.embedding <=> query_embedding) > min_similarity
  order by kc.embedding <=> query_embedding
  limit match_count;
$$;

-- 6. Permissões para service role (usado pelo backend)
grant all on knowledge_sources to service_role;
grant all on knowledge_chunks to service_role;
grant execute on function search_chunks to service_role;

-- 7. RLS — desabilitado para acesso via service_role (backend controlado)
alter table knowledge_sources disable row level security;
alter table knowledge_chunks disable row level security;
