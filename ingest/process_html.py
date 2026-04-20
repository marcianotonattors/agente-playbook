"""
Ingestão de HTML exportado do Notion para o Knowledge Base RAG.

Suporta arquivo .html único ou .zip (export do Notion com múltiplas páginas).

Uso:
  python ingest/process_html.py \\
    --html-path knowledge/html/playbook.zip \\
    --name "Playbook da Coordenação BIM" \\
    --description "Conteúdo completo das etapas do curso"
"""

import argparse
import logging
import os
import re
import requests
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("Instale: pip install beautifulsoup4 lxml")
    sys.exit(1)

sys.path.insert(0, str(Path(__file__).parent))
from embeddings import delete_chunks_for_source, upsert_chunks, upsert_source

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

CHUNK_SIZE = 800
CHUNK_OVERLAP = 100

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
        return [
            " ".join(words[i : i + CHUNK_SIZE])
            for i in range(0, len(words), CHUNK_SIZE - CHUNK_OVERLAP)
        ]


# ---------------------------------------------------------------------------
# Parsing HTML
# ---------------------------------------------------------------------------

_URL_RE = re.compile(r"https?://\S{60,}")  # remove URLs longas (ex: S3 signed URLs)


def _clean(text: str) -> str:
    text = _URL_RE.sub("", text)
    return " ".join(text.split())  # colapsa espaços extras


HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
SKIP_TAGS = {"script", "style", "head", "nav", "footer"}
SKIP_CLASSES = {
    "page-cover-image", "page-header-icon", "page-description",
    "page-title", "breadcrumb", "record-icon",
}


def _table_to_markdown(table_tag) -> str:
    rows: list[list[str]] = []
    for tr in table_tag.find_all("tr"):
        cells = [td.get_text(separator=" ", strip=True) for td in tr.find_all(["td", "th"])]
        if cells:
            rows.append(cells)
    if not rows:
        return ""
    header = rows[0]
    sep = ["---"] * len(header)
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(sep) + " |",
    ]
    for row in rows[1:]:
        row = (row + [""] * len(header))[: len(header)]
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _walk(element, segments: list, section_ref: list, source_file: str) -> None:
    """Percorre o HTML recursivamente extraindo segmentos em ordem do documento."""
    for child in element.children:
        if not hasattr(child, "name") or child.name is None:
            continue

        tag = child.name.lower()
        classes = set(child.get("class", []))

        if tag in SKIP_TAGS:
            continue
        if classes & SKIP_CLASSES:
            continue
        if "link-to-page" in classes:
            # Link para sub-página — processada como arquivo HTML separado no ZIP
            continue

        if tag in HEADING_TAGS:
            text = _clean(child.get_text(strip=True))
            if text:
                section_ref[0] = text
                segments.append({
                    "text": f"## {text}",
                    "chunk_type": "heading",
                    "section": text,
                    "source_file": source_file,
                })

        elif tag == "table":
            md = _table_to_markdown(child)
            if md:
                label = f"Tabela da seção {section_ref[0]}:" if section_ref[0] else "Tabela:"
                segments.append({
                    "text": f"{label}\n\n{md}",
                    "chunk_type": "table",
                    "section": section_ref[0],
                    "source_file": source_file,
                })

        elif tag == "figure":
            if "link-to-page" in classes:
                continue
            caption = child.find("figcaption")
            if caption:
                text = _clean(caption.get_text(separator=" ", strip=True))
                if text:
                    segments.append({
                        "text": f"[Imagem] {text}",
                        "chunk_type": "text",
                        "section": section_ref[0],
                        "source_file": source_file,
                    })

        elif tag == "summary":
            text = _clean(child.get_text(strip=True))
            if text:
                section_ref[0] = text
                segments.append({
                    "text": f"## {text}",
                    "chunk_type": "heading",
                    "section": text,
                    "source_file": source_file,
                })

        elif tag in {"p", "blockquote"}:
            text = _clean(child.get_text(separator=" ", strip=True))
            if text:
                segments.append({
                    "text": text,
                    "chunk_type": "text",
                    "section": section_ref[0],
                    "source_file": source_file,
                })

        elif tag in {"ul", "ol"}:
            items: list[str] = []
            for li in child.find_all("li", recursive=False):
                item_text = _clean(li.get_text(separator=" ", strip=True))
                if item_text:
                    items.append(f"• {item_text}")
            if items:
                segments.append({
                    "text": "\n".join(items),
                    "chunk_type": "text",
                    "section": section_ref[0],
                    "source_file": source_file,
                })

        elif tag == "pre":
            code = child.find("code")
            text = (code or child).get_text(strip=True)
            if text:
                segments.append({
                    "text": f"```\n{text}\n```",
                    "chunk_type": "text",
                    "section": section_ref[0],
                    "source_file": source_file,
                })

        else:
            # Containers: div, details, article, section, main, header, aside, …
            _walk(child, segments, section_ref, source_file)


