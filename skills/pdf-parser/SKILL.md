---
name: pdf-parser
description: Extract structured information (text, headers, tables, and character/font details) from PDF files and store it in a ChromaDB vector database for semantic search and RAG. Use this skill whenever the user wants to ingest, index, parse, or extract content from a .pdf file into a searchable database, or query previously-ingested PDF content.
version: 1.1.0
last-updated: 2026-06-21
---

# PDF Extraction → ChromaDB Skill

Parse PDF files into structured elements (text, headers, tables, optional chars),
clean and chunk them with rich metadata, embed them, and store them in a local
ChromaDB collection. This skill owns the full **ingestion / indexing** pipeline:
`extract → clean → chunk → embed → vector DB`.

## Architecture Flow

```
PDF file(s)
    ↓  extract_pdf.py   (PyMuPDF: text/headers/chars/fonts  +  pdfplumber: tables)
Structured elements (JSON: text / header / table / char, each with bbox, font, page, header_path)
    ↓  chunk.py         (clean + group text by section, keep tables whole, split long text w/ overlap)
Chunks (document + metadata + stable id)
    ↓  ingest.py        (embed + ChromaDB.upsert — default all-MiniLM-L6-v2 embeddings)
ChromaDB collection "documents"  (persisted at ./chroma_db)
    ↓  query.py         (semantic search to verify retrieval)
```

## Prerequisites

```bash
pip install -r skills/pdf-parser/requirements.txt
```

Dependencies: `pdfplumber` (tables), `PyMuPDF` (text/fonts/chars), `chromadb` (vector store).

ChromaDB uses its built-in local embedding model (`all-MiniLM-L6-v2`) — no API key,
no network needed.

## When to Use This Skill

**Trigger** when the user wants to:
- Ingest / index / parse a `.pdf` into a database
- Extract text, tables, headers, or character/font info from a PDF
- Build a searchable knowledge base from PDFs
- Run semantic search over previously-ingested PDF content

## Handling Different PDF Formats

PDFs come in several layouts. The pipeline classifies content the same way
regardless of source, but the right knobs differ per format:

| PDF format | Characteristics | How to handle |
|---|---|---|
| **Prose / report** | One dominant body font, clear paragraphs, occasional tables | Default settings. Header detection works well; tables kept whole. |
| **Slide-deck PDF** | Large fonts everywhere, little body text, bullet lists | Header heuristic may over-classify headers — rely on `header_path` for section context and filter by `element_type` at query time. Lower `--max-chars` so slide bullets stay grouped. |
| **Table-heavy / spec sheet** | Many tables, numeric data, sparse prose | `pdfplumber` detects tables; each is converted to markdown and kept as one chunk with `n_rows`/`n_cols`. Filter `element_type:"table"` when querying numbers. |
| **Charts / figures** | Image-based charts, captions, labels | Charts render as images (not extracted). Their **captions and surrounding text** are captured as `text` and attached to the nearest `header_path`, so query by the chart's topic/caption. |
| **Scanned / image-only** | No selectable text layer | Not OCR-handled by this skill; extraction yields little/no text. OCR the PDF first (external step) before ingesting. |

## Extraction (`extract_pdf.py`)

Two libraries do complementary work:

- **PyMuPDF (fitz)** — text blocks, per-span font size/name, bbox, char-level data.
- **pdfplumber** — table detection and cell extraction.

Each emitted element has an `element_type`:

- **text** — a paragraph/block of body text (captions for charts/figures land here)
- **header** — a block whose font is larger than body text (or bold at body size)
- **table** — a detected table, converted to a markdown string
- **char** — a single character with font + bbox (only with `--include-chars`)

### Header detection (drives section structure)

1. Collect every span's font size across the document.
2. The **mode** (most frequent rounded size) = **body text size**.
3. Sizes **larger** than body become header tiers (top 3 → h1/h2/h3).
4. Bold text at body size becomes a minor header (h4).
5. A running header stack builds a breadcrumb `header_path`
   (e.g. `Packaging > CoWoS > Summary`) attached to following content.

This breadcrumb is what gives every chunk its section context — critical for
slide decks and chart-heavy PDFs where the body text alone is ambiguous.

### Table handling

- `page.find_tables()` + `table.extract()` → 2D array of cells.
- `None` cells → empty strings; cells are stringified and stripped.
- Converted to a GitHub-flavored **markdown table** to preserve rows/columns.
- Stored as a **single chunk** (never split) with `n_rows`/`n_cols` metadata.

### Character extraction (optional, off by default)

`--include-chars` emits every non-whitespace character with `font`, `font_size`,
and `bbox`. Large and only useful for coordinate/font forensics — not for
semantic search.

## Cleaning + Chunking (`chunk.py`)

`chunk_document(doc, max_chars=1000, overlap=150)` turns extracted elements into
RAG-ready chunks. Cleaning and grouping rules:

- **text** — consecutive blocks under the same `(page, header_path)` are merged,
  stripped, then split into `~max_chars` windows on word boundaries with `overlap`
  characters carried into the next window (preserves context across splits).
