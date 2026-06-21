"""
ChromaDB client for the Document RAG MCP Server.

Wraps a ChromaDB PersistentClient + collection and exposes the three operations
the tools need: semantic search, get a single chunk by id, and get all chunks for
a source document.

The collection is created by the pdf-parser / pptx-parser skills using ChromaDB's
default embedding function (all-MiniLM-L6-v2). Querying with `query_texts` here
automatically uses the same embedding function bound to the collection.
"""

import os
from typing import Optional, List, Dict, Any


class ChromaClient:
    """Thin wrapper around a ChromaDB collection for read-only RAG queries."""

    def __init__(self, config):
        self.config = config
        self._client = None
        self._collection = None

    def connect(self):
        """Open the persistent client and load the collection."""
        import chromadb

        db_path = os.path.abspath(self.config.db_path)
        if not os.path.isdir(db_path):
            raise ConnectionError(
                f"ChromaDB path does not exist: {db_path}. "
                f"Run the pdf-parser / pptx-parser ingest scripts first."
            )

        self._client = chromadb.PersistentClient(path=db_path)
        # Raises if the collection does not exist
        self._collection = self._client.get_collection(name=self.config.collection)
        return self._collection

    @property
    def collection(self):
        if self._collection is None:
            self.connect()
        return self._collection

    def count(self) -> int:
        """Total number of chunks in the collection (used for health checks)."""
        return self.collection.count()

    @staticmethod
    def _build_where(filters: Dict[str, Optional[str]]) -> Optional[dict]:
        """Build a ChromaDB `where` clause from a dict of optional equality filters."""
        clauses = [{k: v} for k, v in filters.items() if v]
        if not clauses:
            return None
        if len(clauses) == 1:
            return clauses[0]
        return {"$and": clauses}

    def search(
        self,
        query: str,
        top_k: int,
        file_type: Optional[str] = None,
        element_type: Optional[str] = None,
        source: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Semantic similarity search with optional metadata filtering."""
        where = self._build_where(
            {"file_type": file_type, "element_type": element_type, "source": source}
        )
        kwargs: Dict[str, Any] = {"query_texts": [query], "n_results": top_k}
        if where:
            kwargs["where"] = where

        res = self.collection.query(**kwargs)
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        ids = (res.get("ids") or [[]])[0]

        hits: List[Dict[str, Any]] = []
        for i in range(len(docs)):
            m = metas[i] or {}
            hits.append(
                {
                    "id": ids[i],
                    "score": round(1.0 - float(dists[i]), 4),
                    "source": m.get("source", ""),
                    "file_type": m.get("file_type", ""),
                    "page": int(m.get("page", 0)),
                    "element_type": m.get("element_type", ""),
                    "header_path": m.get("header_path", ""),
                    "document": docs[i],
                }
            )
        return hits

    def get_chunk(self, chunk_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single chunk by its id. Returns None if not found."""
        res = self.collection.get(ids=[chunk_id], include=["documents", "metadatas"])
        ids = res.get("ids") or []
        if not ids:
            return None
        docs = res.get("documents") or [""]
        metas = res.get("metadatas") or [{}]
        return {
            "id": ids[0],
            "document": docs[0] if docs else "",
            "metadata": metas[0] if metas else {},
        }

    def get_document(
        self,
        source: str,
        element_type: Optional[str] = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        """Fetch all chunks for a given source file, ordered by page then id."""
        where = self._build_where({"source": source, "element_type": element_type})
        res = self.collection.get(
            where=where,
            limit=limit,
            include=["documents", "metadatas"],
        )
        ids = res.get("ids") or []
        docs = res.get("documents") or []
        metas = res.get("metadatas") or []

        records: List[Dict[str, Any]] = []
        for i in range(len(ids)):
            m = metas[i] or {}
            records.append(
                {
                    "id": ids[i],
                    "page": int(m.get("page", 0)),
                    "element_type": m.get("element_type", ""),
                    "header_path": m.get("header_path", ""),
                    "document": docs[i] if i < len(docs) else "",
                }
            )
        # Order by page, then by id (stable id includes element type + index)
        records.sort(key=lambda r: (r["page"], r["id"]))
        return records