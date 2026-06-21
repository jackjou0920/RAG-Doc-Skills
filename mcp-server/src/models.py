"""
Pydantic models for the Document RAG MCP Server.

Defines input validation and output serialization for the three tools:
  - search_docs
  - get_chunk
  - get_document
"""

from typing import Optional, List, Any, Dict
from pydantic import BaseModel, Field, field_validator


# ─────────────────────────────────────────────
# Shared
# ─────────────────────────────────────────────

class Hit(BaseModel):
    """A single search result chunk."""
    id: str = Field(..., description="Stable chunk id")
    score: float = Field(..., description="Cosine similarity (1 - distance), higher is better")
    source: str = Field("", description="Source file name")
    file_type: str = Field("", description="pdf or pptx")
    page: int = Field(0, description="Page / slide index (0-based)")
    element_type: str = Field("", description="text/header/table/title/body/notes")
    header_path: str = Field("", description="Section breadcrumb")
    document: str = Field("", description="Chunk text content")


class ChunkRecord(BaseModel):
    """A chunk returned by get_document (full document text + metadata)."""
    id: str = Field(..., description="Stable chunk id")
    page: int = Field(0, description="Page / slide index (0-based)")
    element_type: str = Field("", description="text/header/table/title/body/notes")
    header_path: str = Field("", description="Section breadcrumb")
    document: str = Field("", description="Chunk text content")


# ─────────────────────────────────────────────
# search_docs
# ─────────────────────────────────────────────

class SearchDocsInput(BaseModel):
    """Input model for search_docs tool."""
    query: str = Field(..., description="Natural-language search query")
    top_k: int = Field(5, description="Number of results to return", ge=1, le=50)
    file_type: Optional[str] = Field(None, description="Filter by file type: 'pdf' or 'pptx'")
    element_type: Optional[str] = Field(
        None, description="Filter by element type: text/header/table/title/body/notes"
    )
    source: Optional[str] = Field(None, description="Filter by exact source file name")

    @field_validator("query")
    @classmethod
    def _validate_query(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("query cannot be empty")
        return v.strip()


class SearchDocsOutput(BaseModel):
    """Output model for search_docs tool."""
    success: bool = Field(..., description="Whether the search succeeded")
    query: str = Field(..., description="The query that was searched")
    results: List[Hit] = Field(default_factory=list, description="Ranked search hits")
    count: int = Field(0, description="Number of results returned")
    message: Optional[str] = Field(None, description="Error message if failed")


# ─────────────────────────────────────────────
# get_chunk
# ─────────────────────────────────────────────

class GetChunkInput(BaseModel):
    """Input model for get_chunk tool."""
    chunk_id: str = Field(..., description="The chunk id to retrieve")

    @field_validator("chunk_id")
    @classmethod
    def _validate_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("chunk_id cannot be empty")
        return v.strip()


class GetChunkOutput(BaseModel):
    """Output model for get_chunk tool."""
    success: bool = Field(..., description="Whether the chunk was found")
    id: str = Field("", description="Chunk id")
    document: str = Field("", description="Full chunk text content")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="All chunk metadata")
    message: Optional[str] = Field(None, description="Error message if not found")


# ─────────────────────────────────────────────
# get_document
# ─────────────────────────────────────────────

class GetDocumentInput(BaseModel):
    """Input model for get_document tool."""
    source: str = Field(..., description="Source file name to retrieve all chunks for")
    element_type: Optional[str] = Field(
        None, description="Optional filter by element type"
    )
    limit: int = Field(200, description="Max chunks to return", ge=1, le=2000)

    @field_validator("source")
    @classmethod
    def _validate_source(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("source cannot be empty")
        return v.strip()


class GetDocumentOutput(BaseModel):
    """Output model for get_document tool."""
    success: bool = Field(..., description="Whether the document was found")
    source: str = Field("", description="Source file name")
    chunks: List[ChunkRecord] = Field(default_factory=list, description="Ordered chunks")
    count: int = Field(0, description="Number of chunks returned")
    message: Optional[str] = Field(None, description="Error message if failed")


# ─────────────────────────────────────────────
# Errors
# ─────────────────────────────────────────────

class ErrorResponse(BaseModel):
    """Standard error response."""
    success: bool = Field(False, description="Always False for errors")
    message: str = Field(..., description="Error message")
    error_type: str = Field(
        ..., description="VALIDATION_ERROR / CONNECTION_ERROR / QUERY_ERROR / DATA_ERROR"
    )
    details: Optional[dict] = Field(None, description="Additional error details")