# PPTX Extraction Reference

How `extract_pptx.py` turns a PowerPoint `.pptx` into structured, queryable elements.

## Library

| Library | Role |
|---|---|
| **python-pptx** | Reads the Open XML `.pptx` format: slides, shapes, text frames, tables, notes |

> Only `.pptx` (Open XML) is supported. Legacy `.ppt` binary files must be converted
> to `.pptx` first (e.g. via LibreOffice `soffice --convert-to pptx`).

## Element Types

Each element has an `element_type`:

- **title** — the slide's title placeholder; also seeds the `header_path`
- **body** — text from non-title text frames (content placeholders, text boxes)
- **table** — a table shape, converted to a markdown table
- **notes** — the slide's speaker notes

## Extraction Logic

For each slide (0-based `page` index):

1. **Title**: read `slide.shapes.title.text`. If present, emit a `title` element and
   set `header_path = "<deck name> > <title>"`.
2. **Shapes loop**: for every shape except the title shape:
   - If `shape.has_table` → convert `shape.table` to markdown → emit `table` element
     (with `n_rows`/`n_cols`).
   - Else if it has a text frame → collect non-empty paragraphs → emit a `body` element.
3. **Notes**: if `slide.has_notes_slide`, read `notes_slide.notes_text_frame.text` →
   emit a `notes` element.

All elements on a slide share the same `header_path`, giving the chunker section
context for retrieval.

## Table Handling

- Each row's cells are read via `cell.text`, stripped.
- Rows normalized to equal column count.
- Converted to a GitHub-flavored markdown table.
- Stored as a **single chunk** (never split) with `n_rows`/`n_cols` metadata.

## Output Structure

```json
{
  "source": "deck.pptx",
  "file_type": "pptx",
  "n_pages": 12,
  "n_elements": 48,
  "elements": [
    {
      "page": 0,
      "element_type": "title",
      "text": "Q1 2026 Business Review",
      "header_path": "deck > Q1 2026 Business Review"
    },
    {
      "page": 0,
      "element_type": "body",
      "text": "Revenue: $2.5B\nYoY Growth: +12%",
      "header_path": "deck > Q1 2026 Business Review"
    },
    {
      "page": 3,
      "element_type": "table",
      "text": "| Metric | Q1 | Q2 |\n| --- | --- | --- |\n| Rev | 2.5 | 2.8 |",
      "header_path": "deck > Financials",
      "n_rows": 2,
      "n_cols": 3
    },
    {
      "page": 0,
      "element_type": "notes",
      "text": "Emphasize the YoY growth during the intro.",
      "header_path": "deck > Q1 2026 Business Review"
    }
  ]
}
```

## Shared Pipeline

This output has the **same shape** as the PDF skill's extraction, so it flows through
the identical `chunk.py` and into the same ChromaDB `documents` collection. The
`file_type` field (`pptx`) keeps it distinguishable from PDF content at query time.