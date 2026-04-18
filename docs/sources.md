# Registro de Fontes Ingeridas

Documentos processados e carregados na base vetorial do Knowledge Base RAG.

| Nome | Tipo | Arquivo / ID | Descrição | Data de Ingestão |
|------|------|-------------|-----------|-----------------|
| Playbook da Coordenação BIM | notion | Página raiz com database interno | Conteúdo completo das etapas do curso BIM Consultivo (15 páginas, ~153 chunks) | 2026-04-18 |
| Coletânea BIM - Guia de Conceitos Gerais | pdf | Supabase Storage | Coletânea de Gerenciamento e Coordenação de Projetos em BIM — Guia de Conceitos Gerais | 2026-04-18 |
| Coletânea BIM - Guia de Coordenação de Projetos de Edificações | pdf | Supabase Storage | Coletânea de Gerenciamento e Coordenação de Projetos em BIM — Guia de Coordenação | 2026-04-18 |
| Coletânea BIM - Guia de Gerenciamento de Projetos de Edificações | pdf | Supabase Storage | Coletânea de Gerenciamento e Coordenação de Projetos em BIM — Guia de Gerenciamento | 2026-04-18 |

## Como Registrar um Novo Documento

Após executar o script de ingestão com sucesso, adicione uma linha nesta tabela.

## Convenção de Commits para Novos Documentos

| Ação | Mensagem sugerida |
|------|------------------|
| Adicionar PDF novo | `add: ISO 19650-2 pt-BR v2021` |
| Atualizar export do Notion | `add: Notion export atualizado abril/2026` |
| Re-ingerir documento com correções | `fix: re-ingestão ISO 19650-2 com chunking corrigido` |