def parse_html_file(html_path: Path) -> list[dict]:
    """Parseia um arquivo HTML exportado do Notion e retorna segmentos de texto."""
    logger.info("Parseando %s", html_path.name)
    with open(html_path, encoding="utf-8", errors="replace") as f:
        soup = BeautifulSoup(f, "lxml")

    segments: list[dict] = []
    section_ref: list = [None]

    # Título da página
    title_tag = soup.find("h1", class_="page-title") or soup.find("title")
    page_title = title_tag.get_text(strip=True) if title_tag else html_path.stem

    if page_title:
        section_ref[0] = page_title
        segments.append({
            "text": f"## {page_title}",
            "chunk_type": "heading",
            "section": page_title,
            "source_file": html_path.name,
        })

    # Corpo principal (Notion exporta em <div class="page-body">)
    body = (
        soup.find("div", class_="page-body")
        or soup.find("article")
        or soup.find("body")
        or soup
    )
    _walk(body, segments, section_ref, html_path.name)

    logger.info("  %s → %d segmentos", html_path.name, len(segments))
    return segments


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def segments_to_chunks(segments: list[dict]) -> list[dict]:
    """Agrupa segmentos em chunks com sobreposição de tokens."""
    chunks: list[dict] = []
    chunk_index = 0
    buffer: list[str] = []
    buffer_section: str | None = None
    buffer_source: str | None = None

    def flush() -> None:
        nonlocal chunk_index
        if not buffer:
            return
        for part in _split_text("\n\n".join(buffer)):
            if part.strip():
                chunks.append({
                    "content": part.strip(),
                    "chunk_type": "text",
                    "chunk_index": chunk_index,
                    "page_number": None,
                    "section": buffer_section,
                    "image_path": None,
                    "metadata": {"source_file": buffer_source or ""},
                })
                chunk_index += 1
        buffer.clear()

    for seg in segments:
        ctype = seg["chunk_type"]

        if ctype in ("table", "heading"):
            flush()
            chunks.append({
                "content": seg["text"].strip(),
                "chunk_type": ctype,
                "chunk_index": chunk_index,
                "page_number": None,
                "section": seg["section"],
                "image_path": None,
                "metadata": {"source_file": seg.get("source_file", "")},
            })
            chunk_index += 1
        else:
            if seg["section"] != buffer_section and buffer:
                flush()
            buffer_section = seg["section"]
            buffer_source = seg.get("source_file")
            buffer.append(seg["text"])

    flush()
    return chunks


# ---------------------------------------------------------------------------
# Download de URL
# ---------------------------------------------------------------------------

def download_from_url(url: str) -> Path:
    """Baixa arquivo de uma URL (Supabase Storage ou pública) para arquivo temporário."""
    headers: dict = {}
    supabase_url = os.environ.get("SUPABASE_URL", "")
    if supabase_url and url.startswith(supabase_url):
        headers["Authorization"] = f"Bearer {os.environ['SUPABASE_SERVICE_KEY']}"

    logger.info("Baixando arquivo de URL…")
    response = requests.get(url, headers=headers, timeout=300)
    if response.status_code != 200:
        logger.error("Falha ao baixar: HTTP %d — %s", response.status_code, response.text[:200])
        sys.exit(1)

    suffix = Path(url.split("?")[0]).suffix.lower() or ".zip"
    tmp_file = Path(tempfile.mktemp(suffix=suffix))
    tmp_file.write_bytes(response.content)
    logger.info("Baixado: %.1f MB → %s", len(response.content) / 1e6, tmp_file.name)
    return tmp_file


