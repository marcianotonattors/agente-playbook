"""
Ingestão do conteúdo do Notion para o Knowledge Base RAG.

Uso:
  python ingest/process_notion.py \\
    --database-id SEU_DATABASE_ID \\
    --name "Playbook da Coordenação BIM" \\
    --description "Conteúdo completo das 10 etapas do curso"
"""

import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path

from notion_client import Client as NotionClient

from embeddings import delete_chunks_for_source, upsert_chunks, upsert_source

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

CHUNK_SIZE = 800   # tokens
CHUNK_OVERLAP = 100


# ---------------------------------------------------------------------------
# Cliente Notion
# ---------------------------------------------------------------------------

def _get_notion() -> NotionClient:
    return NotionClient(auth=os.environ["NOTION_TOKEN"])


# ---------------------------------------------------------------------------
# Extração de texto de blocos Notion
# ---------------------------------------------------------------------------

RICH_TEXT_TYPES = {
    "paragraph", "heading_1", "heading_2", "heading_3",
    "bulleted_list_item", "numbered_list_item", "toggle",
    "quote", "callout",
}

CODE_BLOCK = "code"
TABLE_BLOCK = "table"


def rich_text_to_str(rich_text_list: list) -> str:
    return "".join(rt.get("plain_text", "") for rt in rich_text_list)


def block_to_text(block: dict) -> tuple[str, str]:
    """
    Converte um bloco Notion em (texto, chunk_type).
    chunk_type: 'text' | 'table' | 'heading'
    """
    btype = block.get("type", "")

    if btype in ("heading_1", "heading_2", "heading_3"):
        text = rich_text_to_str(block[btype].get("rich_text", []))
        return f"## {text}", "heading"

    if btype in RICH_TEXT_TYPES:
        text = rich_text_to_str(block[btype].get("rich_text", []))
        return text, "text"

    if btype == CODE_BLOCK:
        text = rich_text_to_str(block[CODE_BLOCK].get("rich_text", []))
        lang = block[CODE_BLOCK].get("language", "")
        return f"```{lang}\n{text}\n```", "text"

    return "", "text"


