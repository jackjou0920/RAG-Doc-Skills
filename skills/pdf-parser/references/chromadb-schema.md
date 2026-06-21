# ChromaDB Schema & Query Reference

The collection design shared by the **pdf** and **pptx** skills.

## Collection

- **Name**: `documents` (default; configurable via `--collection`)
- **Distance**: cosine (`metadata={"hnsw:space": "cosine"}`)
- **Embeddings**: ChromaDB default `all-MiniLM-L6-v2` (local, 384-dim, free)
- **Persisted at**: `./chroma_db` (default; configurable via `--db`)

One collection holds **both** PDF and PPTX chunks; the `file_type` metadata field
distinguishes them so a single MCP server can query everything.

## Chunk Record

| Part | Description |
|---|---|
| `id` | Stable string: `<source>::p<page>::<element_type>::<n>` |
| `document` | The text content that gets embedded & searched |
| `metadata` | Filterable fields (below) |

## Metadata Fields

| Field | Type | Present for | Description |
|---|---|---|---|
| `source` | str | all | Source file name |
| `file_type` | str | all | `pdf` or `pptx` |
| `page` | int | all | PDF page / PPTX slide number (0-based) |
| `element_type` | str | all | `text` / `header` / `table` / `char` (PDF); `title`/`body`/`table`/`notes` (PPTX) |
| `header_path` | str | all | Section breadcrumb |
| `bbox` | str | pdf | `x0,y0,x1,y1` |
| `font_size` | float | pdf text/header/char | Average font size |
| `n_rows`, `n_cols` | int | tables | Table dimensions |

> ChromaDB metadata values must be `str`, `int`, `float`, or `bool` — no nested
> structures. `_meta()` in `chunk.py` enforces this.

## Query Patterns

### Semantic search (all content)
```python
collection.query(query_texts=["What is CoWoS?"], n_results=5)
```

### Filter by file type
```python
collection.query(query_texts=["yield"], n_results=5,
                  where={"file_type": "pdf"})
```

### Filter by element type (e.g. tables only)
```python
collection.query(query_texts=["specifications"], n_results=5,
                  where={"element_type": "table"})
```

### Combine filters (AND)
```python
collection.query(
    query_texts=["packaging"], n_results=5,
    where={"$and": [{"file_type": "pdf"}, {"element_type": "text"}]},
)
```

### Filter by a specific source document
```python
collection.query(query_texts=["lithography"], n_results=5,
                 where={"source": "micron-intro-to-fabrication-presentation.pdf"})
```

## Result Interpretation

- `distances` are cosine distances (0 = identical, 2 = opposite).
- The CLI reports `score = 1 - distance` (≈ cosine similarity); higher is better.
- Typical good matches score ~0.6–0.8 for `all-MiniLM-L6-v2`.

## For the Future MCP Server

A `datalens-rag` MCP server (modeled on `Datalens-MCP/datalens-postgres`) would:
1. Open the same `./chroma_db` PersistentClient.
2. Expose a `semantic_search(query, top_k, filters)` tool that calls
   `collection.query(...)` and returns the hit list (document + metadata + score).
3. The LLM uses returned chunks as context to answer the client's question.