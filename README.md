# Legal GraphRAG

A local question-answering app for legal PDFs. Each uploaded PDF is turned into a Neo4j
knowledge graph of parties, agreements, clauses, obligations and so on. You can then chat
with a local Gemma model that answers **only** from that graph and cites the source documents.

- **Ingestion:** `SimpleKGPipeline` from [neo4j-graphrag](https://neo4j.com/docs/neo4j-graphrag-python/current/), with automatic legal-domain schema extraction and entity resolution across documents.
- **Retrieval:** `HybridCypherRetriever` (vector + fulltext search over chunks, then expansion to the entities and relationships linked to each chunk).
- **Answers:** `GraphRAG` with a custom `RagTemplate` that restricts the model to the retrieved context. Conversations are stored in Neo4j with `Neo4jMessageHistory`.
- **Models (via Ollama):** `gemma4:12b` for extraction and answers, `embeddinggemma:300m` for embeddings.
- **Stack:** FastAPI REST backend, React + Vite UI.

## Prerequisites

| Tool | Version | macOS install |
| --- | --- | --- |
| Python | 3.11 – 3.14 (or [uv](https://docs.astral.sh/uv/), which installs Python for you) | `brew install uv` |
| Node.js | 20.19+ | `brew install node` |
| Ollama | recent (Gemma 4 support) | <https://ollama.com/download> |
| Neo4j Desktop | DBMS version 5.18+ with the **APOC** plugin | <https://neo4j.com/download/> |

About 12 GB of free RAM is enough for `gemma4:12b`, `embeddinggemma` and Neo4j together. A
24 GB Apple-silicon Mac works.

## Quick start

1. **Neo4j Desktop:** create a local DBMS, open its **Plugins** tab and install **APOC**, then start it. Note the password.
2. **Ollama:** start the Ollama app.
3. **Set up and run:**

   ```bash
   bash setup.sh    # venv + backend deps, frontend deps + build, backend/.env, model pulls
   bash start.sh    # http://localhost:8000
   ```

`setup.sh` asks for the Neo4j password and writes it to `backend/.env`. It is safe to re-run.
The status bar at the top of the UI shows whether Neo4j, APOC, the indexes, Ollama and both
models are ready. Hover a pill to see details.

For UI development with hot reload, run `bash start.sh --dev` and open <http://localhost:5173>.

### Manual setup (without the scripts)

```bash
uv venv .venv --python 3.12 && uv pip install -r backend/requirements.txt
# or: python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
(cd frontend && npm ci && npm run build)
cp backend/.env.example backend/.env    # then set NEO4J_PASSWORD
ollama pull gemma4:12b && ollama pull embeddinggemma:300m
cd backend && ../.venv/bin/python -m uvicorn app.main:app --port 8000
```

## Using the app

1. **Upload PDFs** in the Documents panel. Each one is queued and processed in the
   background, one at a time. The current stage is shown while it runs (reading, schema,
   embedding, extracting, writing, merging). A typical contract takes a few minutes on a laptop.
2. **Ask questions** in the chat. Use **New chat** for separate conversations. Follow-up
   questions use the conversation history. Answers cite file names, and each answer lists the
   source excerpts it was based on.
3. **Graph view:**
   - **Answer subgraph** shows the entities and relationships retrieved for the selected answer.
     Click "N entities in graph" under any answer to show its subgraph.
   - **Full graph** shows the whole knowledge graph (the 500 most connected entities). You can
     filter it by document or entity type. Entities used in the selected answer are highlighted.
   - Click a node to see its properties, relationships and source documents.

## How the graph is built

```
(:Document {fileName, documentId, ...})<-[:FROM_DOCUMENT]-(:Chunk {text, embedding, index})
(:Chunk)-[:NEXT_CHUNK]->(:Chunk)
(:__Entity__:Party {name, ...})-[:FROM_CHUNK]->(:Chunk)
(:__Entity__:Party)-[:PARTY_TO {role}]->(:__Entity__:Agreement)      # extracted facts
(:Session {id, title})-[:LAST_MESSAGE]->(:Message {role, content})   # chat history
```

For each upload:

1. **Schema:** the LLM proposes node and relationship types from a sample of the document
   (start, middle and end), using legal-domain guidance. The prompt lists the types already
   in the graph, so new documents reuse the same labels. SimpleKGPipeline's built-in
   `schema="EXTRACTED"` mode would send the whole document in one prompt, which overflows a
   local model, so the app runs the same library component on a sample.
2. **SimpleKGPipeline:** the pipeline loads the PDF, splits it into chunks of about 1,200
   characters, and embeds each chunk with `embeddinggemma`. It then extracts entities and
   relationships per chunk with a legal extraction prompt, and writes everything to Neo4j.
3. **Entity resolution:** entities with the same label and name are merged across all
   documents. A party named in two contracts therefore becomes one node linked to both.

When you ask a question, the chunks are searched with the vector index (`chunk_embeddings`)
and the fulltext index (`chunk_fulltext`). For each match, the retriever adds the entities
and relationships linked to that chunk. The LLM sees only that context. The system prompt
tells it to refuse with *"I can't find that in the uploaded documents."* when the context
doesn't contain the answer, to use no outside legal knowledge, to cite file names, and not to
give legal advice. The prompts live in `backend/app/prompts.py`.

## Configuration

All settings are in `backend/.env`. See `backend/.env.example` for the full list.

| Setting | Default | Notes |
| --- | --- | --- |
| `NEO4J_URI` / `NEO4J_USERNAME` / `NEO4J_PASSWORD` / `NEO4J_DATABASE` | `neo4j://localhost:7687`, `neo4j`, –, `neo4j` | From Neo4j Desktop's connection details |
| `LLM_MODEL` | `gemma4:12b` | Any Ollama chat model |
| `EMBEDDING_MODEL` / `EMBEDDING_DIMENSIONS` | `embeddinggemma:300m` / `768` | Must match a pulled model name exactly (`ollama list`). Changing the model after ingesting requires dropping the `chunk_embeddings` index and re-ingesting |
| `OLLAMA_NUM_CTX` | `16384` | Context window for both extraction and chat |
| `OLLAMA_THINK` | `false` | Gemma 4 thinking mode (slower; not useful for JSON extraction) |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `1200` / `150` | Characters |
| `EXTRACTION_CONCURRENCY` | `2` | Parallel LLM calls per document |
| `RETRIEVAL_TOP_K` | `6` | Chunks retrieved per question |
| `HISTORY_WINDOW` | `10` | Earlier messages used for follow-up questions |

## REST API

Interactive docs are at <http://localhost:8000/docs>.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Status of Neo4j, APOC, indexes, Ollama, models, ingestion queue |
| POST | `/api/documents` | Upload a PDF (multipart field `file`); returns 202 and queues it |
| GET | `/api/documents` | Documents with status, stage, chunk and entity counts |
| GET | `/api/graph?document_id=&types=&limit=500` | Entity graph for the UI |
| GET | `/api/graph/meta` | Entity types and documents, for filters |
| GET/POST | `/api/conversations` | List / create conversations |
| GET | `/api/conversations/{id}` | A conversation with its messages |
| POST | `/api/conversations/{id}/messages` | Ask a question (`{"content": "..."}`); returns the answer, sources and subgraph |

## Scripts

```bash
# Ingest one PDF from the command line (same pipeline as the API)
.venv/bin/python backend/scripts/ingest_pdf.py path/to/contract.pdf

# End-to-end check against a running server: health, upload, question, follow-up, refusal
.venv/bin/python backend/scripts/smoke_test.py --pdf path/to/contract.pdf \
  --question "Who are the parties to the agreement?"
```

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Neo4j pill is red | Start the DBMS in Neo4j Desktop. Check `NEO4J_URI` and `NEO4J_PASSWORD` in `backend/.env`. |
| APOC pill is red | Neo4j Desktop → your DBMS → Plugins → install APOC, then restart the DBMS. Ingestion needs it. |
| LLM / Embeddings pill is red | `ollama pull gemma4:12b` and `ollama pull embeddinggemma:300m`. The names in `backend/.env` must match `ollama list` exactly. |
| `setup.sh` says "invalid model name" | `LLM_MODEL` or `EMBEDDING_MODEL` in `backend/.env` contains a space, quote or hidden character. The script prints the exact value it read. |
| "No text found in the PDF" | The PDF is scanned images. Run OCR on it first (e.g. `ocrmypdf in.pdf out.pdf`). |
| Few entities extracted | Some chunks may have produced invalid JSON and were skipped. See the backend log. A smaller `CHUNK_SIZE` can help. |
| Answers are slow | Each follow-up question makes two LLM calls (history summary and answer). The first call after idle also loads the model. |

## Known limitations

- Documents can be added but not deleted.
- Page numbers are not kept. Citations give the file name and excerpt number.
- Because the schema is extracted per document, labels can still differ slightly between
  documents (for example `Party` and `Company`). Telling the model which types already exist
  reduces this but does not remove it.
- Jobs that are queued or running when the server stops are lost. Upload those files again.
- The server must run as a single process, because the ingestion queue is in memory.
- There is no authentication. It binds to `127.0.0.1` by default. Don't expose it to a network as it is.
