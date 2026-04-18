"""
Ingestão de PDFs para o Knowledge Base RAG.

Uso:
  python ingest/process_pdf.py \\
    --file knowledge/pdfs/iso-19650-2-pt.pdf \\
    --name "ISO 19650-2 PT-BR" \\
    --description "Organização e digitalização de informações sobre edificações" \\
    --version "2021"

  # Modo automático (GitHub Actions):
  python ingest/process_pdf.py --file knowledge/pdfs/doc.pdf --auto-meta
"""

import argparse
import base64
import io
import json
import logging
import os
import re
import sys
import tempfile
from pathlib import Path

import pdfplumber
import requests
import tiktoken
from anthropic import Anthropic
from PIL import Image

from embeddings import delete_chunks_for_source, upsert_chunks, upsert_source

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Token budgets
CHUNK_SIZE = 800
CHUNK_OVERLAP = 100
MAX_TABLE_TOKENS = 6000  # tabelas gigantes são truncadas com aviso

enc = tiktoken.get_encoding("cl100k_base")
claude = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


# ---------------------------------------------------------------------------
# Helpers de tokenização
# ---------------------------------------------------------------------------

def count_tokens(text: str) -> int:
    return len(enc.encode(text))


def split_by_tokens(text: str, size: int, overlap: int) -> list[str]:
    """Divide texto em chunks de `size` tokens com `overlap` de sobreposição."""
    tokens = enc.encode(text)
    chunks: list[str] = []
    start = 0
    while start < len(tokens):
        end = min(start + size, len(tokens))
        chunk_tokens = tokens[start:end]
        chunks.append(enc.decode(chunk_tokens))
        if end == len(tokens):
            break
        start += size - overlap
    return chunks


# ---------------------------------------------------------------------------
# Detecção de seção pelo tamanho de fonte
# ---------------------------------------------------------------------------

def detect_section(page, font_size_threshold: float = 13.0) -> str | None:
    """
    Tenta detectar o heading da página inspecionando palavras com fonte grande.
    Retorna a primeira linha com fonte maior que o threshold.
    """
    try:
        words = page.extract_words(extra_attrs=["size"])
        heading_words: list[str] = []
        for w in words:
            size = w.get("size", 0) or 0
            if size >= font_size_threshold:
                heading_words.append(w["text"])
            elif heading_words:
                break
        return " ".join(heading_words) if heading_words else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Tratamento de tabelas
# ---------------------------------------------------------------------------

def table_to_markdown(table: list[list[str | None]]) -> str:
    """Serializa tabela extraída pelo pdfplumber como Markdown."""
    if not table:
        return ""
    rows = [[cell or "" for cell in row] for row in table]
    header = rows[0]
    separator = ["---"] * len(header)
    body = rows[1:]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(separator) + " |",
    ]
    for row in body:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Descrição de imagens via Claude Vision
# ---------------------------------------------------------------------------

VISION_PROMPT = (
    "Descreva essa imagem com precisão técnica suficiente para que alguém consiga "
    "entender o conteúdo sem vê-la. Se for um fluxograma, descreva cada etapa e as "
    "conexões em ordem. Se for uma tabela visual, transcreva os valores. Se for um "
    "diagrama de processo, descreva a lógica completa. Responda em português."
)


def describe_image_with_claude(image_bytes: bytes, media_type: str = "image/png") -> str:
    """Envia imagem ao Claude Vision e retorna descrição textual."""
    b64 = base64.standard_b64encode(image_bytes).decode()
    message = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": b64,
                        },
                    },
                    {"type": "text", "text": VISION_PROMPT},
                ],
            }
        ],
    )
    return message.content[0].text.strip()


