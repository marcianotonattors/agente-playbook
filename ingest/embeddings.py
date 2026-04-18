"""
Geração de embeddings via OpenAI text-embedding-3-small
e carga de chunks no Supabase.
"""

import os
import time
import logging
from typing import Any

from openai import OpenAI
from supabase import create_client, Client

logger = logging.getLogger(__name__)

_openai: OpenAI | None = None
_supabase: Client | None = None

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536


def _get_openai() -> OpenAI:
    global _openai
    if _openai is None:
        _openai = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    return _openai


def _get_supabase() -> Client:
    global _supabase
    if _supabase is None:
        _supabase = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_KEY"],
        )
    return _supabase


def generate_embedding(text: str, retries: int = 3) -> list[float]:
    """Gera embedding para um texto, com retry em caso de rate limit."""
    client = _get_openai()
    for attempt in range(retries):
        try:
            response = client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=text,
                dimensions=EMBEDDING_DIM,
            )
            return response.data[0].embedding
        except Exception as exc:
            if attempt == retries - 1:
                raise
            wait = 2 ** attempt
            logger.warning("Embedding falhou (%s), tentando em %ss…", exc, wait)
            time.sleep(wait)
    raise RuntimeError("Embedding não gerado após retries")


def upsert_source(
    name: str,
    source_type: str,
    filename: str | None = None,
    description: str | None = None,
    version: str | None = None,
) -> str:
    """
    Insere ou atualiza um registro em knowledge_sources.
    Retorna o UUID da fonte.
    """
    db = _get_supabase()
    payload: dict[str, Any] = {"name": name, "type": source_type}
    if filename:
        payload["filename"] = filename
    if description:
        payload["description"] = description
    if version:
        payload["version"] = version

    result = (
        db.table("knowledge_sources")
        .upsert(payload, on_conflict="name")
        .execute()
    )
    return result.data[0]["id"]


def delete_chunks_for_source(source_id: str) -> None:
    """Remove todos os chunks existentes de uma fonte antes de re-ingerir."""
    db = _get_supabase()
    db.table("knowledge_chunks").delete().eq("source_id", source_id).execute()


def upsert_chunks(source_id: str, chunks: list[dict]) -> None:
    """
    Recebe lista de chunks com campos:
      content, chunk_type, chunk_index, page_number, section, image_path, metadata
    Gera embedding para cada um e faz upsert no Supabase em lotes de 50.
    """
    db = _get_supabase()
    batch: list[dict] = []

    for i, chunk in enumerate(chunks):
        text = chunk["content"]
        embedding = generate_embedding(text)

        row: dict[str, Any] = {
            "source_id": source_id,
            "content": text,
            "embedding": embedding,
            "chunk_index": chunk.get("chunk_index", i),
            "chunk_type": chunk.get("chunk_type", "text"),
            "page_number": chunk.get("page_number"),
            "section": chunk.get("section"),
            "image_path": chunk.get("image_path"),
            "metadata": chunk.get("metadata", {}),
        }
        batch.append(row)

        if len(batch) >= 50:
            db.table("knowledge_chunks").insert(batch).execute()
            logger.info("Inseridos %d chunks…", len(batch))
            batch = []
            time.sleep(0.5)

    if batch:
        db.table("knowledge_chunks").insert(batch).execute()
        logger.info("Inseridos %d chunks (lote final).", len(batch))
