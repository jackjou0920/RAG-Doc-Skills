#!/usr/bin/env python3
"""
test_server.py — Smoke test for the Document RAG MCP Server tools.

Tests the three tools directly against the ChromaDB collection (no HTTP server
needed). Verifies search_docs, get_chunk, and get_document work end-to-end.

Usage:
    cd mcp-server
    python3 test_server.py
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.config import ChromaConfig
from src.chroma_client import ChromaClient
from src.tools import search_docs_tool, get_chunk_tool, get_document_tool


def show(title, raw):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)
    data = json.loads(raw)
    print(json.dumps(data, indent=2, ensure_ascii=False)[:1500])
    return data


async def main():
    config = ChromaConfig()
    client = ChromaClient(config)
    client.connect()
    print(f"Connected to collection '{config.collection}' — {client.count()} chunks")

    # 1) search_docs
    res = await search_docs_tool(
        query="What is CoWoS packaging?",
        top_k=5,
        file_type="pdf",
        client=client,
    )
    data = show("search_docs(query='What is CoWoS packaging?', file_type='pdf')", res)
    assert data["success"], "search_docs failed"
    assert data["count"] > 0, "search_docs returned no results"
    first_id = data["results"][0]["id"]
    first_source = data["results"][0]["source"]

    # 2) get_chunk (use an id from the search results)
    res = await get_chunk_tool(chunk_id=first_id, client=client)
    data = show(f"get_chunk(chunk_id='{first_id}')", res)
    assert data["success"], "get_chunk failed"
    assert data["id"] == first_id

    # 3) get_document (use the source from the search results)
    res = await get_document_tool(source=first_source, limit=10, client=client)
    data = show(f"get_document(source='{first_source}', limit=10)", res)
    assert data["success"], "get_document failed"
    assert data["count"] > 0

    # 4) error path: missing chunk
    res = await get_chunk_tool(chunk_id="does-not-exist::p0::text::0", client=client)
    data = json.loads(res)
    assert data["success"] is False and data["error_type"] == "DATA_ERROR"
    print("\n[OK] error path (missing chunk) returns DATA_ERROR as expected")

    print("\n" + "=" * 70)
    print("ALL TESTS PASSED ✅")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())