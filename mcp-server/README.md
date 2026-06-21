# Document RAG MCP Server

A Model Context Protocol (MCP) server providing read-only **semantic search** over
a ChromaDB vector store built by the `pdf-parser` and `pptx-parser` skills. It
exposes three tools so a client/LLM can retrieve relevant document chunks and
generate answers itself.

No authentication, no audit logging — it is a thin query layer over ChromaDB.

## Architecture

```
ChromaDB (./chroma_db, collection "documents")   ← built by pdf-parser / pptx-parser skills
        ↑
  ChromaClient (src/chroma_client.py)
        ↑
  Tools (src/tools.py): search_docs / get_chunk / get_document
        ↑
  FastMCP server (src/server.py)  — streamable HTTP transport
        ↑
  Client (generates the final answer from retrieved chunks)
```

```
mcp-server/
├── README.md
├── requirements.txt
├── run.sh
├── .env.example
├── test_server.py            # direct smoke test of the 3 tools
└── src/
    ├── __init__.py
    ├── config.py             # CHROMA_DB_PATH / COLLECTION / HOST / PORT / MCP_PATH
    ├── models.py             # Pydantic input/output models
    ├── chroma_client.py      # ChromaDB PersistentClient wrapper
    ├── tools.py              # tool implementations (no auth/log)
    └── server.py             # FastMCP + FastAPI app
```

## Setup

```bash
pip install -r mcp-server/requirements.txt
cp mcp-server/.env.example mcp-server/.env   # adjust CHROMA_DB_PATH if needed
```

`.env` defaults:

| Variable | Default | Description |
|---|---|---|
| `CHROMA_DB_PATH` | `../chroma_db` | Path to the ChromaDB created by the skills |
| `CHROMA_COLLECTION` | `documents` | Collection name (shared by PDF + PPTX) |
| `HOST` | `0.0.0.0` | Bind host |
| `PORT` | `8011` | Bind port |
| `MCP_PATH` | `rag` | MCP endpoint prefix |

> The collection uses ChromaDB's default embedding model (`all-MiniLM-L6-v2`).
> Querying here automatically uses the same model bound to the collection.

## Run

```bash
cd mcp-server
./run.sh
# or
python3 src/server.py
```

Endpoints:
- **MCP**: `http://HOST:PORT/{MCP_PATH}/mcp` (e.g. `http://0.0.0.0:8011/rag/mcp`)
- **Health**: `http://HOST:PORT/health`
- **Metrics**: `http://HOST:PORT/{MCP_PATH}/metrics`

## Tools

### `search_docs(query, top_k=5, file_type?, element_type?, source?)`
Semantic similarity search. Returns the most relevant chunks with score + metadata.

```json
{
  "success": true,
  "query": "What is CoWoS packaging?",
  "results": [
    {
      "id": "TSMC_Packaging_Technologies_public.pdf::p3::text::1",
      "score": 0.62,
      "source": "TSMC_Packaging_Technologies_public.pdf",
      "file_type": "pdf",
      "page": 3,
      "element_type": "text",
      "header_path": "TSMC Integration Technologies > CoWoS: Chip on Wafer on Substrate",
      "document": "CoWoS-S CoWoS-R CoWoS-L InFO-R ..."
    }
  ],
  "count": 5
}
```

Filters:
- `file_type`: `pdf` | `pptx`
- `element_type`: `text` | `header` | `table` | `title` | `body` | `notes`
- `source`: exact source file name

### `get_chunk(chunk_id)`
Fetch one chunk's full content + all metadata by id.

```json
{ "success": true, "id": "report.pdf::p3::text::1", "document": "...", "metadata": { ... } }
```

### `get_document(source, element_type?, limit=200)`
Fetch all chunks for a source file, ordered by page.

```json
{ "success": true, "source": "deck.pptx", "chunks": [ { "id": "...", "page": 0, "element_type": "title", "header_path": "...", "document": "..." } ], "count": 6 }
```

## Error Responses

```json
{ "success": false, "message": "Chunk not found: ...", "error_type": "DATA_ERROR" }
```

| error_type | Meaning |
|---|---|
| `VALIDATION_ERROR` | Invalid input parameters |
| `CONNECTION_ERROR` | ChromaDB path/collection unreachable |
| `QUERY_ERROR` | Search execution problem |
| `DATA_ERROR` | Not found / data processing issue |

## Test

```bash
cd mcp-server
python3 test_server.py
```

Runs the three tools directly against ChromaDB and asserts they succeed.

## Typical RAG Flow (client side)

1. Client calls `search_docs(query)` → gets top-k chunks + metadata.
2. (Optional) Client calls `get_chunk(id)` / `get_document(source)` for more context.
3. Client feeds the retrieved chunks to its LLM to **generate the final answer**.

This server only does retrieval; answer generation lives in the client.