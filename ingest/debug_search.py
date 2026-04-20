"""
Diagnóstico do Knowledge Base: mostra chunks existentes e testa busca semântica.

Uso:
  cd ingest
  SUPABASE_URL=... SUPABASE_SERVICE_KEY=... VOYAGE_API_KEY=... python debug_search.py

  # Ou com .env na raiz do projeto:
  python debug_search.py
"""

import os
import sys
from pathlib import Path

# Carrega .env se existir
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

sys.path.insert(0, str(Path(__file__).parent))
from embeddings import _get_supabase, generate_embedding


def show_sources():
    db = _get_supabase()
    result = db.table("knowledge_sources").select("id, name, type, created_at").execute()
    print("\n=== FONTES ===")
    for s in result.data:
        count = db.table("knowledge_chunks").select("id", count="exact").eq("source_id", s["id"]).execute()
        print(f"  [{s['type']}] {s['name']}  →  {count.count} chunks  (id: {s['id'][:8]}...)")


def show_sample_chunks(source_name: str, n: int = 5):
    db = _get_supabase()
    src = db.table("knowledge_sources").select("id").eq("name", source_name).execute()
    if not src.data:
        print(f"\nFonte '{source_name}' não encontrada.")
        return
    source_id = src.data[0]["id"]

    chunks = (
        db.table("knowledge_chunks")
        .select("chunk_index, chunk_type, section, content")
        .eq("source_id", source_id)
        .order("chunk_index")
        .limit(n)
        .execute()
    )
    print(f"\n=== PRIMEIROS {n} CHUNKS de '{source_name}' ===")
    for c in chunks.data:
        preview = c["content"][:200].replace("\n", " ")
        print(f"  [{c['chunk_index']:03d}] ({c['chunk_type']}) [{c['section'] or '—'}]")
        print(f"       {preview}")
        print()


def test_search(query: str, min_similarity: float = 0.3, match_count: int = 5):
    print(f"\n=== BUSCA: '{query}' (threshold={min_similarity}) ===")
    embedding = generate_embedding(query)
    db = _get_supabase()
    result = db.rpc("search_chunks", {
        "query_embedding": embedding,
        "match_count": match_count,
        "min_similarity": min_similarity,
    }).execute()

    if not result.data:
        print("  Nenhum resultado.")
        return

    for r in result.data:
        preview = r["content"][:200].replace("\n", " ")
        print(f"  sim={r['similarity']:.3f}  [{r['source_name']}]  seção: {r['section'] or '—'}")
        print(f"    {preview}")
        print()


def test_keyword(query: str):
    db = _get_supabase()
    keywords = [w for w in query.lower().split() if len(w) > 3][:4]
    print(f"\n=== KEYWORD: palavras={keywords} ===")
    if not keywords:
        print("  Nenhuma palavra-chave.")
        return
    filt = ",".join(f"content.ilike.%{k}%" for k in keywords)
    result = db.from_("knowledge_chunks").select("content, section, source_id").or_(filt).limit(5).execute()
    if not result.data:
        print("  Nenhum resultado.")
        return
    for r in result.data:
        preview = r["content"][:200].replace("\n", " ")
        print(f"  seção: {r['section'] or '—'}")
        print(f"    {preview}")
        print()


if __name__ == "__main__":
    show_sources()

    # Mostra amostra dos chunks HTML
    show_sample_chunks("Playbook da Coordenação BIM")

    # Testa busca semântica com threshold baixo
    test_search("O que é Etapa 1 do curso?", min_similarity=0.1)
    test_search("modelos disciplinares BIM", min_similarity=0.1)

    # Testa busca por palavras-chave
    test_keyword("Etapa 1 alinhamento modelos")
