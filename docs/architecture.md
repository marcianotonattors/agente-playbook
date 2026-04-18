# Arquitetura do Knowledge Base RAG

**BIM Consultivo | Agente Telegram com RAG sobre PDFs e Notion**

## Três Camadas

### Camada 1 — Ingestão (GitHub Actions)

Script Python executado automaticamente ao adicionar PDFs ou via schedule semanal para o Notion.

- `ingest/process_pdf.py` — Extrai texto, tabelas e imagens de PDFs com `pdfplumber`
- `ingest/process_notion.py` — Busca páginas e blocos via Notion API com paginação completa
- `ingest/embeddings.py` — Gera embeddings via OpenAI `text-embedding-3-small` (1536 dim) e persiste no Supabase

### Camada 2 — Armazenamento (Supabase + pgvector)

- `knowledge_sources` — Metadados dos documentos
- `knowledge_chunks` — Texto + embedding vetorial + metadados de localização
- `search_chunks` — Função RPC para busca por similaridade cosseno (IVFFlat index)
- Supabase Storage — Backup dos PNGs extraídos de PDFs

### Camada 3 — Consulta (Vercel Function)

- `api/functions/telegram-webhook.js` — Recebe mensagem do Telegram, executa RAG, responde com Claude

## Fluxo de uma Pergunta

```
Aluno envia mensagem no Telegram
        ↓
Webhook chama Vercel Function
        ↓
Function gera embedding da pergunta (OpenAI)
        ↓
Busca top-5 chunks por similaridade no Supabase
        ↓
Monta system prompt com chunks como contexto
        ↓
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

## Decisões de Design

**Por que OpenAI para embeddings e Claude para geração?**
Voyage AI (parceira Anthropic) é alternativa especializada em retrieval, mas exige re-ingestão completa se migrar. `text-embedding-3-small` com 1536 dims tem ótimo custo-benefício como padrão inicial.

**Por que IVFFlat com lists=100?**
Para volumes de até ~1M chunks, IVFFlat oferece boa velocidade com precisão aceitável. Migrar para HNSW se a base crescer e a latência de busca ultrapassar 500ms.

**Por que histórico em memória e não no banco?**
Solução inicial simples. Substituir por tabela `conversation_history` no Supabase quando for necessário suporte a múltiplas instâncias ou persistência entre deploys.

**PDFs escaneados (imagem pura)**
`pdfplumber` não extrai texto de PDFs escaneados. Fallback: enviar páginas como imagens ao Claude Vision. Identificar na primeira ingestão: se `page.extract_text()` retornar vazio para todas as páginas, o PDF provavelmente é escaneado.

## Variáveis de Ambiente

| Variável | Onde configurar | Descrição |
|----------|----------------|-----------|
| `ANTHROPIC_API_KEY` | Vercel + GitHub Secrets | Claude API |
| `OPENAI_API_KEY` | Vercel + GitHub Secrets | Embeddings |
| `SUPABASE_URL` | Vercel + GitHub Secrets | URL do projeto Supabase |
| `SUPABASE_SERVICE_KEY` | Vercel + GitHub Secrets | Chave de serviço (bypass RLS) |
| `TELEGRAM_BOT_TOKEN` | Vercel | Token do bot Telegram |
| `NOTION_TOKEN` | GitHub Secrets | Token de integração Notion |
| `NOTION_DATABASE_ID` | GitHub Secrets | ID do database raiz do Playbook |

## GitHub como Fonte Única de Verdade

| Camada | Contém | Papel |
|--------|--------|-------|
| GitHub | Código, PDFs, scripts, docs, Actions | Fonte de verdade — tudo recriável a partir daqui |
| Supabase | Embeddings, chunks | Dados derivados e estado operacional |
| Vercel | Runtime das functions | Deploy automático a partir do GitHub |

O banco vetorial pode ser recriado do zero rodando os scripts de ingestão em todos os arquivos de `knowledge/pdfs/` e disparando o workflow do Notion manualmente.
