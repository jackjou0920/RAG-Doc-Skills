# RAG_DOC_Skills — Unstructured Document RAG Pipeline, MCP Server & Claude Skills
 
An end-to-end Retrieval-Augmented Generation (RAG) system for **messy enterprise documents**.
It ingests multi-page PDFs (text, headers, tables) and PowerPoint decks (titles, bullets,
tables, speaker notes), cleans and chunks the content with rich metadata, embeds it into a
local **ChromaDB** vector store, and exposes the searchable knowledge base through a remote
**Model Context Protocol (MCP)** server. Any standard LLM agent (Claude Desktop, OpenAI
GPT-4o, or a custom client) can connect and query the extracted information.

The same parsing/cleaning/indexing capabilities are also packaged as reusable, self-contained
**Claude Skills** that Claude Code can install and invoke directly.
 
This repository covers two deliverables:
 
1. **Unstructured Data Pipeline & Remote MCP Server** — ingest → clean → chunk → embed →
   serve over MCP, with a verifiable MCP client test script and example queries.
2. **Data Preprocessing as Claude Skills** — the PDF/PPTX preprocessing capabilities packaged
   as installable Skills with clear inputs/outputs and a safe execution boundary.
 
---

## Architecture
 
```
        Enterprise documents (sample_doc/)
        ┌─────────────────┐   ┌─────────────────┐
        │   PDF files     │   │   PPTX decks    │
        └────────┬────────┘   └────────┬────────┘
                 │  pdf-parser skill    │  pptx-parser skill
                 │  extract → clean →   │  extract → clean →
                 │  chunk → embed       │  chunk → embed
                 └──────────┬───────────┘
                            ▼
        ┌──────────────────────────────────────────┐
        │  ChromaDB  (./chroma_db, "documents")     │   ← shared collection
        │  all-MiniLM-L6-v2 local embeddings        │
        └────────────────────┬─────────────────────┘
                             ▲
        ┌────────────────────┴─────────────────────┐
        │  MCP Server  (mcp-server/)                │
        │  FastMCP + streamable HTTP                │
        │  tools: search_docs / get_chunk /         │
        │         get_document                      │
        └────────────────────┬─────────────────────┘
                             ▲  MCP over HTTP
        ┌────────────────────┴─────────────────────┐
        │  MCP Client  (mcp-client/)                │
        │  retrieves chunks → LLM generates answer  │
        │  (Qualcomm qgenie / OpenAI GPT-4o)        │
        └───────────────────────────────────────────┘
```
 
The server is a **thin retrieval layer**: it returns relevant chunks; the *client's* LLM
generates the final answer from those chunks.

---

## Repository Layout
 
```
RAG_DOC/
├── README.md                    # this file
├── chroma_db/                   # persisted ChromaDB vector store (built by the skills)
│
├── sample_doc/                  # simulated messy enterprise documents
│   ├── pdf/                     # multi-page PDFs (reports, slide-style, table-heavy)
│   └── pptx/                    # PowerPoint decks
│
├── skills/                      # Claude Skills (data preprocessing as reusable skills)
│   ├── pdf-parser/
│   │   ├── SKILL.md             # skill manifest + usage
│   │   ├── requirements.txt
│   │   ├── references/          # extraction & schema docs
│   │   └── scripts/             # extract_pdf.py / chunk.py / ingest.py / query.py
│   └── pptx-parser/
│       ├── SKILL.md
│       ├── requirements.txt
│       ├── references/
│       └── scripts/             # extract_pptx.py / chunk.py / ingest.py / query.py
│
├── mcp-server/                  # remote MCP server over ChromaDB
│   ├── README.md
│   ├── requirements.txt
│   ├── test_server.py           # direct smoke test of the 3 tools
│   └── src/
│       ├── config.py            # CHROMA path / collection / host / port / MCP path
│       ├── models.py            # Pydantic input/output models
│       ├── chroma_client.py     # ChromaDB PersistentClient wrapper
│       ├── tools.py             # search_docs / get_chunk / get_document
│       └── server.py            # FastMCP + FastAPI app
│
├── mcp-client/                  # MCP client demos (RAG answer generation)
│   ├── client_qualcomm.py       # uses Qualcomm internal LLM (qgenie)
│   ├── client_openai.py         # uses OpenAI GPT-4o
│   ├── requirements.txt
│   └── output.txt               # recorded run logs proving retrieval works
│
└── assets/                      # screenshots / demo images
```
 
---

## Components
 
### 1. Claude Skills — `skills/`
 
Two self-contained skills package the unstructured-data preprocessing pipeline
(`extract → clean → chunk → embed → vector DB`). Each has a clear input (a file or
directory) and output (chunks persisted in ChromaDB), a safe CLI execution boundary, and
can be installed and invoked by Claude Code.
 
