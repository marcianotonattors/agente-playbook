"""
Diagnóstico: lista todos os block types de uma página Notion recursivamente.

Uso:
  NOTION_TOKEN=... python ingest/debug_blocks.py --page-id PAGE_ID
"""
import argparse
import os
from collections import Counter
from notion_client import Client

def dump_blocks(notion, block_id, depth=0, max_depth=4):
    try:
        resp = notion.blocks.children.list(block_id=block_id, page_size=100)
    except Exception as e:
        print("  " * depth + f"[ERRO ao buscar filhos: {e}]")
        return

    for block in resp.get("results", []):
        btype = block.get("type", "?")
        has_ch = block.get("has_children", False)
        bid = block["id"]

        inner = block.get(btype, {})
        if isinstance(inner, dict):
            rt = inner.get("rich_text", [])
            text = "".join(x.get("plain_text", "") for x in rt)[:60]
            title = inner.get("title", "")[:60]
            name = inner.get("name", "")[:60]
            url = inner.get("url", "") or inner.get("external", {}).get("url", "")[:60]
            label = text or title or name or url or ""
        else:
            label = ""

        indent = "  " * depth
        print(f"{indent}[{btype}] has_children={has_ch}  {label!r}")

        if has_ch and depth < max_depth:
            dump_blocks(notion, bid, depth + 1, max_depth)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--page-id", required=True)
    parser.add_argument("--max-depth", type=int, default=4)
    args = parser.parse_args()

    notion = Client(auth=os.environ["NOTION_TOKEN"])
    print(f"=== Blocos de {args.page_id} ===\n")
    dump_blocks(notion, args.page_id, max_depth=args.max_depth)

if __name__ == "__main__":
    main()
