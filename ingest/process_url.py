"""
Ingestão de URLs para o Knowledge Base RAG.

Uso:
  python ingest/process_url.py \
    --url "https://help.autodesk.com/view/RVT/2025/PTB/" \
    --name "Revit 2025 - Ajuda Oficial" \
    --description "Documentação oficial do Autodesk Revit 2025 em português" \
    --depth 1 \
    --max-pages 80

  # Apenas uma página, sem seguir links:
  python ingest/process_url.py \
    --url "https://help.bimcollab.com/en/zoom/zoom" \
    --name "BIMcollab Zoom - Ajuda" \
    --depth 0
"""

import argparse
import logging
import re
import sys
import time
from collections import deque
from urllib.parse import urljoin, urlparse

import requests
import tiktoken
from bs4 import BeautifulSoup

from embeddings import delete_chunks_for_source, upsert_chunks, upsert_source

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

CHUNK_SIZE = 800
CHUNK_OVERLAP = 100

enc = tiktoken.get_encoding("cl100k_base")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; PlaybookBIMBot/1.0; "
        "+https://github.com/marcianotonattors/agente-playbook)"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}

# Seletores CSS para encontrar o conteúdo principal da página
CONTENT_SELECTORS = [
    "main",
    "article",
    '[role="main"]',
    ".content",
    ".main-content",
    ".article-body",
    ".doc-content",
    ".help-content",
    "#content",
    "#main",
    "#article",
]

# Tags/seletores de navegação e chrome para remover antes de extrair texto
NOISE_SELECTORS = [
    "nav", "header", "footer", "aside",
    ".nav", ".navbar", ".sidebar", ".breadcrumb", ".breadcrumbs",
    ".cookie-banner", ".cookie-notice",
    ".modal", ".overlay",
    ".advertisement", ".ads",
    ".feedback", ".rating",
    ".table-of-contents", ".toc",
    "script", "style", "noscript",
]


def count_tokens(text: str) -> int:
    return len(enc.encode(text))


def split_by_tokens(text: str, size: int, overlap: int) -> list[str]:
    tokens = enc.encode(text)
    chunks: list[str] = []
    start = 0
    while start < len(tokens):
        end = min(start + size, len(tokens))
        chunks.append(enc.decode(tokens[start:end]))
        if end == len(tokens):
            break
        start += size - overlap
    return chunks


def fetch_page(url: str, session: requests.Session, timeout: int = 20) -> str | None:
    try:
        resp = session.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
        ct = resp.headers.get("content-type", "")
        if "html" not in ct:
            logger.debug("Ignorando URL (não é HTML): %s [%s]", url, ct)
            return None
        return resp.text
    except requests.RequestException as exc:
        logger.warning("Erro ao buscar %s: %s", url, exc)
        return None


def extract_text_and_links(html: str, base_url: str) -> tuple[str, str, list[str]]:
    """
    Retorna (title, texto_principal, links_encontrados).
    Remove ruído de navegação e tenta isolar o conteúdo principal.
    """
    soup = BeautifulSoup(html, "lxml")

    title = ""
    title_tag = soup.find("title")
    if title_tag:
        title = title_tag.get_text(strip=True)

    # Remove noise elements
    for selector in NOISE_SELECTORS:
        for tag in soup.select(selector):
            tag.decompose()

    # Tenta encontrar área de conteúdo principal
    content_area = None
    for selector in CONTENT_SELECTORS:
        content_area = soup.select_one(selector)
        if content_area:
            break
    if not content_area:
        content_area = soup.find("body") or soup

    # Coleta links da área de conteúdo (antes de extrair texto)
    base_domain = urlparse(base_url).netloc
    found_links: list[str] = []
    seen_links: set[str] = set()
    for a_tag in content_area.find_all("a", href=True):
        href = a_tag["href"].strip()
        if not href or href.startswith("#") or href.startswith("mailto:"):
            continue
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if parsed.netloc != base_domain or parsed.scheme not in ("http", "https"):
            continue
        clean = parsed._replace(fragment="").geturl()
        if clean not in seen_links:
            seen_links.add(clean)
            found_links.append(clean)

    # Extrai texto limpo
    text = content_area.get_text(separator="\n", strip=True)
    # Normaliza linhas em branco múltiplas
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    return title, text, found_links


