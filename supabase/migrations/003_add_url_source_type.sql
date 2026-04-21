-- ============================================================
-- Migration 003: Adiciona tipo 'url' em knowledge_sources
-- ============================================================

-- Recria o check constraint incluindo o novo tipo 'url'
alter table knowledge_sources
  drop constraint if exists knowledge_sources_type_check;

alter table knowledge_sources
  add constraint knowledge_sources_type_check
  check (type in ('pdf', 'notion', 'manual', 'url'));
