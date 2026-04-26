# Agente Playbook BIM — Contexto para Claude Code

## O que é este projeto

Bot do Telegram que responde perguntas dos alunos do **Playbook da Coordenação BIM** (curso de Marciano Tonatto) usando RAG — busca trechos relevantes na base de conhecimento antes de responder com Claude.

---

## Stack

| Camada | Tecnologia | Detalhe |
|--------|-----------|---------|
| Hospedagem | Vercel | Serverless function com timeout de 30s |
| Banco vetorial | Supabase + pgvector | Tabelas: `knowledge_sources`, `knowledge_chunks`, `conversation_history` |
| Embeddings | Voyage AI `voyage-3` | 1024 dimensões (migrado de OpenAI em abr/2026) |
| LLM | Anthropic `claude-sonnet-4-6` | Geração de respostas e visão em PDFs |
| CI/CD de ingestão | GitHub Actions | 5 workflows (pdf, notion, url, html, debug) |
| Interface | Telegram | Bot via webhook |
| Ingestão | Python 3.11 | pdfplumber, notion-client, BeautifulSoup4 |

---

## Estrutura de Diretórios

```
agente-playbook/
├── api/functions/
│   ├── telegram-webhook.js   # Vercel serverless — ponto de entrada do bot
│   └── package.json          # Dependências Node (ESM): @anthropic-ai/sdk, @supabase/supabase-js
├── ingest/                   # Pipeline de ingestão (Python)
│   ├── process_pdf.py        # Extrai texto/tabelas/imagens de PDFs
│   ├── process_notion.py     # Lê blocos da API Notion com paginação
│   ├── process_url.py        # Web crawler com BeautifulSoup (depth 0-2)
│   ├── process_html.py       # Parser de exports HTML/ZIP do Notion
│   ├── embeddings.py         # Voyage AI + upsert no Supabase (batch de 50)
│   ├── debug_blocks.py       # Debug de blocos Notion
│   ├── debug_search.py       # Debug de busca vetorial
│   └── requirements.txt      # Dependências Python
├── supabase/migrations/
│   ├── 001_knowledge_base.sql        # Schema pgvector + índice IVFFlat
│   ├── 002_conversation_history.sql  # Tabela de histórico persistente
│   └── 003_add_url_source_type.sql   # Adiciona tipo 'url' ao enum
├── .github/workflows/
│   ├── ingest-pdf.yml        # Trigger: push em knowledge/pdfs/ ou manual
│   ├── ingest-notion.yml     # Trigger: toda segunda 8h UTC ou manual
│   ├── ingest-url.yml        # Trigger: manual (parâmetros: url, name, depth)
│   ├── ingest-html.yml       # Trigger: push em knowledge/html/ ou manual
│   └── debug-search.yml      # Debug de busca vetorial
├── knowledge/
│   ├── pdfs/                 # PDFs < 25MB (versionados no Git)
│   ├── html/                 # Exports HTML do Notion
│   ├── notion-exports/       # Exports manuais do Notion
│   └── processed/            # Chunks gerados (gitignored)
├── docs/
│   ├── architecture.md       # Decisões de design detalhadas
│   └── sources.md            # Registro de fontes ingeridas
├── .claude/
│   └── settings.json         # MCP server do Notion para Claude Code
├── vercel.json               # Rota /api/telegram → telegram-webhook.js
└── CLAUDE.md                 # Este arquivo
```

---

## Arquitetura e Fluxo de Dados

### Ingestão (offline — GitHub Actions)

```
Fonte (PDF / Notion / URL / HTML)
    ↓  GitHub Actions workflow
Script Python (ingest/)
    ↓  pdfplumber / notion-client / BeautifulSoup
Chunks de 800 tokens com overlap de 100
    ↓  embeddings.py → Voyage AI voyage-3
Vetores 1024-dim
    ↓  upsert em lote (50 por batch)
Supabase: knowledge_sources + knowledge_chunks
```

### Consulta (online — Vercel serverless)

