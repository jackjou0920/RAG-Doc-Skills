"""
MCP tool implementations for the Document RAG MCP Server.

Three tools query the ChromaDB collection built by the pdf-parser / pptx-parser
skills. There is NO authentication and NO audit logging — these functions are
called directly from server.py.

Tools:
  - search_docs_tool   : semantic search with optional metadata filters
  - get_chunk_tool      : fetch a single chunk by id
  - get_document_tool   : fetch all chunks for a source file
"""

from typing import Optional
from fastmcp.server.context import Context

from src.models import (
    SearchDocsInput,
    SearchDocsOutput,
    Hit,
    GetChunkInput,
    GetChunkOutput,
    GetDocumentInput,
    GetDocumentOutput,
    ChunkRecord,
    ErrorResponse,
)
from src.chroma_client import ChromaClient


def _classify_error(msg: str) -> str:
    low = msg.lower()
    if "connect" in low or "path does not exist" in low or "collection" in low:
        return "CONNECTION_ERROR"
    if "query" in low or "search" in low:
        return "QUERY_ERROR"
    return "DATA_ERROR"


async def search_docs_tool(
    query: str,
    top_k: int = 5,
    file_type: Optional[str] = None,
    element_type: Optional[str] = None,
    source: Optional[str] = None,
    ctx: Optional[Context] = None,
    client: Optional[ChromaClient] = None,
) -> str:
    """Semantic search over ingested document chunks."""
    if ctx:
        await ctx.info(f"search_docs: '{query[:80]}' top_k={top_k} "
                       f"file_type={file_type} element_type={element_type} source={source}")
    try:
        params = SearchDocsInput(
            query=query,
            top_k=top_k,
            file_type=file_type,
            element_type=element_type,
            source=source,
        )

        if client is None:
            return ErrorResponse(
                message="ChromaDB client not initialized",
                error_type="CONNECTION_ERROR",
            ).model_dump_json()

        hits = client.search(
            query=params.query,
            top_k=params.top_k,
            file_type=params.file_type,
            element_type=params.element_type,
            source=params.source,
        )

        if ctx:
            await ctx.info(f"search_docs: {len(hits)} hits")

        output = SearchDocsOutput(
            success=True,
            query=params.query,
            results=[Hit(**h) for h in hits],
            count=len(hits),
        )
        return output.model_dump_json()

    except ValueError as e:
        if ctx:
            await ctx.error(f"Validation error: {e}")
        return ErrorResponse(
            message=f"Invalid input: {e}", error_type="VALIDATION_ERROR"
        ).model_dump_json()
    except Exception as e:
        if ctx:
            await ctx.error(f"search_docs failed: {e}")
        return ErrorResponse(
            message=f"Search failed: {e}", error_type=_classify_error(str(e))
        ).model_dump_json()


async def get_chunk_tool(
    chunk_id: str,
    ctx: Optional[Context] = None,
    client: Optional[ChromaClient] = None,
) -> str:
    """Fetch a single chunk by its id."""
    if ctx:
        await ctx.info(f"get_chunk: {chunk_id}")
    try:
        params = GetChunkInput(chunk_id=chunk_id)

        if client is None:
            return ErrorResponse(
                message="ChromaDB client not initialized",
                error_type="CONNECTION_ERROR",
            ).model_dump_json()

        rec = client.get_chunk(params.chunk_id)
        if rec is None:
            if ctx:
                await ctx.warning(f"Chunk not found: {params.chunk_id}")
            return ErrorResponse(
                message=f"Chunk not found: {params.chunk_id}",
                error_type="DATA_ERROR",
            ).model_dump_json()

        output = GetChunkOutput(
            success=True,
            id=rec["id"],
            document=rec["document"],
            metadata=rec["metadata"],
        )
        return output.model_dump_json()

    except ValueError as e:
        if ctx:
            await ctx.error(f"Validation error: {e}")
        return ErrorResponse(
            message=f"Invalid input: {e}", error_type="VALIDATION_ERROR"
        ).model_dump_json()
    except Exception as e:
        if ctx:
            await ctx.error(f"get_chunk failed: {e}")
        return ErrorResponse(
            message=f"get_chunk failed: {e}", error_type=_classify_error(str(e))
        ).model_dump_json()


async def get_document_tool(
    source: str,
    element_type: Optional[str] = None,
    limit: int = 200,
    ctx: Optional[Context] = None,
    client: Optional[ChromaClient] = None,
) -> str:
    """Fetch all chunks for a source file, ordered by page."""
    if ctx:
        await ctx.info(f"get_document: {source} element_type={element_type} limit={limit}")
    try:
        params = GetDocumentInput(source=source, element_type=element_type, limit=limit)

        if client is None:
            return ErrorResponse(
                message="ChromaDB client not initialized",
                error_type="CONNECTION_ERROR",
            ).model_dump_json()

        records = client.get_document(
            source=params.source,
            element_type=params.element_type,
            limit=params.limit,
        )

        if not records:
            if ctx:
                await ctx.warning(f"No chunks found for source: {params.source}")
            return ErrorResponse(
                message=f"No chunks found for source: {params.source}",
                error_type="DATA_ERROR",
            ).model_dump_json()

        if ctx:
            await ctx.info(f"get_document: {len(records)} chunks")

        output = GetDocumentOutput(
            success=True,
            source=params.source,
            chunks=[ChunkRecord(**r) for r in records],
            count=len(records),
        )
        return output.model_dump_json()

    except ValueError as e:
        if ctx:
            await ctx.error(f"Validation error: {e}")
        return ErrorResponse(
            message=f"Invalid input: {e}", error_type="VALIDATION_ERROR"
        ).model_dump_json()
    except Exception as e:
        if ctx:
            await ctx.error(f"get_document failed: {e}")
        return ErrorResponse(
            message=f"get_document failed: {e}", error_type=_classify_error(str(e))
        ).model_dump_json()