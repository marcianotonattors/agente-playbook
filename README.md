# Agente Playbook — Knowledge Base RAG

Agente de Telegram para o Playbook da Coordenação BIM com RAG (Retrieval-Augmented Generation) sobre PDFs e Notion.

**Stack:** Supabase + pgvector · Vercel · GitHub Actions · Claude API · Voyage AI Embeddings

## Estrutura do Repositório

```
.
├── knowledge/
│   ├── pdfs/              # PDFs pequenos (< 25MB) para ingestão via push
│   ├── notion-exports/    # Exports manuais do Notion (opcional)
│   └── processed/         # Chunks JSON gerados (gitignored)
├── ingest/
│   ├── process_pdf.py     # Ingestão de PDFs (local ou Supabase Storage)
│   ├── process_notion.py  # Ingestão do Notion (página ou database)
│   ├── embeddings.py      # Geração de embeddings via Voyage AI e carga no Supabase
│   └── requirements.txt
├── .github/workflows/
│   ├── ingest-pdf.yml     # Trigger automático (push) ou manual (Supabase Storage)
│   └── ingest-notion.yml  # Schedule semanal (segunda 8h UTC) + disparo manual
├── api/functions/
│   └── telegram-webhook.js # Vercel Function do agente
├── supabase/migrations/
│   └── 001_knowledge_base.sql # Schema completo do banco (vector 1024 dims)
├── docs/
│   ├── architecture.md    # Decisões de design
│   └── sources.md         # Registro de documentos ingeridos
└── vercel.json
```

## Setup

### 1. Banco de Dados (Supabase)

Execute `supabase/migrations/001_knowledge_base.sql` no SQL Editor do Supabase.

Depois adicione a constraint de unicidade:
```sql
ALTER TABLE knowledge_sources ADD CONSTRAINT knowledge_sources_name_key UNIQUE (name);
```

### 2. Supabase Storage

Crie um bucket privado chamado `pdfs` em **Storage** no painel do Supabase. Usado para PDFs maiores que 25MB.

### 3. Variáveis de Ambiente

**Vercel:**

| Variável | Descrição |
|----------|-----------|
| `ANTHROPIC_API_KEY` | Claude API |
| `VOYAGE_API_KEY` | Embeddings Voyage AI |
| `SUPABASE_URL` | URL do projeto Supabase |
| `SUPABASE_SERVICE_KEY` | Chave secret do Supabase |
| `TELEGRAM_BOT_TOKEN` | Token do bot Telegram |
| `TELEGRAM_WEBHOOK_SECRET` | Secret para validar requests do Telegram |

**GitHub Secrets:**

| Variável | Descrição |
|----------|-----------|
| `ANTHROPIC_API_KEY` | Claude API (usado no ingest de PDFs) |
| `VOYAGE_API_KEY` | Embeddings Voyage AI |
| `SUPABASE_URL` | URL do projeto Supabase |
| `SUPABASE_SERVICE_KEY` | Chave secret do Supabase |
| `NOTION_TOKEN` | Token de integração Notion |
| `NOTION_DATABASE_ID` | ID da página raiz do Playbook no Notion |

### 4. Webhook do Telegram

Registre o webhook com secret token:

```
https://api.telegram.org/botSEU_TOKEN/setWebhook?url=https://agente-playbook-rho.vercel.app/api/telegram&secret_token=SEU_WEBHOOK_SECRET
```

### 5. Ingestão do Notion

No GitHub → Actions → **Ingest Notion** → Run workflow.

Roda automaticamente toda segunda-feira às 8h UTC.

### 6. Ingestão de PDFs

**PDFs pequenos (< 25MB):** faça upload direto em `knowledge/pdfs/` pelo GitHub. O workflow dispara automaticamente.

**PDFs grandes (> 25MB):** faça upload no Supabase Storage (bucket `pdfs`), depois acesse GitHub → Actions → **Ingest PDF** → Run workflow → informe o nome do arquivo.

## Roadmap — Próximos 3 meses

### Maio
- [ ] Sistema de controle de acesso com códigos por aluno (Kiwify webhook + Supabase + email via Resend)
- [ ] Transcrição de áudio via Groq Whisper
- [ ] Histórico de conversa persistente no Supabase por chat_id

### Junho
- [ ] Dashboard de analytics (perguntas mais feitas, chunks mais acessados)
- [ ] Ingestão de URLs (scraping de documentação dos softwares: Revit, Navisworks, Solibri)

### Julho
- [ ] Notificações proativas (bot avisa aluno sobre novo conteúdo publicado)
- [ ] Avaliação de qualidade das respostas (aluno dá thumbs up/down)
- [ ] Exportar relatório mensal de uso por aluno

## Documentação

- [Arquitetura detalhada](docs/architecture.md)
- [Registro de fontes](docs/sources.md)
