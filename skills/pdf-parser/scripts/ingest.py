#!/usr/bin/env python3
"""
ingest.py — Extract PDFs, chunk them, and store into a ChromaDB collection.

Pipeline:
    PDF file(s) -> extract_pdf.extract_pdf() -> chunk.chunk_document() -> ChromaDB.add()

ChromaDB uses its default embedding function (all-MiniLM-L6-v2, local, free) unless
overridden. The collection is shared across PDF and PPTX skills via the `file_type`
metadata field, so a single MCP server can query both.

Usage:
    # Ingest all PDFs in a directory
    python ingest.py --input ./pdf/ --db ./chroma_db --collection documents

    # Ingest a single file, include char-level elements
    python ingest.py --input report.pdf --db ./chroma_db --include-chars

    # Reset the collection before ingesting
    python ingest.py --input ./pdf/ --db ./chroma_db --reset
"""

import argparse
import os
import sys

# Allow running as a script: make sibling modules importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from extract_pdf import extract_pdf  # noqa: E402
from chunk import chunk_document  # noqa: E402


def gather_pdfs(input_path: str):
    """Return a list of PDF file paths from a file or directory."""
    if os.path.isfile(input_path):
        return [input_path] if input_path.lower().endswith(".pdf") else []
    pdfs = []
    for root, _dirs, files in os.walk(input_path):
        for f in files:
            if f.lower().endswith(".pdf"):
                pdfs.append(os.path.join(root, f))
    return sorted(pdfs)


def get_collection(db_path: str, name: str, reset: bool):
    import chromadb

    client = chromadb.PersistentClient(path=db_path)
    if reset:
        try:
            client.delete_collection(name)
        except Exception:
            pass
    return client.get_or_create_collection(name=name, metadata={"hnsw:space": "cosine"})


def add_chunks(collection, chunks, batch_size: int = 256):
    """Add chunks to ChromaDB in batches (upsert by id)."""
    total = 0
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        collection.upsert(
            ids=[c["id"] for c in batch],
            documents=[c["document"] for c in batch],
            metadatas=[c["metadata"] for c in batch],
        )
        total += len(batch)
    return total


def main():
    ap = argparse.ArgumentParser(description="Ingest PDF(s) into ChromaDB for RAG.")
    ap.add_argument("--input", required=True, help="PDF file or directory of PDFs")
    ap.add_argument("--db", default="./chroma_db", help="ChromaDB persist dir (default: ./chroma_db)")
    ap.add_argument("--collection", default="documents", help="Collection name (default: documents)")
    ap.add_argument("--include-chars", action="store_true", help="Also ingest char-level elements")
    ap.add_argument("--max-chars", type=int, default=1000, help="Max chars per text chunk")
    ap.add_argument("--overlap", type=int, default=150, help="Overlap chars between text chunks")
    ap.add_argument("--reset", action="store_true", help="Delete & recreate collection first")
    args = ap.parse_args()

    pdfs = gather_pdfs(args.input)
    if not pdfs:
        print(f"ERROR: no PDF files found at {args.input}", file=sys.stderr)
        sys.exit(1)

    collection = get_collection(args.db, args.collection, args.reset)

    grand_total = 0
    for pdf_path in pdfs:
        print(f"[extract] {pdf_path}")
        doc = extract_pdf(pdf_path, include_chars=args.include_chars)
        chunks = chunk_document(doc, max_chars=args.max_chars, overlap=args.overlap)
        n = add_chunks(collection, chunks)
        grand_total += n
        print(f"  -> {doc['n_pages']} pages, {doc['n_elements']} elements, {n} chunks ingested")

    print(f"\nDone. Ingested {grand_total} chunks from {len(pdfs)} PDF(s) "
          f"into collection '{args.collection}' at '{args.db}'.")
    print(f"Collection now holds {collection.count()} total chunks.")


if __name__ == "__main__":
    main()