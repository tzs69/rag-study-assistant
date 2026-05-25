# Indexing Pipeline (RAG) - Backend Notes

This document describes the current indexing architecture implemented in this repository, including event-driven ingestion and deletion for chunk/vector lifecycle management.

## Scope

- Folder scope: `backend/src/indexing`
- App purpose: Accept uploaded documents, store source files in S3, then transform them into indexed vectors for retrieval-augmented generation (RAG).
- Current status:
  - Upload API to S3 is implemented.
  - AWS session and basic clients are implemented.
  - Ingestion and deletion workers are wired to SQS-wrapped S3 events.
  - Domain lexicon tracking is implemented (document term-frequency extraction + DynamoDB upsert/delete).
  - Corpus change tracking is implemented via DynamoDB change records on ingest/delete finalize.
  - BM25 update events are published from ingest/delete workers to a dedicated SQS queue.
  - BM25 update worker is implemented and maintains latest BM25 snapshot + pointer in S3.

## Current Implementation (As-Is)

### Implemented components

1. Upload API endpoint
- File: `backend/src/main.py`
- Behavior:
  - Exposes `POST /upload`.
  - Validates that files are present.
  - Delegates upload work to `S3GPRawDocumentStore`.

2. S3 upload service
- File: `backend/src/indexing/services/s3_gp_raw_document_store.py`
- Behavior:
  - Reads each uploaded file body.
  - Writes file to S3 with `put_object`.
  - Uses the uploaded filename as S3 object key.
  - Returns basic metadata (`name`, `size`) for uploaded files.

3. AWS config and session bootstrap
- Files:
  - `backend/src/indexing/config.py`
  - `backend/src/shared/config.py`
  - `backend/src/shared/aws_session.py`
- Behavior:
  - Loads indexing-specific config from `.env.local` under `backend/src/indexing`.
  - Loads shared AWS profile/region config from `.env.local` under `backend/src/shared`.
  - Creates cached boto3 session.

4. AWS clients
- Files:
  - `backend/src/shared/clients/s3_client.py`
  - `backend/src/shared/clients/bedrock_client.py`
- Behavior:
  - Provide reusable cached clients for S3 and Bedrock Runtime.

5. Indexing services and repositories
- Files:
  - `backend/src/indexing/services/chunking_service.py`
  - `backend/src/indexing/services/embedding_service.py`
  - `backend/src/indexing/services/manifest_repository.py`
  - `backend/src/shared/services/corpus_change_table.py`
  - `backend/src/shared/services/s3_gp_chunk_store.py`
  - `backend/src/shared/services/s3_vector_store.py`
- Behavior:
  - Ingestion/deletion workers use manifest + shared storage services and append corpus change events.

6. Domain lexicon services (for query-time spell correction support)
- Files:
  - `backend/src/indexing/services/document_terms_extractor.py`
  - `backend/src/shared/services/domain_lexicon_store.py`
- Behavior:
  - Ingestion worker extracts per-document term frequencies from normalized document text.
  - Ingestion worker upserts `(doc_id, term, doc_tf)` and collection-level term stats into DynamoDB.
  - Deletion worker removes a document's term contributions from DynamoDB.
  - Lexicon update path is best-effort and does not fail core indexing lifecycle transitions.

### Current runtime flow

1. Client sends multipart files to `POST /upload`.
2. API reads each file and stores directly into S3 bucket.
3. Request returns success after upload.
4. Ingestion worker reads/normalizes document text, builds doc-level term frequencies, then performs chunking, embedding, vector upsert.
5. Ingestion/deletion workers update domain lexicon DynamoDB tables (best-effort) using `upsert`/`delete` semantics by `doc_id`.
6. Ingestion/deletion finalization appends a corpus change record (`upsert`/`delete`) used by retrieval freshness checks.
7. Ingestion/deletion workers publish BM25 update events (`doc_id`, `op`, `corpus_version`) to BM25 update queue.
8. BM25 update worker consumes queue events, applies corpus deltas, and writes:
   - `bm25/snapshot.json` (latest snapshot; source-of-truth artifact that retrieval reads to serve non-stale keyword search results)
   - `bm25/latest.json` (latest pointer metadata)

