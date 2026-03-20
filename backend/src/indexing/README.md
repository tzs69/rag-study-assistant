# Indexing Pipeline (RAG) - Backend Notes

This document describes the current indexing architecture implemented in this repository, including event-driven ingestion and deletion for chunk/vector lifecycle management.

## Scope

- Folder scope: `backend/src/indexing`
- App purpose: Accept uploaded documents, store source files in S3, then transform them into indexed vectors for retrieval-augmented generation (RAG).
- Current status:
  - Upload API to S3 is implemented.
  - AWS session and basic clients are implemented.
  - Ingestion and deletion workers are wired to SQS-wrapped S3 events.

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
  - `backend/src/indexing/clients/s3_client.py`
  - `backend/src/shared/clients/bedrock_client.py`
- Behavior:
  - Provide reusable cached clients for S3 and Bedrock Runtime.

5. Indexing services and repositories
- Files:
  - `backend/src/indexing/services/chunking_service.py`
  - `backend/src/indexing/services/embedding_service.py`
- Behavior:
  - Manifest repository and storage services are used by ingestion/deletion workers.

### Current runtime flow

1. Client sends multipart files to `POST /upload`.
2. API reads each file and stores directly into S3 bucket.
3. Request returns success after upload.
4. Ingestion worker performs chunking, embedding, vector upsert, and manifest finalize.

## Why Event-Driven Is Preferred Over Bucket-Scan Diff

A bucket scan approach (maintaining a local list and diffing objects after each upload) works for a prototype but is weaker for production:

- Performance cost grows with object count (frequent list operations).
- Race conditions when multiple uploads happen concurrently.
- Harder idempotency and duplicate prevention.
- Harder recovery/retry semantics.

An S3 event-driven design is simpler operationally at scale:

- Work is triggered per object creation event.
- Natural async boundary with queue-based retries.
- Cleaner failure handling via dead-letter queue.
- Easier horizontal scaling of workers.

## Proposed Target Pipeline (Event-Driven)

### High-level workflow diagram

```text
                    CURRENT IMPLEMENTED PATH

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


                    DELETION PIPELINE (MANIFEST-BASED)

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

## Proposed Responsibilities By Stage

### Stage 1: Upload 

- Keep upload endpoint thin and synchronous.
- Responsibility is only to accept files and place them in S3 reliably.
- Do not block user request on chunking/embedding latency.

### Stage 2: Notification and queue transport

- S3 emits object-created events.
- Event is sent to SQS queue (preferred) instead of direct compute trigger.
- Queue settings should include:
  - Visibility timeout sized to max processing time.
  - Redrive policy to DLQ after max receives.
  - Message retention for operational recovery window.

### Stage 3: Async ingestion worker

Worker should be a pure orchestrator with clear substeps:

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

### Stage 4: Document deletion handling (manifest-based)

Because this application does not rely on Bedrock Knowledge Bases, vector lifecycle must be handled explicitly when a raw document is removed.

Recommended design:

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
- Remove the manifest record after successful vector deletion.

4. Make delete flow idempotent
- If manifest is missing, treat as already cleaned.
- Repeated delete events should safely no-op.
- Record deletion outcomes for observability/auditing.

## Chunking Strategy Guidance (for implementation)

Recommended baseline strategy:

- Chunk by tokens (not characters) for model-aligned limits.
- Start with medium chunk size and moderate overlap.
- Keep stable chunk identity scheme:
  - `chunk_id = <doc_id>:<section_or_page>:<ordinal>`
- Preserve metadata for retrieval filtering and citation:
  - doc name/key
  - page/section
  - source URI
  - ingest timestamp

Good defaults to start testing:

- Chunk size: 400-800 tokens
- Overlap: 10-20%
- Tune based on retrieval quality and context window constraints.

## Idempotency and Update Semantics

Use object identity fields to avoid duplicate indexing:

- Primary key suggestion: `(bucket, key, version_id)`
- If versioning is disabled, fallback to `(bucket, key, etag)`

Define clear behavior for re-uploads:

- Same key + new content:
  - Re-index and replace existing vectors for that document key.
- Same event delivered multiple times:
  - Detect as duplicate and no-op.

Define clear behavior for document deletes:

- Delete event for existing document:
  - Delete all vectors listed in manifest, then delete manifest record.
- Delete event replay / duplicate:
  - If manifest does not exist, treat as already deleted (no-op).
- Re-upload after delete:
  - Create a fresh manifest and new vector keys for the new document version.

## Error Handling Model

Classify failures:

1. Transient (retryable)
- Bedrock throttling/timeouts
- Temporary S3/network failures
- Queue consumer timeouts

2. Permanent (non-retryable)
- Unsupported file format
- Corrupt/empty document after extraction
- Invalid event payload
- Missing manifest schema compatibility (if manifest format is invalid)

Operational behavior:

- Retry transient errors through queue redelivery.
- Route poison messages to DLQ after max retries.
- Emit structured logs for each stage with correlation fields.
- Keep separate metrics for ingestion failures vs deletion cleanup failures.

## Security and IAM Considerations

Minimum required access:

- Uploader/API:
  - `s3:PutObject` on raw document bucket.
- Worker:
  - `sqs:ReceiveMessage`, `sqs:DeleteMessage`, `sqs:ChangeMessageVisibility`
  - `s3:GetObject` on raw document bucket
  - `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:DeleteItem` on manifest table
  - Bedrock invoke permissions for embedding model
  - Vector store write/delete permissions

Additional controls:

- Restrict IAM resources to explicit ARNs.
- Enable server-side encryption on bucket/queue/store.
- Keep PII-sensitive metadata minimized.

## Observability Checklist

Track these metrics for production readiness:

- Queue depth and age of oldest message
- Worker success/failure rates
- End-to-end indexing latency (upload -> indexed)
- Embedding throughput and error rate
- Duplicate event rate and idempotent skips
- Deletion lag (delete event -> vectors removed)
- Orphan vector rate (vectors without manifest)

Useful structured log fields:

- `bucket`, `object_key`, `version_id/etag`
- `message_id`
- `doc_id`
- `chunk_count`
- `embedding_batch_count`
- `index_status`
- `manifest_key_count`
- `delete_status`

## Suggested Near-Term Milestones

1. Implement chunking and embedding service logic in existing stub files.
2. Add worker entrypoint and event parser.
3. Add queue-backed processing loop with retries and DLQ policy.
4. Integrate vector store client and upsert contract.
5. Add idempotency/state persistence.
6. Add tests for event parsing, idempotency, and end-to-end ingestion.
7. Add manifest persistence and deletion worker for S3 `ObjectRemoved` events.
8. Add tests for duplicate delete events and orphan-manifest recovery.

## Source-of-Truth Snapshot

As of this document, these files represent current implemented indexing-related logic:

- `backend/src/main.py`
- `backend/src/indexing/config.py`
- `backend/src/shared/config.py`
- `backend/src/shared/aws_session.py`
- `backend/src/shared/clients/bedrock_client.py`
- `backend/src/indexing/clients/s3_client.py`
- `backend/src/indexing/services/s3_gp_raw_document_store.py`
- `backend/src/indexing/services/chunking_service.py`
- `backend/src/indexing/services/embedding_service.py`
- `backend/src/indexing/services/manifest_repository.py`
- `backend/src/indexing/workers/ingest_lambda_worker.py`
- `backend/src/indexing/workers/delete_lambda_worker.py`

This README should be updated when:

- retrieval services are introduced under `backend/src/retrieval`,
- deletion finalization strategy changes (soft-delete vs hard-delete manifest),
- indexing contracts (chunk key/vector key schema) change.

