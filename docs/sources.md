# Registro de Fontes Ingeridas

Documentos processados e carregados na base vetorial do Knowledge Base RAG.

| Nome | Tipo | Arquivo | Versão | Descrição | Data de Ingestão |
|------|------|---------|--------|-----------|-----------------|
| — | — | — | — | Nenhum documento ingerido ainda | — |

## Como Registrar um Novo Documento

Após executar o script de ingestão com sucesso, adicione uma linha nesta tabela:

```
| Nome do Documento | pdf | nome-do-arquivo.pdf | 2024 | Breve descrição | AAAA-MM-DD |
```

## Convenção de Commits para Novos Documentos

| Ação | Mensagem sugerida |
|------|------------------|
| Adicionar PDF novo | `add: ISO 19650-2 pt-BR v2021` |
| Atualizar export do Notion | `add: Notion export Etapa 6 configuração de regras` |
| Re-ingerir documento com correções | `fix: re-ingestão ISO 19650-2 com chunking corrigido` |
