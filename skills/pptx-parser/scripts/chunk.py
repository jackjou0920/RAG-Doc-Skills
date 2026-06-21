#!/usr/bin/env python3
"""
chunk.py — Turn a structured extraction document (from extract_pdf.py) into
RAG-ready chunks, each with text + metadata for ChromaDB.

Chunking strategy:
  - table  : 1 chunk per table (kept whole — splitting tables hurts retrieval)
  - header : merged into the following text's header_path (not a standalone chunk
             unless it has no body underneath)
  - text   : consecutive text blocks under the same header_path are grouped, then
             split into ~max_chars windows with small overlap
  - char   : 1 chunk per char (only when extracted; rarely useful for semantic search)

Each chunk dict:
  {
    "id": "<source>::p<page>::<element_type>::<n>",
    "document": "<text content>",
    "metadata": { source, file_type, page, element_type, header_path, bbox, font_size }
  }
"""

from typing import Any, Dict, List, Optional


def _meta(doc_meta: Dict[str, Any], el: Dict[str, Any]) -> Dict[str, Any]:
    """Build a ChromaDB-safe metadata dict (only str/int/float/bool values)."""
    m: Dict[str, Any] = {
        "source": doc_meta["source"],
        "file_type": doc_meta["file_type"],
        "page": int(el.get("page", 0)),
        "element_type": el.get("element_type", "text"),
        "header_path": el.get("header_path", "") or "",
    }
    if el.get("bbox"):
        m["bbox"] = el["bbox"]
    fs = el.get("font_size")
    if isinstance(fs, (int, float)):
        m["font_size"] = float(fs)
    if el.get("element_type") == "table":
        m["n_rows"] = int(el.get("n_rows", 0))
        m["n_cols"] = int(el.get("n_cols", 0))
    return m


def _split_text(text: str, max_chars: int, overlap: int) -> List[str]:
    """Split a long text into overlapping windows by character length, on word boundaries."""
    text = text.strip()
    if len(text) <= max_chars:
        return [text] if text else []
    words = text.split()
    chunks: List[str] = []
    cur: List[str] = []
    cur_len = 0
    for w in words:
        add = len(w) + (1 if cur else 0)
        if cur_len + add > max_chars and cur:
            chunks.append(" ".join(cur))
            # build overlap tail
            if overlap > 0:
                tail: List[str] = []
                tail_len = 0
                for tw in reversed(cur):
                    if tail_len + len(tw) + 1 > overlap:
                        break
                    tail.insert(0, tw)
                    tail_len += len(tw) + 1
                cur = tail
                cur_len = tail_len
            else:
                cur = []
                cur_len = 0
        cur.append(w)
        cur_len += add
    if cur:
        chunks.append(" ".join(cur))
    return chunks


def chunk_document(
    doc: Dict[str, Any],
    max_chars: int = 1000,
    overlap: int = 150,
    min_chars: int = 1,
) -> List[Dict[str, Any]]:
    """Convert an extraction document into a list of chunk dicts."""
    source = doc["source"]
    chunks: List[Dict[str, Any]] = []
    counters: Dict[str, int] = {}

    def next_id(page: int, etype: str) -> str:
        key = f"{page}:{etype}"
        n = counters.get(key, 0)
        counters[key] = n + 1
        return f"{source}::p{page}::{etype}::{n}"

    # Group consecutive text blocks sharing the same (page, header_path)
    pending_text: List[Dict[str, Any]] = []

    def flush_text():
        if not pending_text:
            return
        page = pending_text[0]["page"]
        header_path = pending_text[0].get("header_path", "")
        # Preserve the source element type (PDF "text" vs PPTX "body")
        etype = pending_text[0].get("element_type", "text")
        combined = "\n".join(b["text"] for b in pending_text).strip()
        base_meta_el = {
            "page": page,
            "element_type": etype,
            "header_path": header_path,
            "bbox": pending_text[0].get("bbox", ""),
            "font_size": pending_text[0].get("font_size"),
        }
        for piece in _split_text(combined, max_chars, overlap):
            if len(piece) < min_chars:
                continue
            cid = next_id(page, etype)
            chunks.append(
                {
                    "id": cid,
                    "document": piece,
                    "metadata": _meta(doc, base_meta_el),
                }
            )
        pending_text.clear()

    # Element types that are flowing body text (grouped + windowed)
    TEXT_TYPES = {"text", "body"}
    # Element types that become standalone chunks (one per element)
    STANDALONE_TYPES = {"header", "title", "notes"}

    for el in doc["elements"]:
        etype = el.get("element_type", "text")
        if etype in TEXT_TYPES:
            # flush if header_path or page changed
            if pending_text and (
                pending_text[0].get("header_path", "") != el.get("header_path", "")
                or pending_text[0]["page"] != el["page"]
            ):
                flush_text()
            pending_text.append(el)
        elif etype in STANDALONE_TYPES:
            # headers/titles/notes become standalone chunks (useful for section lookups)
            flush_text()
            txt = el.get("text", "").strip()
            if txt:
                cid = next_id(el["page"], etype)
                chunks.append(
                    {
                        "id": cid,
                        "document": txt,
                        "metadata": _meta(doc, el),
                    }
                )
        elif etype == "table":
            flush_text()
            txt = el.get("text", "").strip()
            if txt:
                cid = next_id(el["page"], "table")
                # Prefix with header context to aid retrieval
                hp = el.get("header_path", "")
                doc_text = (f"[Table under: {hp}]\n" if hp else "") + txt
                chunks.append(
                    {
                        "id": cid,
                        "document": doc_text,
                        "metadata": _meta(doc, el),
                    }
                )
        elif etype == "char":
            flush_text()
            cid = next_id(el["page"], "char")
            chunks.append(
                {
                    "id": cid,
                    "document": el.get("text", ""),
                    "metadata": _meta(doc, el),
                }
            )
    flush_text()
    return chunks
