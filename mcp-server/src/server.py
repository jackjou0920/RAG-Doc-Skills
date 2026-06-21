"""
Document RAG MCP Server

FastMCP server exposing three tools to query a ChromaDB vector store built by the
pdf-parser / pptx-parser skills:
  - search_docs(query, top_k, file_type, element_type, source)
  - get_chunk(chunk_id)
  - get_document(source, element_type, limit)

This server is a thin read-only query
layer over ChromaDB. The client is responsible for generating final answers.

Transport: streamable HTTP
Endpoint:  http://HOST:PORT/{MCP_PATH}/mcp
"""

import sys
import os

# Allow `from src...` imports when run as a script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from typing import Optional
from fastmcp import FastMCP
from fastmcp.server.context import Context
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import uvicorn

from src.config import ChromaConfig
from src.chroma_client import ChromaClient
from src.tools import search_docs_tool, get_chunk_tool, get_document_tool


SERVICE_NAME = "doc-rag-mcp"

# Initialize FastMCP server
mcp = FastMCP("Document RAG MCP Server")

# Globals
config: Optional[ChromaConfig] = None
client: Optional[ChromaClient] = None


@mcp.tool
async def search_docs(
    query: str,
    top_k: int = 5,
    file_type: str = None,
    element_type: str = None,
    source: str = None,
    ctx: Context = None,
) -> str:
    """
    Semantic search over ingested document chunks (PDF/PPTX) in ChromaDB.

    Performs vector similarity search and returns the most relevant chunks, each
    with its source file, page, element type, section path, and text content.
    Use the returned chunks as context to generate an answer on the client side.

    Args:
        query: Natural-language search query (required)
        top_k: Number of results to return (default 5, max 50)
        file_type: Optional filter — "pdf" or "pptx"
        element_type: Optional filter — text/header/table/title/body/notes
        source: Optional filter — exact source file name

    Returns:
        JSON string: { success, query, results: [{id, score, source, file_type,
        page, element_type, header_path, document}], count }

    Example:
        search_docs(query="What is CoWoS packaging?", top_k=5, file_type="pdf")
    """
    return await search_docs_tool(
        query=query,
        top_k=top_k,
        file_type=file_type,
        element_type=element_type,
        source=source,
        ctx=ctx,
        client=client,
    )


@mcp.tool
async def get_chunk(
    chunk_id: str,
    ctx: Context = None,
) -> str:
    """
    Retrieve a single chunk by its id (e.g. the id returned by search_docs).

    Returns the chunk's full text content and all of its metadata. Use this to
    inspect the complete content of a specific passage.

    Args:
        chunk_id: The chunk id, e.g. "report.pdf::p3::text::1" (required)

    Returns:
        JSON string: { success, id, document, metadata }

    Example:
        get_chunk(chunk_id="TSMC_Packaging_Technologies_public.pdf::p3::text::1")
    """
    return await get_chunk_tool(chunk_id=chunk_id, ctx=ctx, client=client)


@mcp.tool
async def get_document(
    source: str,
    element_type: str = None,
    limit: int = 200,
    ctx: Context = None,
) -> str:
    """
    Retrieve all chunks for a source document, ordered by page.

    Use this to reconstruct or review an entire document's content. Optionally
    filter to a single element type (e.g. only tables).

    Args:
        source: Source file name to fetch (required), e.g. "deck.pptx"
        element_type: Optional filter — text/header/table/title/body/notes
        limit: Max chunks to return (default 200, max 2000)

    Returns:
        JSON string: { success, source, chunks: [{id, page, element_type,
        header_path, document}], count }

    Example:
        get_document(source="Semiconductors-studymafia.pptx")
    """
    return await get_document_tool(
        source=source, element_type=element_type, limit=limit, ctx=ctx, client=client
    )