```
Usuário → Telegram → POST /api/telegram
    1. Valida X-Telegram-Bot-Api-Secret-Token
    2. Verifica rate limit (10 msgs/min por chat_id, in-memory)
    3. Limita input a 2.000 chars
    4. Gera embedding (Voyage AI voyage-3)
    5. Busca semântica no Supabase (cosine sim ≥ 0.3, top 10)
    6. Fallback: busca por keywords se resultado insuficiente
    7. Busca histórico de conversa (últimas 6 mensagens do Supabase)
    8. Monta system prompt com chunks de contexto
    9. Chama Claude (claude-sonnet-4-6, max_tokens=500)
   10. Salva mensagem + resposta em conversation_history
   11. Envia resposta ao Telegram (Markdown, ≤ 2000 chars)
```

---

## Arquivo Principal: `api/functions/telegram-webhook.js`

**Linguagem:** JavaScript ES Module (Node.js)

### Constantes de configuração (linha ~19)

```js
const RAG_MATCH_COUNT = 10;        // chunks retornados por busca
const RAG_MIN_SIMILARITY = 0.3;    // limiar de similaridade coseno
const MAX_MESSAGE_LENGTH = 2000;   // máximo de chars de input
const RATE_LIMIT_WINDOW_MS = 60_000;
const RATE_LIMIT_MAX_REQUESTS = 10;
const MAX_HISTORY_MESSAGES = 6;    // mensagens do histórico carregadas
```

### Fluxo interno de funções

- `handleWebhook(req, res)` — valida secret, despacha para handler
- `handleMessage(message)` — orquestra o fluxo RAG completo
- `searchKnowledge(embedding)` — busca semântica + fallback keyword no Supabase
- `callClaude(systemPrompt, history)` — chama a API Anthropic (max_tokens=500)
- `getHistory(chatId)` — busca últimas 6 msgs em `conversation_history`
- `saveHistory(chatId, userMsg, botReply)` — persiste conversa no Supabase
- `sendTelegramMessage(chatId, text)` — envia resposta com Markdown

### Rate limiting

Implementado **in-memory** por `chat_id` usando `Map`. Reseta a cada 60s. Não persiste entre re-deploys do Vercel.

### Histórico de conversa

**Persistido no Supabase** (tabela `conversation_history`). Armazena `chat_id`, `role` e `content`. As últimas `MAX_HISTORY_MESSAGES` são carregadas a cada request.

---

## Pipeline de Ingestão Python (`ingest/`)

### `embeddings.py` — funções centrais

- `generate_embedding(text)` — Voyage AI `voyage-3`, retry automático, delay de 1s entre chamadas
- `upsert_source(name, type, filename, description, version)` — cria/atualiza em `knowledge_sources`
- `delete_chunks_for_source(source_id)` — limpa chunks antes de re-ingerir
- `upsert_chunks(source_id, chunks)` — insere em lote de 50 com logging de progresso

### Estratégia de chunking (uniforme entre scripts)

- Tamanho: **800 tokens** (via tiktoken `cl100k_base`)
- Overlap: **100 tokens**
- Tipos de chunk: `text`, `heading`, `table`, `image_description`
- Tabelas: serializadas como Markdown

### `process_pdf.py` — casos especiais

- PDFs escaneados (sem texto extraível): fallback para **Claude Vision** (`claude-sonnet-4-6`)
- PDFs > 25MB: baixa do **Supabase Storage** (bucket `pdfs`) antes de processar
- Metadados: extrai título dos metadados do PDF automaticamente

### `process_notion.py`

- Blocos suportados: `paragraph`, `heading_1-3`, `bulleted/numbered_list_item`, `code`, `table`, `file`, `bookmark`, `image`
- Tabelas: buscadas via API com paginação de `table_row` blocks

### `process_url.py`

- Crawling com `requests` + `BeautifulSoup`
- `depth=0`: apenas a URL fornecida; `depth=1`: links diretos; `depth=2`: dois níveis
- Delay configurável entre requests (padrão 1.5s)
- Remove ruído: `nav`, `header`, `footer`, `sidebar`, scripts, ads

---

## Banco de Dados Supabase

### Tabelas