def fetch_table_rows(notion: NotionClient, block_id: str) -> str:
    """Busca linhas de uma tabela Notion e serializa como Markdown."""
    rows: list[list[str]] = []
    cursor = None
    while True:
        kwargs: dict = {"block_id": block_id}
        if cursor:
            kwargs["start_cursor"] = cursor
        resp = notion.blocks.children.list(**kwargs)
        for child in resp["results"]:
            if child["type"] == "table_row":
                cells = child["table_row"]["cells"]
                rows.append([rich_text_to_str(cell) for cell in cells])
        if not resp.get("has_more"):
            break
        cursor = resp["next_cursor"]

    if not rows:
        return ""

    header = rows[0]
    separator = ["---"] * len(header)
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(separator) + " |",
    ]
    for row in rows[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Traversal recursivo de blocos com paginação
# ---------------------------------------------------------------------------

_SKIP_RECURSE_TYPES = {TABLE_BLOCK, "child_database"}


def fetch_all_blocks(notion: NotionClient, block_id: str, depth: int = 0) -> list[dict]:
    """Retorna todos os blocos filhos recursivamente, com paginação.

    Não recursiona em TABLE_BLOCK (tratado via fetch_table_rows) nem em
    child_database (as páginas precisam ser obtidas via databases.query,
    não via blocks.children.list).
    """
    results: list[dict] = []
    cursor = None

    while True:
        kwargs: dict = {"block_id": block_id}
        if cursor:
            kwargs["start_cursor"] = cursor
        resp = notion.blocks.children.list(**kwargs)
        for block in resp["results"]:
            results.append(block)
            if block.get("has_children") and block.get("type") not in _SKIP_RECURSE_TYPES:
                children = fetch_all_blocks(notion, block["id"], depth + 1)
                results.extend(children)
        if not resp.get("has_more"):
            break
        cursor = resp["next_cursor"]

    return results


# ---------------------------------------------------------------------------
# Conversão de blocos para chunks de texto
# ---------------------------------------------------------------------------

def blocks_to_raw_segments(notion: NotionClient, blocks: list[dict]) -> list[dict]:
    """
    Converte lista de blocos em segmentos de texto com metadados.
    Retorna lista de dicts: {text, chunk_type, section}
    """
    segments: list[dict] = []
    current_section: str | None = None

    for block in blocks:
        btype = block.get("type", "")

        # Tabela: serializa diretamente
        if btype == TABLE_BLOCK:
            md = fetch_table_rows(notion, block["id"])
            if md:
                segments.append({
                    "text": f"Tabela da seção {current_section or 'N/A'}:\n\n{md}",
                    "chunk_type": "table",
                    "section": current_section,
                })
            continue

        text, ctype = block_to_text(block)
        if not text.strip():
            continue

        if ctype == "heading":
            current_section = text.lstrip("#").strip()

        segments.append({"text": text, "chunk_type": ctype, "section": current_section})

    return segments


# ---------------------------------------------------------------------------
# Chunking de segmentos de texto
# ---------------------------------------------------------------------------

try:
    import tiktoken
    _enc = tiktoken.get_encoding("cl100k_base")

    def _count_tokens(t: str) -> int:
        return len(_enc.encode(t))

    def _split_text(text: str) -> list[str]:
        tokens = _enc.encode(text)
        chunks: list[str] = []
        start = 0
        while start < len(tokens):
            end = min(start + CHUNK_SIZE, len(tokens))
            chunks.append(_enc.decode(tokens[start:end]))
            if end == len(tokens):
                break
            start += CHUNK_SIZE - CHUNK_OVERLAP
        return chunks

except ImportError:
    def _count_tokens(t: str) -> int:  # type: ignore[misc]
        return len(t.split())

    def _split_text(text: str) -> list[str]:  # type: ignore[misc]
        words = text.split()
        chunks = []
        for i in range(0, len(words), CHUNK_SIZE - CHUNK_OVERLAP):
            chunks.append(" ".join(words[i : i + CHUNK_SIZE]))
        return chunks


def segments_to_chunks(segments: list[dict]) -> list[dict]:
    """
    Agrupa segmentos consecutivos de texto e faz chunking por tokens.
    Tabelas e headings são sempre chunks independentes.
    """
    chunks: list[dict] = []
    chunk_index = 0
    buffer: list[str] = []
    buffer_section: str | None = None

    def flush_buffer():
        nonlocal chunk_index
        if not buffer:
            return
        text = "\n\n".join(buffer)
        for part in _split_text(text):
            if part.strip():
                chunks.append({
                    "content": part.strip(),
                    "chunk_type": "text",
                    "chunk_index": chunk_index,
                    "page_number": None,
                    "section": buffer_section,
                    "image_path": None,
                    "metadata": {},
                })
                chunk_index += 1
        buffer.clear()

    for seg in segments:
        ctype = seg["chunk_type"]

        if ctype in ("table", "heading"):
            flush_buffer()
            chunks.append({
                "content": seg["text"].strip(),
                "chunk_type": ctype,
                "chunk_index": chunk_index,
                "page_number": None,
                "section": seg["section"],
                "image_path": None,
                "metadata": {},
            })
            chunk_index += 1
        else:
            if seg["section"] != buffer_section and buffer:
                flush_buffer()
            buffer_section = seg["section"]
            buffer.append(seg["text"])

    flush_buffer()
    return chunks


# ---------------------------------------------------------------------------
# Busca de páginas no database Notion
# ---------------------------------------------------------------------------

def fetch_database_pages(notion: NotionClient, database_id: str) -> list[dict]:
    """Retorna todas as páginas de um database Notion com paginação completa."""
    pages: list[dict] = []
    cursor = None

    while True:
        kwargs: dict = {"database_id": database_id}
        if cursor:
            kwargs["start_cursor"] = cursor
        resp = notion.databases.query(**kwargs)
        pages.extend(resp["results"])
        if not resp.get("has_more"):
            break
        cursor = resp["next_cursor"]

    return pages


def page_title(page: dict) -> str:
    """Extrai o título de uma página Notion."""
    props = page.get("properties", {})
    for prop in props.values():
        if prop.get("type") == "title":
            return rich_text_to_str(prop["title"])
    return page["id"]


# ---------------------------------------------------------------------------
# Persistência de chunks processados como JSON (opcional)
# ---------------------------------------------------------------------------

def save_processed_json(chunks: list[dict], source_name: str) -> None:
    out_dir = Path("knowledge/processed")
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9_]", "_", source_name.lower())
    out_path = out_dir / f"{slug}_notion.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)
    logger.info("Chunks salvos em %s", out_path)


# ---------------------------------------------------------------------------
# Processamento recursivo de página com databases aninhados
# ---------------------------------------------------------------------------

