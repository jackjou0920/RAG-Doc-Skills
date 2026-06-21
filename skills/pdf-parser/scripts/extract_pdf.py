#!/usr/bin/env python3
"""
extract_pdf.py — Extract structured elements (text, header, table, char) from a PDF.

Uses:
  - PyMuPDF (fitz)  : text blocks with bbox + font size (for text/header detection)
  - pdfplumber      : table extraction (most reliable table detector)

Output: a structured JSON document of "elements", each carrying rich metadata
(page, element_type, bbox, font_size, header level, etc.) suitable for chunking
and ingestion into a vector DB (ChromaDB).

Usage:
    python extract_pdf.py --input report.pdf --output report.json [--include-chars]
"""

import argparse
import json
import os
import statistics
import sys
from typing import Any, Dict, List, Optional


def _round_bbox(bbox) -> str:
    """Serialize a bbox tuple/list to a compact string 'x0,y0,x1,y1'."""
    try:
        return ",".join(str(round(float(v), 1)) for v in bbox)
    except Exception:
        return ""


def extract_tables(pdf_path: str) -> Dict[int, List[Dict[str, Any]]]:
    """Extract tables per page using pdfplumber. Returns {page_index: [table_dict,...]}."""
    import pdfplumber

    tables_by_page: Dict[int, List[Dict[str, Any]]] = {}
    with pdfplumber.open(pdf_path) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            page_tables = []
            try:
                found = page.find_tables()
            except Exception:
                found = []
            for t_idx, table in enumerate(found):
                try:
                    rows = table.extract()
                except Exception:
                    continue
                if not rows:
                    continue
                # Clean None -> "" and stringify
                cleaned = [[("" if c is None else str(c).strip()) for c in row] for row in rows]
                page_tables.append(
                    {
                        "table_index": t_idx,
                        "bbox": _round_bbox(table.bbox) if table.bbox else "",
                        "n_rows": len(cleaned),
                        "n_cols": max((len(r) for r in cleaned), default=0),
                        "rows": cleaned,
                        "markdown": _rows_to_markdown(cleaned),
                    }
                )
            if page_tables:
                tables_by_page[page_idx] = page_tables
    return tables_by_page


def _rows_to_markdown(rows: List[List[str]]) -> str:
    """Convert table rows to a GitHub-flavored markdown table string."""
    if not rows:
        return ""
    n_cols = max(len(r) for r in rows)
    norm = [r + [""] * (n_cols - len(r)) for r in rows]
    header = norm[0]
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join(["---"] * n_cols) + " |"]
    for r in norm[1:]:
        lines.append("| " + " | ".join(r) + " |")
    return "\n".join(lines)


def extract_text_blocks(pdf_path: str, include_chars: bool = False):
    """
    Extract text blocks (with font size) per page using PyMuPDF.
    Returns (blocks_by_page, char_records, all_font_sizes).
    """
    import fitz  # PyMuPDF

    blocks_by_page: Dict[int, List[Dict[str, Any]]] = {}
    char_records: List[Dict[str, Any]] = []
    all_font_sizes: List[float] = []

    doc = fitz.open(pdf_path)
    for page_idx in range(len(doc)):
        page = doc[page_idx]
        data = page.get_text("dict")
        page_blocks = []
        for block in data.get("blocks", []):
            if block.get("type") != 0:  # 0 = text block (1 = image)
                continue
            block_text_parts = []
            block_sizes = []
            is_bold = False
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    span_text = span.get("text", "")
                    if not span_text.strip():
                        continue
                    block_text_parts.append(span_text)
                    size = float(span.get("size", 0.0))
                    block_sizes.append(size)
                    all_font_sizes.append(size)
                    font_name = span.get("font", "")
                    if "bold" in font_name.lower() or "black" in font_name.lower():
                        is_bold = True
                    if include_chars:
                        for ch in span_text:
                            if ch.strip():
                                char_records.append(
                                    {
                                        "page": page_idx,
                                        "char": ch,
                                        "font": font_name,
                                        "font_size": round(size, 1),
                                        "bbox": _round_bbox(span.get("bbox", [])),
                                    }
                                )
            text = " ".join(block_text_parts).strip()
            if not text:
                continue
            avg_size = round(statistics.mean(block_sizes), 1) if block_sizes else 0.0
            page_blocks.append(
                {
                    "text": text,
                    "bbox": _round_bbox(block.get("bbox", [])),
                    "font_size": avg_size,
                    "is_bold": is_bold,
                }
            )
        blocks_by_page[page_idx] = page_blocks
    doc.close()
    return blocks_by_page, char_records, all_font_sizes