def crawl(
    start_url: str,
    max_depth: int,
    max_pages: int,
    session: requests.Session,
    delay: float = 1.5,
) -> list[dict]:
    """
    BFS sobre o domínio a partir de start_url.
    Retorna lista de dicts com {url, title, text}.
    """
    queue: deque[tuple[str, int]] = deque([(start_url, 0)])
    visited: set[str] = set()
    pages: list[dict] = []
    base_domain = urlparse(start_url).netloc

    while queue and len(pages) < max_pages:
        url, depth = queue.popleft()
        if url in visited:
            continue
        visited.add(url)

        logger.info("[%d/%d] depth=%d  %s", len(pages) + 1, max_pages, depth, url)
        html = fetch_page(url, session)
        if not html:
            continue

        title, text, links = extract_text_and_links(html, url)

        if text.strip():
            pages.append({"url": url, "title": title, "text": text})

        if depth < max_depth:
            for link in links:
                parsed = urlparse(link)
                if parsed.netloc == base_domain and link not in visited:
                    queue.append((link, depth + 1))

        time.sleep(delay)

    logger.info("Crawl concluído: %d páginas coletadas.", len(pages))
    return pages


def pages_to_chunks(pages: list[dict]) -> list[dict]:
    chunks: list[dict] = []
    chunk_idx = 0

    for page in pages:
        url = page["url"]
        title = page["title"]
        text = page["text"]

        if not text.strip():
            continue

        # Prefixa o título para contextualizar o primeiro chunk
        full_text = f"# {title}\n\n{text}" if title else text
        text_chunks = split_by_tokens(full_text, CHUNK_SIZE, CHUNK_OVERLAP)

        for i, chunk_text in enumerate(text_chunks):
            chunks.append({
                "content": chunk_text,
                "chunk_type": "text",
                "chunk_index": chunk_idx,
                "page_number": None,
                "section": title or None,
                "image_path": None,
                "metadata": {
                    "url": url,
                    "page_title": title,
                    "chunk_in_page": i,
                },
            })
            chunk_idx += 1

    return chunks


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingere páginas web no knowledge base RAG via BFS crawling."
    )
    parser.add_argument("--url", required=True, help="URL inicial para ingerir")
    parser.add_argument("--name", required=True, help="Nome da fonte no knowledge base")
    parser.add_argument("--description", default=None, help="Descrição da fonte")
    parser.add_argument(
        "--depth", type=int, default=1,
        help="Profundidade de crawling: 0=só a URL inicial, 1=links diretos, 2=dois níveis (padrão: 1)",
    )
    parser.add_argument(
        "--max-pages", type=int, default=100,
        help="Máximo de páginas a coletar (padrão: 100)",
    )
    parser.add_argument(
        "--delay", type=float, default=1.5,
        help="Delay em segundos entre requisições para não sobrecarregar o servidor (padrão: 1.5)",
    )
    args = parser.parse_args()

    logger.info(
        "Iniciando ingestão: url=%s | depth=%d | max-pages=%d",
        args.url, args.depth, args.max_pages,
    )

    session = requests.Session()
    pages = crawl(args.url, args.depth, args.max_pages, session, args.delay)

    if not pages:
        logger.error("Nenhuma página coletada. Verifique a URL e tente novamente.")
        sys.exit(1)

    chunks = pages_to_chunks(pages)
    logger.info("Chunks gerados: %d (de %d páginas)", len(chunks), len(pages))

    source_id = upsert_source(
        name=args.name,
        source_type="url",
        filename=args.url,
        description=args.description,
    )
    logger.info("Source registrado: %s", source_id)

    delete_chunks_for_source(source_id)
    upsert_chunks(source_id, chunks)

    logger.info("Ingestão concluída: %d chunks de %d páginas.", len(chunks), len(pages))


if __name__ == "__main__":
    main()