## Current Pipeline (Event-Driven)

### High-level workflow diagram

```text
                    INDEXING PIPELINE

[User/Frontend]
      |
      v
[FastAPI POST /upload]  (backend/src/main.py)
      |
      v
[S3GPRawDocumentStore.put_object]  (backend/src/indexing/services/s3_gp_raw_document_store.py)
      |
      v
[Raw Document S3 Bucket]
      |
      | ObjectCreated:* event 
      v
[S3 Event Notification]
      |
      v
[Ingestion SQS Queue] -----> [DLQ]
      |
      v
[Ingestion Worker]
      | 
      | (For a single document)
      |
      1 --> Parse event payload and perform basic envelope validation
      2 --> Claim ingestion event 
      3 --> Read document from S3
      4 --> Build per-document term tf dictionary from normalized text
      5 --> Chunk document
      6 --> Upload chunks as json into S3
        --> Generate embeddings on Chunks (Bedrock)
      7 --> Upsert vectors into S3 vector store
      8 --> Best-effort upsert into domain lexicon store (DynamoDB)
      9 --> Finalize ingestion event: persist indexing status/metadata
        --> On success, SQS ack is handled by the Lambda event source mapping

(Query path, downstream)
[Retriever] -> [Spell correction (domain lexicon + base lexicon)] -> [Vector Store / BM25] -> [Re-ranker] -> [LLM answer synthesis]


                    DELETION PIPELINE 

[Raw Document S3 Bucket]
      |
      | ObjectRemoved:* event
      v
[Deletion SQS Queue] -----> [DLQ]
      |
      v
[Deletion Worker]
      |
      +--> Parse event and derive doc_id
      +--> Claim deletion + fetch vector keys from manifest (DynamoDB)
      +--> Delete chunk artifact in /chunks
      +--> DeleteVectors(keys=[...]) in vector store
      +--> Best-effort delete doc term mappings from domain lexicon store (DynamoDB)
	      +--> Clear vector keys and finalize status to deleted
	      +--> Ack message on success


                    BM25 UPDATE PIPELINE

[Ingestion Worker]--------+
                          |
[Deletion Worker]---------+--> [BM25 Update SQS Queue] -----> [DLQ]
                                        |
                                        v
                                 [BM25 Update Worker]
                                        |
                                        +--> Parse/validate queue payloads
                                        +--> Compare target_version vs bm25/latest.json
                                        +--> Warm-start from bm25/snapshot.json (if exists)
                                        +--> Fallback bootstrap from manifest indexed docs
                                        +--> Apply corpus deltas from corpus-change table
                                        +--> Validate BM25 build
                                        +--> Write bm25/snapshot.json
                                        +--> Write bm25/latest.json
```

## Implemented Pipeline Stages

### Document upload 

- Accept files and place them in S3 reliably.
- Does not block user request on chunking/embedding latency.

### Notification and queue transport

- S3 emits object-created events and object-removed events.
- Instead if direct compute triggers, S3-emitted events are sent to appropriate SQS queues for further action by workers down the line.

### Document ingestion handling (post-upload)

Document ingestion process is handled by a documnet ingestion lambda worker coordinating across different services.
Worker is implemented as a pure orchestrator with these substeps:

1. Parse event message
- Extract bucket, object key, version id (or ETag), event timestamp.
- Reject malformed payloads.

2. Enforce idempotency
- Build deterministic document event id from object identity.
- Skip if already processed successfully.
- Allow safe reprocessing if document content changed.

3. Load and normalize document
- Download object bytes from S3.
- Convert supported formats to text.
- Attach source metadata (doc_id/key, filename, mime type, timestamps).

4. Extract document term frequencies (spell-lexicon support)
- Normalize/tokenize extracted text and build `term -> doc_tf` mapping.
- Keeps the mapping in memory for later domain-lexicon db upsert.

5. Chunking
- Apply token-aware chunking strategy with overlap.
- Emit chunk-level metadata (`doc_id`, `chunk_id`, position offsets/pages).

6. Embedding
- Batch chunk texts to embedding model.
- Handle rate limits/retries with exponential backoff.