def extract_images_from_page(page, page_num: int, source_name: str) -> list[dict]:
    """
    Extrai imagens de uma página do PDF.
    Retorna lista de chunks do tipo image_description.
    """
    chunks: list[dict] = []
    try:
        images = page.images
    except Exception:
        return chunks

    for idx, img in enumerate(images):
        try:
            # pdfplumber expõe os bytes brutos da imagem
            img_data = img.get("stream")
            if img_data is None:
                continue

            # Converte para PNG via Pillow para garantir compatibilidade
            raw = img_data.get_data() if hasattr(img_data, "get_data") else bytes(img_data)
            pil_img = Image.open(io.BytesIO(raw)).convert("RGB")

            # Ignora imagens muito pequenas (ícones, decorações)
            w, h = pil_img.size
            if w < 100 or h < 100:
                continue

            buf = io.BytesIO()
            pil_img.save(buf, format="PNG")
            png_bytes = buf.getvalue()

            description = describe_image_with_claude(png_bytes)

            image_filename = f"page{page_num}_img{idx}.png"
            image_path = f"knowledge/pdfs/tmp_images/{re.sub(r'[^a-z0-9_]', '_', source_name.lower())}/{image_filename}"

            chunks.append({
                "content": description,
                "chunk_type": "image_description",
                "page_number": page_num,
                "section": None,
                "image_path": image_path,
                "metadata": {"width": w, "height": h},
            })
        except Exception as exc:
            logger.warning("Erro ao processar imagem %d da página %d: %s", idx, page_num, exc)

    return chunks


# ---------------------------------------------------------------------------
# Pipeline principal de extração
# ---------------------------------------------------------------------------