def initialize_server():
    """Load config and connect to ChromaDB before the server starts."""
    global config, client

    print("\n" + "=" * 60)
    print("Document RAG MCP Server")
    print("=" * 60)

    try:
        print("\nLoading configuration...")
        config = ChromaConfig()
        info = config.get_safe_info()
        print(f"  ChromaDB path: {info['db_path']}")
        print(f"  Collection:    {info['collection']}")

        print("\nConnecting to ChromaDB...")
        client = ChromaClient(config)
        client.connect()
        chunk_count = client.count()
        print(f"  ✓ Connected — collection '{config.collection}' holds {chunk_count} chunks")

        print("\nStarting MCP server with HTTP transport...")
        print("  Registered tools:")
        print("    - search_docs")
        print("    - get_chunk")
        print("    - get_document")

        host = info["host"]
        port = info["port"]
        mcp_path = info["mcp_path"]

        print("\nMCP server endpoints:")
        print(f"  MCP:     http://{host}:{port}/{mcp_path}/mcp")
        print("\nFastAPI endpoints:")
        print(f"  Health:  http://{host}:{port}/health")
        print(f"  Metrics: http://{host}:{port}/{mcp_path}/metrics")
        print("\nPress Ctrl+C to stop.")
        print("=" * 60 + "\n")

        return host, port, mcp_path
    except Exception as e:
        print(f"\nERROR: Failed to initialize server: {e}")
        print("=" * 60 + "\n")
        raise


def cleanup_server():
    """Shutdown message (ChromaDB PersistentClient needs no explicit close)."""
    print("\n" + "=" * 60)
    print("Shutting down Document RAG MCP Server...")
    print("=" * 60)
    print("Server stopped.")
    print("=" * 60 + "\n")


def create_app(mcp_path: str) -> FastAPI:
    """Create the FastAPI app and mount the MCP HTTP app under /{mcp_path}."""
    mcp_app = mcp.http_app(transport="streamable-http", stateless_http=True)

    app = FastAPI(
        title="Document RAG MCP Server",
        description="MCP server providing read-only ChromaDB search over ingested PDF/PPTX documents",
        version="1.0.0",
        lifespan=mcp_app.lifespan,
    )

    @app.get("/health")
    async def health_check():
        """Health check — verifies the ChromaDB collection is reachable."""
        if client is not None:
            try:
                count = client.count()
                return JSONResponse({
                    "status": "healthy",
                    "chromadb": "connected",
                    "collection": config.collection if config else None,
                    "chunks": count,
                    "service": SERVICE_NAME,
                })
            except Exception as e:
                return JSONResponse(
                    status_code=503,
                    content={
                        "status": "unhealthy",
                        "chromadb": "error",
                        "error": str(e),
                        "service": SERVICE_NAME,
                    },
                )
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "chromadb": "disconnected",
                "service": SERVICE_NAME,
            },
        )

    @app.get(f"/{mcp_path}/metrics")
    async def get_metrics():
        """Basic metrics — collection name and chunk count."""
        if client is not None:
            try:
                return JSONResponse({
                    "service": SERVICE_NAME,
                    "metrics": {
                        "collection": config.collection if config else None,
                        "chunks": client.count(),
                        "db_path": config.get_safe_info()["db_path"] if config else None,
                    },
                })
            except Exception as e:
                return JSONResponse(
                    status_code=503,
                    content={"service": SERVICE_NAME, "error": str(e)},
                )
        return JSONResponse(
            status_code=503,
            content={"service": SERVICE_NAME, "error": "Client not initialized"},
        )

    app.mount(f"/{mcp_path}", mcp_app)
    return app


if __name__ == "__main__":
    try:
        host, port, mcp_path = initialize_server()
        app = create_app(mcp_path)
        uvicorn.run(app, host=host, port=port, log_level="info", ws="websockets-sansio")
    except KeyboardInterrupt:
        print("\n\nReceived interrupt signal...")
    except Exception as e:
        print(f"\n\nFATAL ERROR: {e}")
    finally:
        cleanup_server()