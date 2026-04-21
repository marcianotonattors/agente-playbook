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
| Adicionar URL de software | `add: documentação Revit 2025 PT-BR` |

---

## Ingestão de URLs (Documentação de Softwares)

Use o workflow **Ingest URL** no GitHub Actions para ingerir documentação oficial dos softwares BIM.

### Links recomendados para ingerir

| Software | URL sugerida | Nome sugerido | Depth | Max pages |
|----------|-------------|---------------|-------|-----------|
| Autodesk Revit | `https://help.autodesk.com/view/RVT/2025/PTB/` | `Revit 2025 - Ajuda Oficial` | 1 | 80 |
| Autodesk Navisworks | `https://help.autodesk.com/view/NAV/2025/PTB/` | `Navisworks 2025 - Ajuda Oficial` | 1 | 80 |
| Solibri | `https://solibri.com/solibri-office-documentation` | `Solibri - Documentação` | 1 | 50 |
| BIMcollab Zoom | `https://help.bimcollab.com/en/zoom/zoom` | `BIMcollab Zoom - Ajuda` | 1 | 50 |
| BIMcollab Cloud | `https://help.bimcollab.com/en/bimcollab-cloud` | `BIMcollab Cloud - Ajuda` | 1 | 40 |

### Como executar

1. Acesse **GitHub → Actions → Ingest URL → Run workflow**
2. Preencha os campos:
   - **url**: URL inicial da documentação
   - **name**: Nome que aparecerá nas citações do agente (`Fonte: <name>`)
   - **description**: Descrição opcional
   - **depth**: `1` para seguir links diretos da página inicial (recomendado)
   - **max_pages**: Limite de páginas (comece com `80`, aumente se necessário)
3. Clique em **Run workflow**
4. Após concluir, registre a fonte na tabela acima

> **Dica:** Execute com `depth=0` primeiro para testar se a URL principal é acessível, antes de fazer o crawl completo.
