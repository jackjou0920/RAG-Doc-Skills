---
name: pptx-parser
description: Extract structured information (slide titles, body text, tables, and speaker notes) from PowerPoint .pptx files and store it in a ChromaDB vector database for semantic search and RAG. Use this skill whenever the user wants to ingest, index, parse, or extract content from a .pptx presentation into a searchable database, or query previously-ingested presentation content.
version: 1.1.0
last-updated: 2026-06-21
---

# PPTX Extraction → ChromaDB Skill

Parse PowerPoint `.pptx` files into structured elements (titles, body text, tables,
speaker notes), clean and chunk them with rich metadata, embed them, and store them
in a local ChromaDB collection. This skill owns the full **ingestion / indexing**
pipeline: `extract → clean → chunk → embed → vector DB`. It shares the same
collection and schema as the **pdf** skill, so PDF and PPTX content live in one
searchable knowledge base.

## Architecture Flow

```
PPTX file(s)
    ↓  extract_pptx.py   (python-pptx: titles, body text, tables, notes)
Structured elements (JSON: title / body / table / notes, each with slide#, header_path)
    ↓  chunk.py          (clean + group body text by slide, keep tables whole, split long text w/ overlap)
Chunks (document + metadata + stable id)
    ↓  ingest.py         (embed + ChromaDB.upsert — default all-MiniLM-L6-v2 embeddings)
ChromaDB collection "documents"  (persisted at ./chroma_db)
    ↓  query.py          (semantic search to verify retrieval)
```

## Prerequisites

```bash
pip install -r skills/pptx-parser/requirements.txt
```

Dependencies: `python-pptx` (presentation parsing), `chromadb` (vector store).

ChromaDB uses its built-in local embedding model (`all-MiniLM-L6-v2`) — no API key,
no network needed.

## When to Use This Skill

**Trigger** when the user wants to:
- Ingest / index / parse a `.pptx` into a database
- Extract titles, body text, tables, or speaker notes from a presentation
- Build a searchable knowledge base from PowerPoint decks
- Run semantic search over previously-ingested presentation content

> Only `.pptx` (Open XML) is supported. Legacy `.ppt` (binary) must be converted first.

## Handling Different PPTX Layouts

Decks vary widely. Slides are read shape-by-shape, so the structure of each slide
drives what gets extracted:

| Deck / slide type | Characteristics | How to handle |
|---|---|---|
| **Title + bullets** | A title placeholder plus bulleted body text frames | Default. Title seeds `header_path`; bullets are grouped per shape with indent preserved by level. |
| **Table slides** | One or more table shapes, sparse text | Each table → markdown, kept as one chunk with `n_rows`/`n_cols`. Filter `element_type:"table"` to query figures/numbers. |
| **Chart / image slides** | Charts, images, SmartArt, diagrams | Charts/images are **not** extracted as data; only their title and any text labels/captions in text frames are captured. Search by the slide's title or caption. |
| **Notes-heavy decks** | Short slides, long speaker notes | Notes are captured separately as `notes` elements — searchable on their own or excludable via `element_type` filter. |
| **Grouped / nested shapes** | Shapes inside group containers | Extraction descends into group shapes recursively, so nested text and tables are not missed. |
| **No-title slides** | Section dividers, blank-title layouts | `header_path` falls back to just the deck name; body/notes still indexed. |

## Extraction (`extract_pptx.py`)

`extract_pptx(path)` walks every slide and emits elements that match the **same
document shape as the pdf skill**, so `chunk.py` / `ingest.py` / `query.py` work
unchanged. For each slide:

1. The **title placeholder** is read first and seeds the slide's `header_path`
   (`<deck> > <slide title>`).
2. All shapes are walked **recursively** (descending into group shapes):
   - **tables** → converted to a GitHub-flavored markdown string + `n_rows`/`n_cols`.
   - **text frames** → body text, grouped per shape with bullet levels preserved as
     leading indent (two spaces per level).
3. **Speaker notes** for the slide are captured as a separate `notes` element.

### Element types

| element_type | Source |
|---|---|
| `title` | Slide title placeholder (also builds `header_path`) |
| `body` | Body/content text frames (bullets, indented by level) |
| `table` | Tables on the slide (converted to markdown, kept whole) |
| `notes` | Speaker notes |

### Table handling

- Each row's cells are read, newlines flattened to spaces, ragged rows padded to the
  widest row's column count.
- Rendered to a GitHub-flavored **markdown table** (first row treated as the header).
- Stored downstream as a **single chunk** (never split) with `n_rows`/`n_cols` metadata.

### Charts, images, SmartArt

These shapes carry no extractable text body, so they are skipped — but any title,
caption, or label living in an accompanying text frame is still captured as `body`
or `title`. Query such slides by their title/caption text.

## Cleaning + Chunking (`chunk.py`, shared with pdf skill)

`chunk_document(doc, max_chars=1000, overlap=150)` turns extracted elements into
RAG-ready chunks. Cleaning and grouping rules:

