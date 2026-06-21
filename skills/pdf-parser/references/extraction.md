# PDF Extraction Reference

How `extract_pdf.py` turns a PDF into structured, queryable elements.

## Libraries

| Library | Role | Why |
|---|---|---|
| **PyMuPDF (fitz)** | Text blocks, spans, font size/name, bbox, char-level | Fast, gives per-span font metadata needed for header detection |
| **pdfplumber** | Table detection & extraction | Most reliable table finder; converts to row/col arrays |

## Element Types

Every extracted element has a `element_type`:

- **text** — a paragraph/block of body text
- **header** — a block whose font size is larger than body text (or bold at body size)
- **table** — a detected table, converted to a markdown string
- **char** — a single character with font + bbox (only with `--include-chars`)

## Header Detection Heuristic

1. Collect every span's font size across the whole document.
2. The **mode** (most frequent rounded size) = **body text size**.
3. Distinct sizes **larger** than body become header tiers (top 3 → h1/h2/h3).
4. Bold text at body size becomes a minor header (h4).
5. A running `header_stack` builds a breadcrumb `header_path`
   (e.g. `Packaging > CoWoS > Summary`) attached to following content.

> Note: this is heuristic. Slide-style PDFs (where everything is large) may
> over-classify headers. The `header_path` still gives useful section context,
> and you can filter by `element_type` at query time.

## Table Handling

- `page.find_tables()` + `table.extract()` gives a 2D array of cells.
- `None` cells → empty strings; cells stringified & stripped.
- Converted to a GitHub-flavored markdown table (preserves rows/cols for the LLM).
- Stored as a **single chunk** with `n_rows`/`n_cols` metadata — never split.

## Character Extraction (optional)

With `--include-chars`, every non-whitespace character is emitted as its own element
with `font`, `font_size`, and `bbox`. This is large and only useful for
coordinate/font-level forensics — **off by default** and not recommended for
semantic search.

## Output Structure

```json
{
  "source": "report.pdf",
  "file_type": "pdf",
  "n_pages": 47,
  "body_font_size": 9.0,
  "header_font_sizes": [40, 36, 32],
  "n_elements": 674,
  "elements": [
    {
      "page": 6,
      "element_type": "header",
      "text": "Advanced Packaging",
      "bbox": "72.0,120.0,500.0,150.0",
      "font_size": 32.0,
      "header_level": 3,
      "header_path": "Outline > Advanced Packaging"
    },
    {
      "page": 6,
      "element_type": "text",
      "text": "CoWoS is a 2.5D integration ...",
      "bbox": "72.0,160.0,500.0,400.0",
      "font_size": 9.0,
      "header_level": null,
      "header_path": "Outline > Advanced Packaging"
    }
  ]
}