def process_pdf(
    file_path: str,
    source_name: str,
    description: str | None = None,
    version: str | None = None,
) -> list[dict]:
    """
    Processa um PDF completo e retorna lista de chunks prontos para embedding.
    """
    all_chunks: list[dict] = []
    chunk_index = 0

    with pdfplumber.open(file_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            section = detect_section(page)

            # --- Tabelas ---
            tables = page.extract_tables()
            table_bboxes: list[tuple] = []

            for table in tables:
                if not table:
                    continue
                md = table_to_markdown(table)
                if not md.strip():
                    continue

                # Contexto da tabela
                prefix = f"Tabela da seção {section or 'N/A'} do documento {source_name}:\n\n"
                content = prefix + md

                if count_tokens(content) > MAX_TABLE_TOKENS:
                    logger.warning(
                        "Tabela na página %d excede %d tokens; truncando.", page_num, MAX_TABLE_TOKENS
                    )
                    tokens = enc.encode(content)[:MAX_TABLE_TOKENS]
                    content = enc.decode(tokens)

                all_chunks.append({
                    "content": content,
                    "chunk_type": "table",
                    "chunk_index": chunk_index,
                    "page_number": page_num,
                    "section": section,
                    "image_path": None,
                    "metadata": {},
                })
                chunk_index += 1

                # Registra bbox para excluir da extração de texto corrido
                for t in (page.find_tables() or []):
                    table_bboxes.append(t.bbox)

            # --- Imagens ---
            image_chunks = extract_images_from_page(page, page_num, source_name)
            for ic in image_chunks:
                ic["chunk_index"] = chunk_index
                chunk_index += 1
            all_chunks.extend(image_chunks)

            # --- Texto corrido (excluindo regiões de tabelas) ---
            if table_bboxes:
                # Crop fora das tabelas não é direto; extraímos o texto da página
                # e removemos linhas que coincidem com células já capturadas
                raw_text = page.extract_text(x_tolerance=2, y_tolerance=2) or ""
                # Heurística: remove linhas que parecem ser cabeçalho/rodapé de tabela (|)
                lines = [ln for ln in raw_text.splitlines() if "|" not in ln]
                raw_text = "\n".join(lines).strip()
            else:
                raw_text = page.extract_text(x_tolerance=2, y_tolerance=2) or ""

            raw_text = raw_text.strip()
            if not raw_text:
                continue

            text_chunks = split_by_tokens(raw_text, CHUNK_SIZE, CHUNK_OVERLAP)
            for tc in text_chunks:
                all_chunks.append({
                    "content": tc.strip(),
                    "chunk_type": "text",
                    "chunk_index": chunk_index,
                    "page_number": page_num,
                    "section": section,
                    "image_path": None,
                    "metadata": {},
                })
                chunk_index += 1

    logger.info("Extração concluída: %d chunks de '%s'.", len(all_chunks), source_name)
    return all_chunks


# ---------------------------------------------------------------------------
# Auto-meta: inferência de metadados do nome do arquivo
# ---------------------------------------------------------------------------

def infer_meta_from_filename(file_path: str) -> dict:
    stem = Path(file_path).stem
    name = stem.replace("-", " ").replace("_", " ").title()
    return {"name": name, "description": None, "version": None}


# ---------------------------------------------------------------------------
# Persistência de chunks processados como JSON (opcional)
# ---------------------------------------------------------------------------

def save_processed_json(chunks: list[dict], source_name: str) -> None:
    out_dir = Path("knowledge/processed")
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9_]", "_", source_name.lower())
    out_path = out_dir / f"{slug}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)
    logger.info("Chunks salvos em %s", out_path)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def download_from_supabase(filename: str) -> str:
    """Baixa PDF do Supabase Storage e salva em arquivo temporário. Retorna o caminho."""
    url = f"{os.environ['SUPABASE_URL']}/storage/v1/object/pdfs/{filename}"
    headers = {"Authorization": f"Bearer {os.environ['SUPABASE_SERVICE_KEY']}"}
    logger.info("Baixando '%s' do Supabase Storage…", filename)
    response = requests.get(url, headers=headers, timeout=300)
    if response.status_code != 200:
        logger.error("Falha ao baixar arquivo: HTTP %d", response.status_code)
        sys.exit(1)
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    tmp.write(response.content)
    tmp.close()
    logger.info("Arquivo salvo temporariamente em %s", tmp.name)
    return tmp.name


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingere PDF no Knowledge Base RAG.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", help="Caminho local para o PDF")
    source.add_argument("--supabase-file", help="Nome do arquivo no Supabase Storage bucket 'pdfs'")
    parser.add_argument("--name", help="Nome do documento (ex: 'ISO 19650-2 PT-BR')")
    parser.add_argument("--description", help="Descrição do documento")
    parser.add_argument("--version", help="Versão do documento")
    parser.add_argument(
        "--auto-meta",
        action="store_true",
        help="Infere metadados a partir do nome do arquivo",
    )
    parser.add_argument(
        "--save-json",
        action="store_true",
        help="Salva chunks em knowledge/processed/ antes de enviar ao Supabase",
    )
    args = parser.parse_args()

    if args.supabase_file:
        file_path = download_from_supabase(args.supabase_file)
        original_filename = args.supabase_file
    else:
        file_path = args.file
        original_filename = args.file
        if not os.path.isfile(file_path):
            logger.error("Arquivo não encontrado: %s", file_path)
            sys.exit(1)

    if args.auto_meta:
        meta = infer_meta_from_filename(original_filename)
        name = args.name or meta["name"]
        description = args.description or meta["description"]
        version = args.version or meta["version"]
    else:
        if not args.name:
            logger.error("--name é obrigatório quando --auto-meta não está ativo.")
            sys.exit(1)
        name = args.name
        description = args.description
        version = args.version

    logger.info("Processando '%s'…", file_path)
    chunks = process_pdf(file_path, name, description, version)

    if args.save_json:
        save_processed_json(chunks, name)

    logger.info("Registrando fonte no Supabase…")
    source_id = upsert_source(
        name=name,
        source_type="pdf",
        filename=os.path.basename(original_filename),
        description=description,
        version=version,
    )

    logger.info("Removendo chunks anteriores da fonte %s…", source_id)
    delete_chunks_for_source(source_id)

    logger.info("Gerando embeddings e inserindo %d chunks…", len(chunks))
    upsert_chunks(source_id, chunks)

    logger.info("Ingestão concluída com sucesso para '%s'.", name)


if __name__ == "__main__":
    main()
