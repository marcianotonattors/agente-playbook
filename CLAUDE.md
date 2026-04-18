# Agente Playbook BIM — Contexto para Claude Code

## O que é este projeto

Bot do Telegram que responde perguntas dos alunos do **Playbook da Coordenação BIM** (curso de Marciano Tonatto) usando RAG — busca trechos relevantes na base de conhecimento antes de responder com Claude.

## Stack

- **Vercel** — hospeda a serverless function (`api/functions/telegram-webhook.js`)
- **Supabase** — banco vetorial com pgvector (tabelas: `knowledge_sources`, `knowledge_chunks`)
- **Voyage AI** — embeddings `voyage-3` (1024 dimensões)
- **Anthropic Claude** — modelo `claude-sonnet-4-6` para geração de respostas
- **GitHub Actions** — ingestão automática de PDFs e Notion
- **Telegram** — interface com os alunos (bot: BIMgente ou similar)

## URLs e Recursos

- **Vercel:** `https://agente-playbook-rho.vercel.app`
- **Webhook:** `https://agente-playbook-rho.vercel.app/api/telegram`
- **Branch de produção:** `claude/rag-knowledge-base-pipeline-dN4Ui`
- **Repositório:** `marcianotonattors/agente-playbook`

## Variáveis de Ambiente

**Vercel:**
- `ANTHROPIC_API_KEY` — Claude API
- `VOYAGE_API_KEY` — Voyage AI embeddings
- `SUPABASE_URL` — URL do projeto Supabase
- `SUPABASE_SERVICE_KEY` — chave secret do Supabase
- `TELEGRAM_BOT_TOKEN` — token do bot
- `TELEGRAM_WEBHOOK_SECRET` — secret para validar requests do Telegram

**GitHub Secrets (Actions):**
- `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`
- `NOTION_TOKEN` — integração Notion
- `NOTION_DATABASE_ID` — ID da página raiz do Playbook

## Decisões Importantes

- Embeddings migrados de OpenAI para **Voyage AI** (abril/2026) — dimensão 1024
- PDFs grandes (> 25MB) ficam no **Supabase Storage** (bucket `pdfs`), não no GitHub
- Similaridade mínima RAG: **0.5** (foi 0.7 — muito restritivo)
- Histórico de conversa em **memória** (em revisão — migrar para Supabase)
- Bot faz **perguntas de contexto** antes de responder quando pergunta for vaga
- Rate limiting: **10 msgs/min** por usuário
- Limite de input: **2.000 caracteres**
- Webhook secret ativo — validação via `X-Telegram-Bot-Api-Secret-Token`

## Fontes Ingeridas

| Fonte | Tipo | Status |
|-------|------|--------|
| Playbook da Coordenação BIM | Notion | Ativo — atualiza toda segunda 8h UTC |
| Coletânea BIM - Guia de Conceitos Gerais | PDF (Supabase Storage) | Ingerido abr/2026 |
| Coletânea BIM - Guia de Coordenação de Projetos | PDF (Supabase Storage) | Ingerido abr/2026 |
| Coletânea BIM - Guia de Gerenciamento de Projetos | PDF (Supabase Storage) | Ingerido abr/2026 |

## Como Adicionar PDFs

**PDFs < 25MB:** upload em `knowledge/pdfs/` no GitHub → workflow dispara automaticamente.

**PDFs > 25MB:** upload no Supabase Storage (bucket `pdfs`) → GitHub Actions → Ingest PDF → Run workflow → informar nome do arquivo.

## Roadmap Próximos 3 Meses

### Maio
- [ ] Controle de acesso por código único por aluno (Kiwify webhook + Resend email)
- [ ] Transcrição de áudio via Groq Whisper
- [ ] Histórico de conversa persistente no Supabase

### Junho
- [ ] Dashboard de analytics (perguntas mais feitas, chunks mais acessados)
- [ ] Ingestão de URLs (documentação Revit, Navisworks, Solibri, BIMcollab)

### Julho
- [ ] Notificações proativas para alunos
- [ ] Avaliação de qualidade das respostas (thumbs up/down)
- [ ] Relatório mensal de uso por aluno
