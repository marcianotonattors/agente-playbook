# Agente Playbook — Knowledge Base RAG

Agente de Telegram para o Playbook da Coordenação BIM com RAG (Retrieval-Augmented Generation) sobre PDFs e Notion.

**Stack:** Supabase + pgvector · Vercel · GitHub Actions · Claude API · OpenAI Embeddings

## Estrutura do Repositório

```
.
├── knowledge/
│   ├── pdfs/              # PDFs originais das referências técnicas
│   ├── notion-exports/    # Exports manuais do Notion (opcional)
│   └── processed/         # Chunks JSON gerados (gitignored)
├── ingest/
│   ├── process_pdf.py     # Ingestão de PDFs
│   ├── process_notion.py  # Ingestão do Notion
│   ├── embeddings.py      # Geração de embeddings e carga no Supabase
│   └── requirements.txt
├── .github/workflows/
│   ├── ingest-pdf.yml     # Trigger automático ao adicionar PDF
│   └── ingest-notion.yml  # Schedule semanal + disparo manual
├── api/functions/
│   └── telegram-webhook.js # Vercel Function do agente
├── supabase/migrations/
│   └── 001_knowledge_base.sql # Schema completo do banco
├── docs/
│   ├── architecture.md    # Decisões de design
│   └── sources.md         # Registro de documentos ingeridos
└── vercel.json
```

## Setup

### 1. Banco de Dados (Supabase)

Execute o arquivo `supabase/migrations/001_knowledge_base.sql` no SQL Editor do Supabase para criar as tabelas e a função de busca.

### 2. Variáveis de Ambiente

Configure no Vercel e como GitHub Secrets:

| Variável | Onde |
|----------|------|
| `ANTHROPIC_API_KEY` | Vercel + GitHub Secrets |
| `OPENAI_API_KEY` | Vercel + GitHub Secrets |
| `SUPABASE_URL` | Vercel + GitHub Secrets |
| `SUPABASE_SERVICE_KEY` | Vercel + GitHub Secrets |
| `TELEGRAM_BOT_TOKEN` | Vercel |
| `NOTION_TOKEN` | GitHub Secrets |
| `NOTION_DATABASE_ID` | GitHub Secrets |

### 3. Ingestão Manual de PDFs

```bash
cd ingest
pip install -r requirements.txt

python process_pdf.py \
  --file ../knowledge/pdfs/iso-19650-2-pt.pdf \
  --name "ISO 19650-2 PT-BR" \
  --description "Organização e digitalização de informações sobre edificações" \
  --version "2021"
```

### 4. Ingestão do Notion

```bash
python ingest/process_notion.py \
  --database-id SEU_DATABASE_ID \
  --name "Playbook da Coordenação BIM"
```

### 5. Adicionar PDFs pelo GitHub (automático)

1. Acesse o repositório no GitHub
2. Arraste o PDF para `knowledge/pdfs/`
3. Faça commit
4. O GitHub Actions ingere automaticamente

## Webhook do Telegram

Configure o webhook do bot para apontar para:

```
https://seu-projeto.vercel.app/api/telegram
```

## Documentação

- [Arquitetura detalhada](docs/architecture.md)
- [Registro de fontes](docs/sources.md)
