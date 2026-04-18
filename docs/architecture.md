# Arquitetura do Knowledge Base RAG

**BIM Consultivo | Agente Telegram com RAG sobre PDFs e Notion**

## Três Camadas

### Camada 1 — Ingestão (GitHub Actions)

Script Python executado automaticamente ao adicionar PDFs ou via schedule semanal para o Notion.

- `ingest/process_pdf.py` — Extrai texto, tabelas e imagens de PDFs com `pdfplumber`. Suporta arquivos locais (< 25MB via GitHub) e arquivos grandes via Supabase Storage.
- `ingest/process_notion.py` — Suporta página Notion com databases internos ou database direto. Paginação completa.
- `ingest/embeddings.py` — Gera embeddings via Voyage AI `voyage-3` (1024 dims) e persiste no Supabase.

### Camada 2 — Armazenamento (Supabase + pgvector)

- `knowledge_sources` — Metadados dos documentos (com constraint UNIQUE em `name`)
- `knowledge_chunks` — Texto + embedding vetorial (1024 dims) + metadados de localização
- `search_chunks` — Função RPC para busca por similaridade cosseno (IVFFlat index)
- Supabase Storage (bucket `pdfs`) — Armazenamento de PDFs grandes (> 25MB)

### Camada 3 — Consulta (Vercel Function)

- `api/functions/telegram-webhook.js` — Recebe mensagem do Telegram, valida webhook secret, aplica rate limiting, executa RAG, responde com Claude.

## Fluxo de uma Pergunta

```
Aluno envia mensagem no Telegram
        ↓
Webhook chama Vercel Function
        ↓
Valida X-Telegram-Bot-Api-Secret-Token
        ↓
Verifica rate limit (10 msg/min por usuário)
        ↓
Function gera embedding da pergunta (Voyage AI)
        ↓
Busca top-5 chunks por similaridade ≥ 0.5 no Supabase
        ↓
Monta system prompt com chunks como contexto
        ↓
Claude avalia se precisa de contexto adicional
        ↓ (se sim: faz perguntas ao aluno)
        ↓ (se não: responde diretamente)
Chama Claude API (claude-sonnet-4-6)
        ↓
Retorna resposta ao aluno no Telegram
```

## Estratégia de Chunking

| Tipo de Conteúdo | Estratégia | chunk_type |
|-----------------|-----------|-----------|
| Texto corrido | 800 tokens, overlap 100 tokens | `text` |
| Tabela (pdfplumber) | Chunk único, serializado como Markdown | `table` |
| Imagem / Fluxograma | Descrita via Claude Vision, salva como texto | `image_description` |
| Heading (Notion) | Chunk independente | `heading` |

## Segurança

| Proteção | Implementação |
|----------|--------------|
| Validação de origem | `X-Telegram-Bot-Api-Secret-Token` header verificado a cada request |
| Rate limiting | 10 mensagens por minuto por `chat_id` (em memória) |
| Limite de input | Mensagens truncadas em 2.000 caracteres |

## Decisões de Design

**Por que Voyage AI para embeddings?**
Voyage AI `voyage-3` (1024 dims) tem qualidade superior ao `text-embedding-3-small` da OpenAI para retrieval, é parceiro oficial da Anthropic e tem tier gratuito generoso (200M tokens). Migração realizada em abril/2026 substituindo OpenAI.

**Por que IVFFlat com lists=100?**
Para volumes de até ~1M chunks, IVFFlat oferece boa velocidade com precisão aceitável. Migrar para HNSW se a base crescer e a latência de busca ultrapassar 500ms.

**Por que histórico em memória e não no banco?**
Solução inicial simples. Substituir por tabela `conversation_history` no Supabase quando for necessário persistência entre deploys — planejado para maio.

**Por que o bot faz perguntas antes de responder?**
Perguntas vagas (ex: "não consigo fazer a coordenação") geram respostas genéricas. O system prompt instrui o Claude a pedir contexto (software usado, etapa do processo) quando a pergunta for ambígua.

**PDFs grandes via Supabase Storage**
GitHub tem limite de 25MB por arquivo. PDFs técnicos de BIM frequentemente excedem esse limite. O workflow `ingest-pdf.yml` aceita disparo manual com nome de arquivo no bucket `pdfs` do Supabase Storage.

**PDFs escaneados (imagem pura)**
`pdfplumber` não extrai texto de PDFs escaneados. Fallback: enviar páginas como imagens ao Claude Vision. Identificar na primeira ingestão: se `page.extract_text()` retornar vazio para todas as páginas, o PDF provavelmente é escaneado.

## Variáveis de Ambiente

| Variável | Onde configurar | Descrição |
|----------|----------------|-----------|
| `ANTHROPIC_API_KEY` | Vercel + GitHub Secrets | Claude API |
| `VOYAGE_API_KEY` | Vercel + GitHub Secrets | Embeddings Voyage AI |
| `SUPABASE_URL` | Vercel + GitHub Secrets | URL do projeto Supabase |
| `SUPABASE_SERVICE_KEY` | Vercel + GitHub Secrets | Chave secret do Supabase |
| `TELEGRAM_BOT_TOKEN` | Vercel | Token do bot Telegram |
| `TELEGRAM_WEBHOOK_SECRET` | Vercel | Secret para validar requests do Telegram |
| `NOTION_TOKEN` | GitHub Secrets | Token de integração Notion |
| `NOTION_DATABASE_ID` | GitHub Secrets | ID da página raiz do Playbook |

## GitHub como Fonte Única de Verdade

| Camada | Contém | Papel |
|--------|--------|-------|
| GitHub | Código, PDFs pequenos, scripts, docs, Actions | Fonte de verdade — tudo recriável a partir daqui |
| Supabase | Embeddings, chunks, PDFs grandes | Dados derivados e estado operacional |
| Vercel | Runtime das functions | Deploy automático a partir do GitHub |

O banco vetorial pode ser recriado do zero rodando os scripts de ingestão em todos os arquivos e disparando os workflows manualmente.
