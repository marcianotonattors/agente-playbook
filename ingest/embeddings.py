"""
Geração de embeddings via OpenAI text-embedding-3-small
e carga de chunks no Supabase.
"""

import os
import time
import logging
from typing import Any

import voyageai
from supabase import create_client, Client

logger = logging.getLogger(__name__)

_voyage: voyageai.Client | None = None
_supabase: Client | None = None

EMBEDDING_MODEL = "voyage-3"
EMBEDDING_DIM = 1024


def _get_voyage() -> voyageai.Client:
    global _voyage
    if _voyage is None:
        _voyage = voyageai.Client(api_key=os.environ["VOYAGE_API_KEY"])
    return _voyage


def _get_supabase() -> Client:
    global _supabase
    if _supabase is None:
        _supabase = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_KEY"],
        )
    return _supabase


REQUESTS_PER_MINUTE = 3
_MIN_INTERVAL = 60.0 / REQUESTS_PER_MINUTE  # 20s entre chamadas
_last_request_time: float = 0.0


def generate_embedding(text: str, retries: int = 5) -> list[float]:
    global _last_request_time
    client = _get_voyage()

    for attempt in range(retries):
        # Throttle para respeitar 3 RPM
        elapsed = time.monotonic() - _last_request_time
        if elapsed < _MIN_INTERVAL:
            time.sleep(_MIN_INTERVAL - elapsed)

        try:
            _last_request_time = time.monotonic()
            result = client.embed([text], model=EMBEDDING_MODEL)
            return result.embeddings[0]
        except Exception as exc:
            if attempt == retries - 1:
                raise
            wait = min(2 ** attempt * 20, 120)
            logger.warning("Embedding falhou (%s), aguardando %ss…", exc, wait)
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