```sql
knowledge_sources (
  id UUID PRIMARY KEY,
  name TEXT UNIQUE,          -- identificador único da fonte
  type TEXT,                 -- 'pdf' | 'notion' | 'manual' | 'url'
  filename TEXT,
  description TEXT,
  version TEXT,
  created_at TIMESTAMPTZ
)

knowledge_chunks (
  id UUID PRIMARY KEY,
  source_id UUID REFERENCES knowledge_sources,
  content TEXT,
  embedding VECTOR(1024),    -- Voyage AI voyage-3
  chunk_index INT,
  chunk_type TEXT,           -- 'text' | 'table' | 'image_description' | 'heading'
  page_number INT,
  section TEXT,
  image_path TEXT,
  metadata JSONB
)
-- Índice: IVFFlat (lists=100) para similaridade coseno

conversation_history (
  id UUID PRIMARY KEY,
  chat_id BIGINT,
  role TEXT,                 -- 'user' | 'assistant'
  content TEXT,
  created_at TIMESTAMPTZ
)
-- Índice: (chat_id, created_at DESC)
```

### Função RPC `search_chunks`

```sql
search_chunks(
  query_embedding VECTOR(1024),
  match_count INT DEFAULT 5,
  min_similarity FLOAT DEFAULT 0.70
)
-- Retorna: id, content, chunk_type, section, source_name, image_path, similarity
```

> **Nota:** O valor padrão `0.70` na função SQL é sobrescrito pelo código JS que passa `0.3`.

---

## GitHub Actions Workflows

| Workflow | Trigger | Script | Timeout |
|---------|---------|--------|---------|
| `ingest-pdf.yml` | Push em `knowledge/pdfs/` ou manual | `process_pdf.py` | padrão |
| `ingest-notion.yml` | Segunda 8h UTC (schedule) ou manual | `process_notion.py` | padrão |
| `ingest-url.yml` | Manual (url, name, depth, max_pages, delay) | `process_url.py` | 90min |
| `ingest-html.yml` | Push em `knowledge/html/` ou manual | `process_html.py` | padrão |
| `debug-search.yml` | Manual | `debug_search.py` | padrão |

---

## Variáveis de Ambiente

**Vercel (runtime):**

| Variável | Uso |
|---------|-----|
| `ANTHROPIC_API_KEY` | Claude API (respostas + visão em PDFs) |
| `VOYAGE_API_KEY` | Voyage AI embeddings |
| `SUPABASE_URL` | URL do projeto Supabase |
| `SUPABASE_SERVICE_KEY` | Chave service role (admin) |
| `TELEGRAM_BOT_TOKEN` | Autenticação do bot |
| `TELEGRAM_WEBHOOK_SECRET` | Validação do header `X-Telegram-Bot-Api-Secret-Token` |

**GitHub Secrets (Actions):**

| Secret | Workflows que usam |
|--------|-------------------|
| `ANTHROPIC_API_KEY` | ingest-pdf (visão) |
| `VOYAGE_AI_KEY` | todos os workflows de ingestão |
| `SUPABASE_URL` | todos os workflows de ingestão |
| `SUPABASE_SERVICE_KEY` | todos os workflows de ingestão |
| `NOTION_TOKEN` | ingest-notion |
| `NOTION_DATABASE_ID` | ingest-notion (ID da página raiz) |

---

## URLs e Recursos

- **Vercel:** `https://agente-playbook-rho.vercel.app`
- **Webhook:** `https://agente-playbook-rho.vercel.app/api/telegram`
- **Branch de produção:** `claude/rag-knowledge-base-pipeline-dN4Ui`
- **Repositório:** `marcianotonattors/agente-playbook`

---

## Fontes de Conhecimento Ingeridas

| Fonte | Tipo | Chunks | Status |
|-------|------|--------|--------|
| Playbook da Coordenação BIM | Notion | 153 | Ativo — atualiza toda segunda 8h UTC |
| Coletânea BIM - Guia de Conceitos Gerais | PDF (Supabase Storage) | — | Ingerido abr/2026 |
| Coletânea BIM - Guia de Coordenação de Projetos | PDF (Supabase Storage) | — | Ingerido abr/2026 |
| Coletânea BIM - Guia de Gerenciamento de Projetos | PDF (Supabase Storage) | — | Ingerido abr/2026 |