7. Vector upsert
- Upsert vectors and metadata in a deterministic way.
- Ensure repeated upserts for same chunk id are safe.

8. Domain lexicon upsert (best-effort)
- Upsert document term frequencies into DynamoDB-backed domain lexicon store.
- Failures are logged but do not fail core indexing transitions.

9. State tracking
- Record status transitions: `received -> processing -> indexed`.
- On failure: `failed` plus error class and retry count.
- Persist corpus-level change stream records (`change_id`, `doc_id`, `op`, `updated_at`) on successful finalize.

### Document deletion handling

Document deletion process is handled by a document deletion lambda worker.
Because this application does not rely on Bedrock Knowledge Bases, vector lifecycle is handled explicitly when a raw document is removed.

Current design:

1. Keep a vector manifest per document
- During ingestion, create deterministic vector keys per chunk:
  - `docId#0001`, `docId#0002`, ...
- Persist these keys in a manifest record keyed by `docId` (DynamoDB recommended).

2. Trigger deletion worker from S3 delete events
- Subscribe to `ObjectRemoved:*` notifications.
- Route events into a dedicated deletion queue.

3. Execute deterministic cleanup on delete
- Resolve `docId` from the S3 event/object key mapping.
- Look up manifest for that `docId`.
- Call vector store delete API with all keys from manifest.
- Best-effort delete document term mappings from DynamoDB domain lexicon store.
- Finalize manifest by clearing `vector_keys` and setting status to `deleted`.

4. Make delete flow idempotent
- If manifest is missing, treat as already cleaned.
- Repeated delete events safely no-op.
- Record deletion outcomes for observability/auditing.

## Next Milestones

1. Add end-to-end tests for BM25 event publish on ingest/delete success paths.
2. Add failure-mode tests for BM25 worker retry behavior and partial-batch failures.
3. Add observability dashboards for BM25 queue lag, snapshot publish latency, and pointer version drift.
4. Add optional periodic reconciliation job to rebuild snapshot from manifest for drift recovery.
5. Add structured alerting on BM25 snapshot publish failures and DLQ growth.

## Source-of-Truth Snapshot

As of this document, these files represent current implemented indexing-related logic:

- `backend/src/main.py`
- `backend/src/indexing/config.py`
- `backend/src/shared/config.py`
- `backend/src/shared/aws_session.py`
- `backend/src/shared/clients/bedrock_client.py`
- `backend/src/shared/clients/s3_client.py`
- `backend/src/shared/services/s3_base_store.py`
- `backend/src/shared/services/s3_gp_chunk_store.py`
- `backend/src/shared/services/s3_vector_store.py`
- `backend/src/shared/services/corpus_change_table.py`
- `backend/src/indexing/services/s3_gp_raw_document_store.py`
- `backend/src/indexing/services/chunking_service.py`
- `backend/src/indexing/services/embedding_service.py`
- `backend/src/indexing/services/document_terms_extractor.py`
- `backend/src/indexing/services/manifest_repository.py`
- `backend/src/indexing/clients/sqs_client.py`
- `backend/src/indexing/services/bm25_update_event_publisher.py`
- `backend/src/indexing/services/indexed_documents_loader.py`
- `backend/src/indexing/services/latest_chunk_index_loader.py`
- `backend/src/indexing/workers/ingest_lambda_worker.py`
- `backend/src/indexing/workers/delete_lambda_worker.py`
- `backend/src/indexing/workers/bm25_update_lambda_worker.py`
- `backend/src/shared/services/chunk_loader.py`
- `backend/src/shared/services/chunk_index.py`
- `backend/src/shared/services/corpus_delta_applier.py`
- `backend/src/shared/services/corpus_monitor.py`
- `backend/src/shared/services/domain_lexicon_store.py`

This README should be updated when:

- retrieval-side corpus monitor/index refresh contracts are finalized under `backend/src/retrieval`,
- BM25 snapshot contract (schema keys, pointer semantics, key names) changes,
- deletion finalization strategy changes (soft-delete vs hard-delete manifest),
- indexing contracts (chunk key/vector key schema) change.

