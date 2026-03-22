# Indexing Pipeline (RAG) - Backend Notes

This document describes the current indexing architecture implemented in this repository, including event-driven ingestion and deletion for chunk/vector lifecycle management.

## Scope

- Folder scope: `backend/src/indexing`
- App purpose: Accept uploaded documents, store source files in S3, then transform them into indexed vectors for retrieval-augmented generation (RAG).
- Current status:
  - Upload API to S3 is implemented.
  - AWS session and basic clients are implemented.
  - Ingestion and deletion workers are wired to SQS-wrapped S3 events.
  - Corpus change tracking is implemented via DynamoDB change records on ingest/delete finalize.

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

### Current runtime flow

1. Client sends multipart files to `POST /upload`.
2. API reads each file and stores directly into S3 bucket.
3. Request returns success after upload.
4. Ingestion worker performs chunking, embedding, vector upsert, and manifest finalize.
5. Ingestion/deletion finalization appends a corpus change record (`upsert`/`delete`) used by retrieval freshness checks.

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
      4 --> Chunk document
      5 --> Upload chunks as json into S3
        --> Generate embeddings on Chunks (Bedrock)
      6 --> Upsert vectors into S3 vector store
      7 --> Finalize ingestion event: persist indexing status/metadata
        --> On success, SQS ack is handled by the Lambda event source mapping

(Query path, downstream)
[Retriever] -> [Vector Store] -> [LLM answer synthesis]


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
      +--> Clear vector keys and finalize status to deleted
      +--> Ack message on success
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

4. Chunking
- Apply token-aware chunking strategy with overlap.
- Emit chunk-level metadata (`doc_id`, `chunk_id`, position offsets/pages).

5. Embedding
- Batch chunk texts to embedding model.
- Handle rate limits/retries with exponential backoff.

6. Vector upsert
- Upsert vectors and metadata in a deterministic way.
- Ensure repeated upserts for same chunk id are safe.

7. State tracking
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
- Finalize manifest by clearing `vector_keys` and setting status to `deleted`.

4. Make delete flow idempotent
- If manifest is missing, treat as already cleaned.
- Repeated delete events safely no-op.
- Record deletion outcomes for observability/auditing.

## Next Milestones

1. Add retrieval-side corpus monitor + orchestrator wiring to consume corpus change versions safely.
2. Implement BM25 artifact build/publish pipeline using chunk JSONL from shared store.
3. Add end-to-end tests for corpus change version bumps on ingest/delete success paths.
4. Add failure-mode tests to verify corpus change rows are not appended on failed finalize.
5. Add observability dashboards for manifest state transitions and corpus change lag.

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
- `backend/src/indexing/services/manifest_repository.py`
- `backend/src/indexing/workers/ingest_lambda_worker.py`
- `backend/src/indexing/workers/delete_lambda_worker.py`

This README should be updated when:

- retrieval-side corpus monitor/index refresh contracts are finalized under `backend/src/retrieval`,
- deletion finalization strategy changes (soft-delete vs hard-delete manifest),
- indexing contracts (chunk key/vector key schema) change.

