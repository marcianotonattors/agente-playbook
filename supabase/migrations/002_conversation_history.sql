-- Histórico de conversa persistente por chat_id

create table if not exists conversation_history (
  id         uuid primary key default gen_random_uuid(),
  chat_id    text not null,
  role       text not null check (role in ('user', 'assistant')),
  content    text not null,
  created_at timestamptz default now()
);

create index if not exists conversation_history_chat_idx
  on conversation_history (chat_id, created_at desc);

grant all on conversation_history to service_role;
alter table conversation_history disable row level security;