---

## Como Adicionar Novas Fontes

**PDF < 25MB:** Commit em `knowledge/pdfs/` → workflow `ingest-pdf.yml` dispara automaticamente.

**PDF > 25MB:** Upload no Supabase Storage (bucket `pdfs`) → GitHub Actions → "Ingest PDF" → "Run workflow" → informar nome do arquivo no campo `supabase_filename`.

**URL:** GitHub Actions → "Ingest URL" → preencher `url`, `name`, `depth` (0-2), `max_pages`, `delay`.

**Notion:** Automático toda segunda 8h UTC, ou manual via "Ingest Notion".

**HTML/ZIP exportado do Notion:** Commit em `knowledge/html/` → workflow `ingest-html.yml` dispara.

---

## Convenções para Desenvolvimento

### JavaScript (telegram-webhook.js)

- **Módulo ES** (`"type": "module"` no package.json) — usar `import`/`export`, não `require`
- Variáveis de ambiente via `process.env` — nunca hardcode de credenciais
- Constantes de configuração no topo do arquivo (linhas ~19-21)
- Função principal: `export default async function handler(req, res)` (padrão Vercel)
- Não alterar a validação do webhook secret sem testar com o Telegram

### Python (ingest/)

- Python 3.11; dependências gerenciadas em `ingest/requirements.txt`
- Clientes Voyage AI e Supabase são singletons em `embeddings.py`
- Sempre chamar `delete_chunks_for_source()` antes de re-ingerir uma fonte
- Batch size para upsert: **50 chunks** (evita timeout do Supabase)
- Delay de **1s** entre chamadas de embedding (respeita rate limit da Voyage AI)

### Git e Branches

- **Branch de produção:** `claude/rag-knowledge-base-pipeline-dN4Ui`
- Desenvolvimento de documentação: `claude/add-claude-documentation-9rNS1`
- Não alterar a branch de produção sem revisar impacto no Vercel deploy

### Segurança

- Webhook secret validado via comparação segura (evita timing attacks)
- Rate limiting in-memory: 10 msgs/min por chat_id
- Input truncado em 2.000 chars antes de processar
- `SUPABASE_SERVICE_KEY` nunca exposta no frontend

---

## Decisões Técnicas Importantes

| Decisão | Motivo |
|---------|--------|
| Voyage AI `voyage-3` (não OpenAI) | Melhor qualidade de retrieval para pt-BR; tier gratuito generoso |
| IVFFlat com `lists=100` | Bom equilíbrio velocidade/precisão para < 1M chunks |
| `RAG_MIN_SIMILARITY = 0.3` | Valor anterior 0.7 era muito restritivo; fallback por keyword cobre lacunas |
| Chunks de 800 tokens + overlap 100 | Preserva contexto suficiente sem exceder janela do prompt |
| Histórico no Supabase | Persistência entre re-deploys do Vercel (substituiu in-memory) |
| PDFs > 25MB no Supabase Storage | Limite de 100MB por arquivo do GitHub |
| Fallback Claude Vision para PDFs | Suporte a PDFs escaneados sem texto extraível |
| `max_tokens=500` na resposta | Respostas concisas e dentro do limite do Telegram |

---

## Roadmap

### Maio 2026
- [ ] Controle de acesso por código único por aluno (Kiwify webhook + Resend email)
- [ ] Transcrição de áudio via Groq Whisper
- [ ] Histórico de conversa persistente no Supabase *(schema já existe, integração pendente)*

### Junho 2026
- [ ] Dashboard de analytics (perguntas mais feitas, chunks mais acessados)
- [ ] Ingestão de URLs (documentação Revit, Navisworks, Solibri, BIMcollab)

### Julho 2026
- [ ] Notificações proativas para alunos
- [ ] Avaliação de qualidade das respostas (thumbs up/down)
- [ ] Relatório mensal de uso por aluno