- **body** — consecutive body blocks under the same `(slide, header_path)` are merged,
  stripped, then split into `~max_chars` windows on word boundaries with `overlap`
  characters carried into the next window.
- **title / notes** — emitted as standalone chunks (good for slide/section lookups
  and notes-only searches).
- **table** — one chunk per table, prefixed with `[Table under: <header_path>]` so
  the slide context is searchable alongside the table data; never split.

Each chunk:

```json
{
  "id": "<source>::p<slide>::<element_type>::<n>",
  "document": "<cleaned text content>",
  "metadata": { "source": "deck.pptx", "file_type": "pptx", "page": 0, "element_type": "body", "header_path": "deck > Q1 Results" }
}
```

Tuning per deck:
- Bullet-heavy slides: defaults work; lower `max_chars` (e.g. 400–600) if you want
  each slide's bullets to stay as one focused chunk.
- Table slides: chunking already isolates tables; no extra tuning needed.

## Standard Workflow

### Step 1 — (optional) Inspect extraction of a single deck

```bash
python skills/pptx-parser/scripts/extract_pptx.py --input ./pptx/deck.pptx --output deck.json
# or just a summary:
python skills/pptx-parser/scripts/extract_pptx.py --input ./pptx/deck.pptx
```

### Step 2 — Ingest PPTX deck(s) into ChromaDB

```bash
# Whole directory (into the shared 'documents' collection)
python skills/pptx-parser/scripts/ingest.py --input ./pptx/ --db ./chroma_db --collection documents

# Single deck
python skills/pptx-parser/scripts/ingest.py --input ./pptx/deck.pptx --db ./chroma_db
```

### Step 3 — Verify retrieval

```bash
# Semantic search — ranked source chunks
python skills/pptx-parser/scripts/query.py --db ./chroma_db --collection documents \
    --query "What were the Q1 revenue figures?" --top-k 5

# Restrict to PPTX tables only
python skills/pptx-parser/scripts/query.py --db ./chroma_db --collection documents \
    --query "revenue table" --filter '{"$and":[{"file_type":"pptx"},{"element_type":"table"}]}'

# Speaker notes only
python skills/pptx-parser/scripts/query.py --db ./chroma_db --collection documents \
    --query "action items" --filter '{"element_type":"notes"}'
```

## Script Reference

| Script | Purpose |
|---|---|
| `extract_pptx.py` | PPTX → structured elements (title/body/table/notes). `extract_pptx(path)` returns a dict matching the PDF skill's shape. |
| `chunk.py` | `chunk_document(doc, max_chars, overlap)` → list of `{id, document, metadata}` chunks. Tables kept whole; body text windowed. (Same module as the pdf skill.) |
| `ingest.py` | Orchestrates extract → chunk → embed → `ChromaDB.upsert`. Handles dirs, batching, `--reset`. |
| `query.py` | Semantic retrieval with optional metadata `--filter`; text or `--json` output. (Same as the pdf skill.) |

## Metadata Schema (shared with pdf skill)

| Field | Type | Description |
|---|---|---|
| `source` | str | Deck file name, e.g. `deck.pptx` |
| `file_type` | str | Always `pptx` (the pdf skill writes `pdf`) |
| `page` | int | Slide index (0-based) |
| `element_type` | str | `title` / `body` / `table` / `notes` |
| `header_path` | str | `<deck> > <slide title>` breadcrumb |
| `n_rows`,`n_cols` | int | Table dimensions (tables only) |

Because both skills write to the same `documents` collection, you can filter by
`file_type` to scope a query to PDFs or PPTX, or query across both at once, e.g.
`where={"file_type":"pptx","element_type":"table"}`.

## Output Format (query --json)

```json
{
  "query": "What were the Q1 revenue figures?",
  "results": [
    {
      "rank": 1,
      "id": "sample_deck.pptx::p3::table::0",
      "distance": 0.18,
      "score": 0.82,
      "metadata": {
        "source": "sample_deck.pptx",
        "file_type": "pptx",
        "page": 3,
        "element_type": "table",
        "header_path": "sample_deck > Q1 Results"
      },
      "document": "[Table under: sample_deck > Q1 Results]\n| Region | Revenue |\n| --- | --- |\n..."
    }
  ]
}
```

## Notes

- **Shared collection**: use the same `--db`/`--collection` as the pdf skill to build
  one unified knowledge base; distinguish sources via the `file_type` metadata filter.
- **Tables** become markdown and are stored as single chunks (never split).
- **Speaker notes** are captured separately so they can be searched or excluded.
- **Charts/images/SmartArt** are not extracted as data; only their titles/captions
  in text frames are indexed.
- **Grouped shapes** are traversed recursively, so nested text and tables are captured.
- **Embeddings** default to local `all-MiniLM-L6-v2`. Switch by setting a ChromaDB
  embedding function in `ingest.py`.
- **`.ppt`** (legacy binary) is not supported — convert to `.pptx` first.