# ---------------------------------------------------------------------------
# Coleta de arquivos HTML
# ---------------------------------------------------------------------------

def collect_html_files(html_path: Path) -> tuple[list[Path], Path | None]:
    """
    Retorna (lista de HTMLs, diretório temporário ou None).
    Para ZIP: extrai em temp dir e retorna todos os .html encontrados.
    Para diretório: retorna todos os .html recursivamente.
    Para arquivo .html/.htm: retorna lista com ele.
    """
    suffix = html_path.suffix.lower()

    if suffix == ".zip":
        tmp = Path(tempfile.mkdtemp())
        logger.info("Extraindo ZIP em %s", tmp)
        with zipfile.ZipFile(html_path, "r") as zf:
            zf.extractall(tmp)
        # Extrai ZIPs aninhados (Notion exporta ZIP dentro de ZIP)
        for inner_zip in list(tmp.rglob("*.zip")):
            logger.info("Extraindo ZIP interno: %s", inner_zip.name)
            with zipfile.ZipFile(inner_zip, "r") as zf:
                zf.extractall(inner_zip.parent)
            inner_zip.unlink()
        files = sorted(tmp.rglob("*.html")) + sorted(tmp.rglob("*.htm"))
        return files, tmp

    if html_path.is_dir():
        files = sorted(html_path.rglob("*.html")) + sorted(html_path.rglob("*.htm"))
        return files, None

    if suffix in {".html", ".htm"}:
        return [html_path], None

    raise ValueError(f"Formato não suportado: {suffix}. Use .html, .htm ou .zip")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingere HTML exportado do Notion no Knowledge Base RAG."
    )
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--html-path",
        help="Arquivo .html, .zip ou diretório com HTMLs"
    )
    source_group.add_argument(
        "--url",
        help="URL do arquivo no Supabase Storage ou URL pública"
    )
    parser.add_argument("--name", required=True, help="Nome da fonte")
    parser.add_argument("--description", help="Descrição da fonte")
    parser.add_argument(
        "--save-json", action="store_true",
        help="Salva chunks em knowledge/processed/ (debug)"
    )
    args = parser.parse_args()

    downloaded_file: Path | None = None
    tmp_dir: Path | None = None
    try:
        if args.url:
            downloaded_file = download_from_url(args.url)
            html_path = downloaded_file
        else:
            html_path = Path(args.html_path)
            if not html_path.exists():
                logger.error("Caminho não encontrado: %s", html_path)
                sys.exit(1)

        html_files, tmp_dir = collect_html_files(html_path)
        if not html_files:
            logger.error("Nenhum arquivo HTML encontrado em %s", html_path)
            sys.exit(1)
        logger.info("Encontrados %d arquivo(s) HTML.", len(html_files))

        all_segments: list[dict] = []
        for f in html_files:
            all_segments.extend(parse_html_file(f))

        all_chunks = segments_to_chunks(all_segments)
        logger.info("Total de chunks: %d", len(all_chunks))

        if args.save_json:
            import json
            out_dir = Path("knowledge/processed")
            out_dir.mkdir(parents=True, exist_ok=True)
            slug = re.sub(r"[^a-z0-9_]", "_", args.name.lower())
            out_path = out_dir / f"{slug}_html.json"
            with open(out_path, "w", encoding="utf-8") as jf:
                json.dump(all_chunks, jf, ensure_ascii=False, indent=2)
            logger.info("Chunks salvos em %s", out_path)

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

        logger.info("Ingestão HTML concluída para '%s'.", args.name)

    finally:
        if downloaded_file and downloaded_file.exists():
            downloaded_file.unlink(missing_ok=True)
        if tmp_dir and tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