- **header / title / notes** — emitted as standalone chunks (good for section lookups).
- **table** — one chunk per table, prefixed with `[Table under: <header_path>]` so
  the section context is searchable alongside the table data; never split.
- **char** — one chunk per char (only when extracted).

Each chunk:

```json
{
  "id": "<source>::p<page>::<element_type>::<n>",
  "document": "<cleaned text content>",
  "metadata": { "source": "...", "file_type": "pdf", "page": 0, "element_type": "text", "header_path": "...", "bbox": "...", "font_size": 9.0 }
}
```

Tuning per format:
- Dense reports: keep defaults (`max_chars=1000`, `overlap=150`).
- Slide decks / short bullets: lower `max_chars` (e.g. 400–600) to avoid merging
  unrelated slides.
- Table-heavy docs: chunking already isolates tables; no extra tuning needed.

## Standard Workflow

### Step 1 — (optional) Inspect extraction of a single PDF

```bash
python skills/pdf-parser/scripts/extract_pdf.py --input ./pdf/report.pdf --output report.json
# or just a summary:
python skills/pdf-parser/scripts/extract_pdf.py --input ./pdf/report.pdf
```

### Step 2 — Ingest PDF(s) into ChromaDB

```bash
# Whole directory
python skills/pdf-parser/scripts/ingest.py --input ./pdf/ --db ./chroma_db --collection documents

# Single file, reset collection first
python skills/pdf-parser/scripts/ingest.py --input ./pdf/report.pdf --db ./chroma_db --reset

# Include character-level elements (large; only if char/font lookups are needed)
python skills/pdf-parser/scripts/ingest.py --input ./pdf/ --db ./chroma_db --include-chars
```

### Step 3 — Verify retrieval

```bash
# Semantic search — show the ranked source chunks
python skills/pdf-parser/scripts/query.py --db ./chroma_db --collection documents \
    --query "What is CoWoS packaging?" --top-k 5

# Filter to tables only (useful for table-heavy PDFs)
python skills/pdf-parser/scripts/query.py --db ./chroma_db --collection documents \
    --query "wafer yield numbers" --filter '{"element_type":"table"}'

# JSON output (for inspection or piping)
python skills/pdf-parser/scripts/query.py --db ./chroma_db --collection documents \
    --query "lithography process" --json
```

## Script Reference

| Script | Purpose |
|---|---|
| `extract_pdf.py` | PDF → structured elements (text/header/table/char) with bbox, font size, header path. `extract_pdf(path, include_chars)` returns a dict. |
| `chunk.py` | `chunk_document(doc, max_chars, overlap)` → list of `{id, document, metadata}` chunks. Tables kept whole; text grouped by section then windowed. |
| `ingest.py` | Orchestrates extract → chunk → embed → `ChromaDB.upsert`. Handles dirs, batching, `--reset`. |
| `query.py` | Semantic retrieval. Default: ranked chunks; `--json`: raw JSON; `--filter`: metadata filter. |

## Metadata Schema (shared with pptx skill)

Each chunk stored in ChromaDB carries:

| Field | Type | Description |
|---|---|---|
| `source` | str | File name, e.g. `report.pdf` |
| `file_type` | str | Always `pdf` (the pptx skill writes `pptx`) |
| `page` | int | Page index (0-based) |
| `element_type` | str | `text` / `header` / `table` / `char` |
| `header_path` | str | Section breadcrumb, e.g. `Packaging > CoWoS` |
| `bbox` | str | `x0,y0,x1,y1` bounding box |
| `font_size` | float | Average font size (text/header/char) |
| `n_rows`,`n_cols` | int | Table dimensions (tables only) |

This lets queries filter precisely, e.g. `where={"file_type":"pdf","element_type":"table"}`.

## Output Format (query --json)

```json
{
  "query": "What is CoWoS packaging?",
  "results": [
    {
      "rank": 1,
      "id": "TSMC_Packaging_Technologies_public.pdf::p7::text::0",
      "distance": 0.21,
      "score": 0.79,
      "metadata": {
        "source": "TSMC_Packaging_Technologies_public.pdf",
        "file_type": "pdf",
        "page": 7,
        "element_type": "text",
        "header_path": "Advanced Packaging > CoWoS"
      },
      "document": "CoWoS (Chip-on-Wafer-on-Substrate) is ..."
    }
  ]
}
```

## Notes

- **Header detection** is heuristic (font size relative to body text + bold). Works
  well for typical documents; very stylized or slide-style PDFs may misclassify some
  headers — `header_path` still gives useful section context.
- **Tables** are converted to markdown and kept as a single chunk to preserve structure.
- **Charts/figures** are not extracted as images; their captions and nearby text are
  indexed instead, so search by topic/caption.
- **Chars** are off by default (`--include-chars` to enable) — they bloat the DB and
  are only useful for font/coordinate-level analysis, not semantic search.
- **Shared collection**: ingest PDFs and PPTX into the same `--collection` and
  distinguish them via the `file_type` metadata filter.
- **Embeddings** default to local `all-MiniLM-L6-v2`. To switch to OpenAI/other, set a
  ChromaDB embedding function when creating the collection in `ingest.py`.