def process_page_to_chunks(
    notion: NotionClient,
    page_id: str,
    title: str,
    parent_title: str | None = None,
) -> list[dict]:
    """Extrai chunks de uma página e de qualquer child_database aninhado nela.

    Isso captura estruturas como:
      Página (Etapa N)
        └── child_database (Aulas)
              └── Página (Aula: Título X)
    """
    all_chunks: list[dict] = []

    blocks = fetch_all_blocks(notion, page_id)

    # Conteúdo textual direto da página (ignora child_database — tratado abaixo)
    text_blocks = [b for b in blocks if b.get("type") != "child_database"]
    segments = blocks_to_raw_segments(notion, text_blocks)
    page_chunks = segments_to_chunks(segments)
    for chunk in page_chunks:
        chunk["metadata"]["page_title"] = title
        if parent_title:
            chunk["metadata"]["parent_title"] = parent_title
        chunk.setdefault("section", title)
    all_chunks.extend(page_chunks)

    # Processar child_databases aninhados (ex.: banco de aulas dentro de cada etapa)
    nested_db_ids = [b["id"] for b in blocks if b.get("type") == "child_database"]
    for db_id in nested_db_ids:
        try:
            sub_pages = fetch_database_pages(notion, db_id)
            logger.info("  Database aninhado em '%s': %d sub-páginas.", title, len(sub_pages))
            for sub_page in sub_pages:
                sub_title = page_title(sub_page)
                logger.info("    Sub-página: %s", sub_title)
                try:
                    sub_chunks = process_page_to_chunks(notion, sub_page["id"], sub_title, title)
                    all_chunks.extend(sub_chunks)
                except Exception as exc:
                    logger.warning("Erro na sub-página '%s': %s", sub_title, exc)
        except Exception as exc:
            logger.warning("Erro no database aninhado %s em '%s': %s", db_id, title, exc)

    return all_chunks


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Ingere Notion page ou database no Knowledge Base RAG.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--database-id", help="ID do database Notion")
    group.add_argument("--page-id", help="ID da página Notion")
    parser.add_argument("--name", required=True, help="Nome da fonte (ex: 'Playbook da Coordenação BIM')")
    parser.add_argument("--description", help="Descrição da fonte")
    parser.add_argument("--save-json", action="store_true", help="Salva chunks em knowledge/processed/")
    args = parser.parse_args()

    notion = _get_notion()
    all_chunks: list[dict] = []

    if args.database_id:
        logger.info("Buscando páginas do database %s…", args.database_id)
        pages = fetch_database_pages(notion, args.database_id)
        logger.info("Encontradas %d páginas.", len(pages))

        for page in pages:
            title = page_title(page)
            logger.info("Processando página: %s", title)
            try:
                chunks = process_page_to_chunks(notion, page["id"], title)
                all_chunks.extend(chunks)
            except Exception as exc:
                logger.warning("Erro ao processar página '%s': %s", title, exc)

    else:
        logger.info("Buscando conteúdo da página %s…", args.page_id)

        # Busca blocos diretos da página raiz para encontrar child_databases
        top_blocks = fetch_all_blocks(notion, args.page_id)
        child_db_ids = [b["id"] for b in top_blocks if b.get("type") == "child_database"]

        if child_db_ids:
            logger.info("Encontrados %d databases dentro da página.", len(child_db_ids))
            for db_id in child_db_ids:
                try:
                    pages = fetch_database_pages(notion, db_id)
                    logger.info("Database %s: %d páginas.", db_id, len(pages))
                    for page in pages:
                        title = page_title(page)
                        logger.info("Processando: %s", title)
                        try:
                            chunks = process_page_to_chunks(notion, page["id"], title)
                            all_chunks.extend(chunks)
                        except Exception as exc:
                            logger.warning("Erro na página '%s': %s", title, exc)
                except Exception as exc:
                    logger.warning("Erro no database %s: %s", db_id, exc)
        else:
            # Página simples sem databases — ingere o conteúdo direto
            all_chunks = process_page_to_chunks(notion, args.page_id, args.name)

    logger.info("Total de chunks extraídos: %d", len(all_chunks))

    if args.save_json:
        save_processed_json(all_chunks, args.name)

    logger.info("Registrando fonte no Supabase…")
    source_id = upsert_source(
        name=args.name,
        source_type="notion",
        description=args.description,
    )

    logger.info("Removendo chunks anteriores…")
    delete_chunks_for_source(source_id)

    logger.info("Gerando embeddings e inserindo %d chunks…", len(all_chunks))
    upsert_chunks(source_id, all_chunks)

    logger.info("Ingestão do Notion concluída para '%s'.", args.name)


if __name__ == "__main__":
    main()