def classify_headers(blocks_by_page, all_font_sizes):
    """
    Determine header levels by font size relative to the body font size.

    The most common font size = body text. Sizes larger than body are headers,
    bucketed into h1/h2/h3 by descending size.
    """
    if not all_font_sizes:
        body_size = 0.0
        header_sizes: List[float] = []
    else:
        # Mode = most frequent rounded size = body text
        rounded = [round(s) for s in all_font_sizes]
        try:
            body_size = float(statistics.mode(rounded))
        except statistics.StatisticsError:
            body_size = float(statistics.median(rounded))
        # Distinct sizes strictly larger than body become header tiers
        larger = sorted({round(s) for s in all_font_sizes if round(s) > body_size}, reverse=True)
        header_sizes = larger[:3]  # up to 3 header tiers

    def level_for(size: float, is_bold: bool) -> Optional[int]:
        rs = round(size)
        for i, hs in enumerate(header_sizes):
            if rs >= hs:
                return i + 1  # 1=h1 (largest)
        # Bold text at body size acts as a minor header
        if is_bold and rs >= body_size:
            return min(len(header_sizes) + 1, 4)
        return None

    for blocks in blocks_by_page.values():
        for b in blocks:
            lvl = level_for(b["font_size"], b.get("is_bold", False))
            b["header_level"] = lvl
            b["element_type"] = "header" if lvl else "text"
    return body_size, header_sizes


def assemble_elements(blocks_by_page, tables_by_page, char_records, include_chars):
    """Merge text/header blocks, tables, and (optional) chars into one ordered element list."""
    elements: List[Dict[str, Any]] = []
    header_stack: List[str] = []  # track current header path

    all_pages = sorted(set(blocks_by_page) | set(tables_by_page))
    for page_idx in all_pages:
        blocks = blocks_by_page.get(page_idx, [])
        for b in blocks:
            etype = b["element_type"]
            if etype == "header":
                lvl = b.get("header_level", 1) or 1
                # Truncate stack to (lvl-1), then push this header
                header_stack[:] = header_stack[: lvl - 1]
                header_stack.append(b["text"])
            elements.append(
                {
                    "page": page_idx,
                    "element_type": etype,
                    "text": b["text"],
                    "bbox": b["bbox"],
                    "font_size": b["font_size"],
                    "header_level": b.get("header_level"),
                    "header_path": " > ".join(header_stack) if header_stack else "",
                }
            )
        # Tables for this page
        for t in tables_by_page.get(page_idx, []):
            elements.append(
                {
                    "page": page_idx,
                    "element_type": "table",
                    "text": t["markdown"],
                    "bbox": t["bbox"],
                    "font_size": None,
                    "header_level": None,
                    "header_path": " > ".join(header_stack) if header_stack else "",
                    "n_rows": t["n_rows"],
                    "n_cols": t["n_cols"],
                }
            )

    if include_chars:
        for c in char_records:
            elements.append(
                {
                    "page": c["page"],
                    "element_type": "char",
                    "text": c["char"],
                    "bbox": c["bbox"],
                    "font_size": c["font_size"],
                    "header_level": None,
                    "header_path": "",
                    "font": c["font"],
                }
            )
    return elements


def extract_pdf(pdf_path: str, include_chars: bool = False) -> Dict[str, Any]:
    """Top-level extraction: returns a structured document dict."""
    tables_by_page = extract_tables(pdf_path)
    blocks_by_page, char_records, all_font_sizes = extract_text_blocks(pdf_path, include_chars)
    body_size, header_sizes = classify_headers(blocks_by_page, all_font_sizes)
    elements = assemble_elements(blocks_by_page, tables_by_page, char_records, include_chars)

    n_pages = max(
        (max(blocks_by_page) if blocks_by_page else -1),
        (max(tables_by_page) if tables_by_page else -1),
    ) + 1

    return {
        "source": os.path.basename(pdf_path),
        "file_type": "pdf",
        "n_pages": n_pages,
        "body_font_size": body_size,
        "header_font_sizes": header_sizes,
        "n_elements": len(elements),
        "elements": elements,
    }


def main():
    ap = argparse.ArgumentParser(description="Extract structured elements from a PDF.")
    ap.add_argument("--input", required=True, help="Path to input PDF file")
    ap.add_argument("--output", help="Path to output JSON (default: stdout summary)")
    ap.add_argument(
        "--include-chars",
        action="store_true",
        help="Also emit character-level elements (large output)",
    )
    args = ap.parse_args()

    if not os.path.isfile(args.input):
        print(f"ERROR: input not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    doc = extract_pdf(args.input, include_chars=args.include_chars)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        print(f"Wrote {doc['n_elements']} elements from {doc['source']} -> {args.output}")
    else:
        # Print a brief summary
        counts: Dict[str, int] = {}
        for e in doc["elements"]:
            counts[e["element_type"]] = counts.get(e["element_type"], 0) + 1
        print(json.dumps({**{k: v for k, v in doc.items() if k != "elements"}, "element_counts": counts}, indent=2))


if __name__ == "__main__":
    main()
