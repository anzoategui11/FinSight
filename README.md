# FinSight RAG — API + indexing worker

A local Docker Compose development implementation:

- `api`: FastAPI upload, query, and status endpoints
- `worker`: Redis Queue (RQ) consumer that extracts, chunks, embeds, and indexes
- `redis`: asynchronous job queue
- `qdrant`: vector database
- Snowflake (external): filing catalog
- OpenRouter (external): language model
- LangSmith (external): query tracing

## Setup

1. Create your existing Snowflake `FINSIGHT.RAG.DOCUMENT_CATALOG` table, or run `sql/catalog.sql` in Snowsight with the necessary role.
2. Configure key-pair authentication for a Snowflake service user, and grant it `USAGE` on warehouse/database/schema and `SELECT`, `INSERT`, `UPDATE` on the catalog table. This service requires non-interactive authentication; `externalbrowser` does not work in a headless worker.
3. Copy `.env.example` to `.env`, fill all credentials. Keep `.env` out of git.
4. Put your Snowflake private key in `secrets/snowflake_key.p8` (untracked), with appropriate file permissions. In a real deployment, use a secrets manager or Kubernetes Secret.
5. Run `docker compose up --build -d` and inspect logs: `docker compose logs -f worker api`.
6. Open http://localhost:8000/docs (the endpoints require the configured X-API-Key header).

### Upload a report (PowerShell)

```powershell
curl.exe -X POST http://localhost:8000/documents -H "X-API-Key: YOUR_LOCAL_KEY" -F "company=AAPL" -F "year=2024" -F "file=@data/raw/original_doc/AAPL_2024.html"
```

The response is `202 Accepted` with a `job_id` and `source_file`. Poll:

```powershell
curl.exe -H "X-API-Key: YOUR_LOCAL_KEY" http://localhost:8000/jobs/JOB_ID
curl.exe -H "X-API-Key: YOUR_LOCAL_KEY" http://localhost:8000/documents/SOURCE_FILE
```

### Ask a question

```powershell
curl.exe -X POST http://localhost:8000/ask -H "X-API-Key: YOUR_LOCAL_KEY" -H "Content-Type: application/json" -d '{"question":"What risks did Apple mention?"}'
```

Note: PowerShell quoting for native executables depends on your shell version. FastAPI's interactive `/docs` page is often easier for initial tests.

## Design notes and limitations

- Uploaded filenames are unique, so re-uploading an identical filing under a new ID creates a new catalog row and potentially duplicate search results. Deduplication by logical filing ID + content digest is a follow-up improvement.
- The worker runs **one indexing job at a time** by default. Avoid concurrent workers indexing the same source or creating the Qdrant collection simultaneously; add locks before scaling.
- The indexer deletes existing source vectors before writing replacements. This is not a cross-system transaction with Snowflake; use versioned vectors plus a cutover for production.
- Upload status is held in Redis until the worker begins, then in Snowflake. Jobs lost between saving and enqueueing can leave an orphan upload. Production needs durable object storage, job reconciler, and idempotency keys.
- Snowflake schema uses a primary key constraint for documentation; Snowflake standard tables do not enforce it.
- Only supports HTML, PDF and plain-text filings; scanned PDFs require an OCR pipeline (not provided).
- Embedding model must fit vector dimensions in the target Qdrant collection. For a changed model, use a new collection name.
- Qdrant and Redis are not exposed publicly; API and dashboard are bound to localhost. Docker Compose does not make this deployment production hardened.
- RQ is a simple dev queue. Hardening could include retries, dead-letter recovery, explicit trace propagation, worker health metrics, and outbox transactions.
- Avoid committing real financial or confidential uploaded documents. LangSmith traces can contain questions and retrieved source excerpts.
