#!/usr/bin/env python3
"""
query.py — Semantic search (RETRIEVAL ONLY) against the ChromaDB collection built
by ingest.py.

This is a local test/inspection tool to verify that ingestion worked and that
relevant chunks are retrievable. It performs vector similarity search (cosine) over
ingested PDF/PPTX chunks, with optional metadata filtering.

NOTE: This skill is responsible for the RETRIEVAL half of RAG only
(extract -> chunk -> embed -> vector DB -> search). Answer GENERATION is done by
the MCP server's client (see step 3), not here.

Usage:
    # Basic semantic search
    python query.py --db ./chroma_db --collection documents \
        --query "What is CoWoS packaging?" --top-k 5

    # Filter to tables only, from a specific source file
    python query.py --db ./chroma_db --collection documents \
        --query "wafer yield" --top-k 5 \
        --filter '{"element_type": "table"}'

    # JSON output (for piping into other tools)
    python query.py --db ./chroma_db --collection documents \
        --query "lithography" --json
"""

import argparse
import json
import sys


def get_collection(db_path: str, name: str):
    import chromadb

    client = chromadb.PersistentClient(path=db_path)
    return client.get_collection(name=name)


def search(collection, query: str, top_k: int, where: dict | None):
    kwargs = {"query_texts": [query], "n_results": top_k}
    if where:
        kwargs["where"] = where
    res = collection.query(**kwargs)
    hits = []
    docs = res.get("documents", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    dists = res.get("distances", [[]])[0]
    ids = res.get("ids", [[]])[0]
    for i in range(len(docs)):
        hits.append(
            {
                "rank": i + 1,
                "id": ids[i],
                "distance": round(float(dists[i]), 4),
                "score": round(1.0 - float(dists[i]), 4),  # cosine similarity
                "metadata": metas[i],
                "document": docs[i],
            }
        )
    return hits


def main():
    ap = argparse.ArgumentParser(description="Semantic search over ingested documents.")
    ap.add_argument("--db", default="./chroma_db", help="ChromaDB persist dir")
    ap.add_argument("--collection", default="documents", help="Collection name")
    ap.add_argument("--query", required=True, help="Natural-language query")
    ap.add_argument("--top-k", type=int, default=5, help="Number of results")
    ap.add_argument("--filter", help='Metadata filter as JSON, e.g. \'{"element_type":"table"}\'')
    ap.add_argument("--json", action="store_true", help="Output raw JSON")
    args = ap.parse_args()

    where = None
    if args.filter:
        try:
            where = json.loads(args.filter)
        except json.JSONDecodeError as e:
            print(f"ERROR: --filter is not valid JSON: {e}", file=sys.stderr)
            sys.exit(1)

    try:
        collection = get_collection(args.db, args.collection)
    except Exception as e:
        print(f"ERROR: cannot open collection '{args.collection}' at '{args.db}': {e}",
              file=sys.stderr)
        sys.exit(1)

    hits = search(collection, args.query, args.top_k, where)

    if args.json:
        print(json.dumps({"query": args.query, "results": hits}, ensure_ascii=False, indent=2))
        return

    if not hits:
        print("No results.")
        return

    print(f"\nQuery: {args.query}")
    print(f"Top {len(hits)} results:\n" + "=" * 70)
    for h in hits:
        m = h["metadata"]
        loc = f"{m.get('source','?')} p{m.get('page','?')} [{m.get('element_type','?')}]"
        hp = m.get("header_path", "")
        print(f"\n#{h['rank']}  score={h['score']}  {loc}")
        if hp:
            print(f"   section: {hp}")
        snippet = h["document"].replace("\n", " ")
        if len(snippet) > 300:
            snippet = snippet[:300] + " ..."
        print(f"   {snippet}")
    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()