| Skill | Input | Extracts | Library |
|---|---|---|---|
| **pdf-parser** | `.pdf` | text, headers, tables, optional char/font data | PyMuPDF + pdfplumber |
| **pptx-parser** | `.pptx` | titles, body/bullets, tables, speaker notes | python-pptx |

Both skills:
- Emit a shared element/metadata schema (`source`, `file_type`, `page`, `element_type`,
  `header_path`, table dims …) so PDF and PPTX content coexist in one `documents` collection.
- Build a section breadcrumb (`header_path`) for context, keep **tables whole** as markdown,
  and window long text with overlap.
- Use ChromaDB's local `all-MiniLM-L6-v2` embeddings — **no API key, no network** needed.
 
See `skills/pdf-parser/SKILL.md` and `skills/pptx-parser/SKILL.md` for full details, format
handling tables, and per-script reference.

#### Ingest the sample documents
 
```bash
pip install -r skills/pdf-parser/requirements.txt
pip install -r skills/pptx-parser/requirements.txt
 
# Ingest all PDFs (reset collection first)
python skills/pdf-parser/scripts/ingest.py  --input ./sample_doc/pdf/  --db ./chroma_db --collection documents --reset
 
# Ingest all PPTX decks into the same collection
python skills/pptx-parser/scripts/ingest.py --input ./sample_doc/pptx/ --db ./chroma_db --collection documents
```

#### Verify retrieval directly
 
```bash
python skills/pdf-parser/scripts/query.py --db ./chroma_db --collection documents \
    --query "What is CoWoS packaging?" --top-k 5
```

### 2. Remote MCP Server — `mcp-server/`
 
A FastMCP server (streamable HTTP transport) that exposes **read-only semantic search** over
the ChromaDB collection. Three tools:

| Tool | Description |
|---|---|
| `search_docs(query, top_k, file_type?, element_type?, source?)` | Semantic similarity search; returns ranked chunks + score + metadata. |
| `get_chunk(chunk_id)` | Fetch one chunk's full content + all metadata by id. |
| `get_document(source, element_type?, limit)` | Fetch all chunks for a source file, ordered by page/slide. |
 
```bash
pip install -r mcp-server/requirements.txt
cd mcp-server && python3 src/server.py
```
 
Endpoints (defaults):
- **MCP**: `http://0.0.0.0:8011/rag/mcp`
- **Health**: `http://0.0.0.0:8011/health`
- **Metrics**: `http://0.0.0.0:8011/rag/metrics`

Smoke test the tools directly against ChromaDB:
 
```bash
cd mcp-server && python3 test_server.py
```
 
See `mcp-server/README.md` for the full tool schemas, filters, and error model.

### 3. MCP Client Demos — `mcp-client/`
 
Connects to the running MCP server, calls `search_docs` to retrieve relevant chunks, and
feeds them to an LLM to **generate the final answer** — a complete RAG loop. Two generators
are provided:

| Client | Generator |
|---|---|
| `client_qualcomm.py` | Qualcomm internal LLM (qgenie) |
| `client_openai.py` | OpenAI GPT-4o (set `OPENAI_API_KEY`) |
 
```bash
pip install -r mcp-client/requirements.txt
python mcp-client/client_qualcomm.py
# or
OPENAI_API_KEY=sk-... python mcp-client/client_openai.py
```

`mcp-client/output.txt` contains recorded run logs proving successful end-to-end retrieval and answer generation (example query: *"What is CoWoS packaging and what are its main types?"*) including the retrieved sources and similarity scores.

---

## Key Design Choices
 
- **Shared collection & schema** — PDF and PPTX skills write to one `documents` collection;
  scope queries with the `file_type` metadata filter, or search across both at once.
- **Tables kept whole** — converted to markdown and stored as single chunks to preserve
  row/column structure (with `n_rows`/`n_cols` metadata).
- **Section context everywhere** — every chunk carries a `header_path` breadcrumb, which is
  essential for slide decks and chart-heavy PDFs where body text alone is ambiguous.

- **Retrieval ≠ generation** — the MCP server only retrieves; the client's LLM generates
  answers, keeping the server stateless, model-agnostic, and easy to host remotely.
- **Local embeddings by default** — `all-MiniLM-L6-v2` runs offline; swap in OpenAI/other by
  setting a ChromaDB embedding function in `ingest.py`.
 
---

## Verifiable Outputs
 
- `mcp-client/output.txt` — recorded RAG run logs (queries, tool calls, generated answers,
  cited sources with scores).
- `mcp-server/test_server.py` — asserts all three tools succeed against ChromaDB.
- `assets/` — screenshots of skill loading, MCP tool listing, database state, and example
  queries (e.g. `load_pdf_skill.png`, `load_pptx_skill.png`, `mcp_tools.png`, `add_mcp.png`,
  `query_example.png`, `db_now.png`, `init.png`).