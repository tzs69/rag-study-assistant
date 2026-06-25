# Indexing Pipeline

## Scope

This document describes the indexing architecture implemented inside `backend/src/indexing` and the relevant indexing-related shared services under `backend/src/shared`. It covers the AWS-hosted event-driven ingestion, deletion and BM25 artifact update lambda runtimes, along with their supporting services for document parsing, chunking, embedding, vector store writes, manifest/indexing status tracking, domain lexicon updates, corpus state tracking, and S3/DynamoDB/SQS integration.

<br/>

## Current Runtime Flow

### Upload -> Ingestion Process

1. **Client sends multipart files to `POST /upload`**
   - The FastAPI upload endpoint accepts one or more files in the same request
   - The request path only covers raw file upload; chunking, embedding, vector writes, and BM25 refresh happen asynchronously after S3 emits events

2. **API reads each file and stores directly into the S3 general-purpose bucket**
   - `S3GPRawDocumentStore` writes each file under the configured raw prefix using a UUID-suffixed key
   - The original filename is stored as S3 object metadata, while the generated S3 key becomes the application `doc_id`

3. **Request returns success after upload.**
   - The API returns uploaded file metadata once S3 accepts the raw objects
   - At this point the document may still show as `uploaded` until the ingestion worker claims and finalizes indexing

4. **S3 object-created events are transported through SQS to the ingestion worker**
   - S3 emits `ObjectCreated:*` events for raw document uploads
   - The events are routed to the ingestion queue so the Lambda worker can process each document independently and retry failed messages through the event source mapping/DLQ setup

5. **Ingestion worker parses the event and claims ingestion**
   - `ingestion_handler` unwraps the SQS body, validates the nested S3 event, extracts bucket/key data, and ignores malformed or non-create events
   - The worker decodes the S3 object key into `doc_id`
   - `ManifestRepository.claim_reclaim_ingestion` creates a manifest row with `status="ingesting"` and empty `vector_keys`, or reclaims only a prior `ingest failed` record
   - Existing non-reclaimable rows are skipped so duplicate S3 events do not re-run a successful ingest

6. **Ingestion worker reads and normalizes document text**
   - `DocumentReaderService` downloads the raw object from S3 and extracts text for supported file types: `.pdf`, `.docx`, `.txt`, and `.md`
   - Extracted text is whitespace-normalized into a `DocumentText` payload used by downstream indexing services

7. **Ingestion worker builds document term frequencies for spell-correction support**
   - `build_term_frequency_dict` tokenizes/normalizes the extracted text and builds an in-memory `term -> doc_tf` mapping for the document
   - This mapping is later written to the DynamoDB-backed domain lexicon store as a best-effort side effect

8. **Ingestion worker chunks the document**
   - `SemanticChunkingService` validates the extracted text, normalizes paragraphs, and creates primary semantic chunks
   - Undersized chunks are merged into adjacent chunks
   - Oversized chunks are split with the recursive character splitter and then cleaned up for small overlapping sub-chunks
   - The service emits chunk metadata including `doc_id` and deterministic `chunk_id` values derived from the raw S3 key

9. **Ingestion worker stores chunk artifacts and vectors**
   - `S3GPChunkStore` writes the document chunk set as a JSONL artifact under the configured chunks prefix (`chunks/`)
   - `EmbeddingService` embeds chunk text with the shared Bedrock embedding model.
   - `S3VectorStore` upserts the resulting vector records into the S3 Vector index using each chunk ID as the vector key

10. **Ingestion worker updates domain lexicon DynamoDB tables**
    - `DomainLexiconWriter.upsert_document_terms` writes document-level term frequencies and collection-level term stats
    - Failures are logged but do not fail the core indexing lifecycle because retrieval can still use vector/BM25 paths without spell-correction freshness

11. **Ingestion worker finalizes indexing state**
    - `ManifestRepository.update_vectors_finalize_ingestion` stores the vector keys and transitions the manifest to `indexed`
    - The finalize update is conditional on the same Lambda invocation still owning the `ingesting` claim
    - `CorpusChangeTable.add_change_record` appends an `upsert` change record with `change_id`, `doc_id`, `op`, and `updated_at` for retrieval freshness checks

12. **Ingestion worker publishes a BM25 update event**
    - `BM25UpdateEventService` publishes `{ "doc_id": ..., "op": "upsert", "corpus_version": ... }` to the BM25 update queue after successful manifest and corpus-change finalization
    - Publish failures are logged separately and do not roll back the already-finalized vector/chunk lifecycle

<br/>

### Document Deletion Process

1. **Client sends `DELETE /documents/{doc_id}` for an indexed document**
   - The FastAPI delete endpoint checks the manifest status before deleting the raw S3 object
   - The API only deletes documents currently marked `indexed`; other statuses return a conflict instead of racing active ingestion/deletion work

2. **API deletes the raw object from the S3 general-purpose bucket**
   - `S3GPRawDocumentStore.delete_raw_doc` deletes the exact S3 key represented by `doc_id`
   - The user-facing request returns once the raw object delete call succeeds; chunk/vector cleanup is handled asynchronously

3. **S3 object-removed events are transported through SQS to the deletion worker**
   - S3 emits `ObjectRemoved:*` events for raw document deletion
   - The events are routed to the deletion queue so cleanup can retry independently from the API request

4. **Deletion worker parses the event and claims deletion**
   - `deletion_handler` unwraps the SQS body, validates the nested S3 delete event, rejects unrelated buckets/non-delete events, and derives `doc_id` from the deleted object key
   - `ManifestRepository.claim_reclaim_deletion` transitions only `indexed` or `delete failed` records to `deleting`
   - The same claim response returns the stored `vector_keys` required for vector cleanup

5. **Deletion worker removes document-derived artifacts**
   - `S3GPChunkStore.delete_chunks_for_docid` deletes the chunk JSONL artifact for the document
   - `S3VectorStore.delete_vectors` deletes stored vectors when the manifest contains vector keys
   - `DomainLexiconWriter.delete_document` removes the document's term contributions from DynamoDB as a best-effort side effect

6. **Deletion worker finalizes deletion state**
   - `ManifestRepository.clear_vectors_finalize_deletion` clears `vector_keys` and transitions the manifest to `deleted`.
   - The finalize update is conditional on the same Lambda invocation still owning the `deleting` claim
   - `CorpusChangeTable.add_change_record` appends a `delete` change record for retrieval freshness checks

7. **Deletion worker publishes a BM25 update event**
   - `BM25UpdateEventService` publishes `{ "doc_id": ..., "op": "delete", "corpus_version": ... }` to the BM25 update queue after successful deletion finalization
   - Repeated or non-reclaimable delete events safely skip at the manifest-claim stage

<br/>

### BM25 Artifact Update Process

1. **Ingestion and deletion workers publish corpus update events**
   - Each successful ingest/delete finalization creates a corpus change record and sends a BM25 queue message containing `doc_id`, `op`, and `corpus_version`
   - `corpus_version` corresponds to the corpus change table's monotonically allocated `change_id`

2. **BM25 update worker parses and validates queue payloads**
   - `bm25_update_handler` accepts only events with a non-empty `doc_id`, `op` equal to `upsert` or `delete`, and a positive integer `corpus_version`
   - Malformed records are skipped as non-retried records, while valid records are eligible for partial-batch retry if rebuild fails

3. **BM25 update worker determines whether rebuild is needed**
   - The worker computes `target_version` as the highest corpus version in the valid SQS batch
   - It reads `bm25/pointer.json` through `load_latest_pointer`
   - If the pointer's corpus version is already at or ahead of `target_version`, the worker returns success without rewriting artifacts

4. **BM25 update worker builds the baseline in-memory chunk index**
   - The preferred path warm-starts from the existing `bm25/snapshot.json`
   - If no snapshot is available, the worker bootstraps from indexed manifest rows and their chunk JSONL artifacts

5. **BM25 update worker applies corpus deltas**
   - `CorpusMonitor` reads corpus changes newer than the pointer version
   - `apply_changes` updates the in-memory chunk index by loading changed document chunks for `upsert` records and removing document chunks for `delete` records

6. **BM25 update worker validates and publishes BM25 artifacts**
   - The worker constructs a LangChain `BM25Retriever` in memory to fail fast before publishing invalid artifacts
   - It writes the updated `bm25/snapshot.json` first
   - It writes `bm25/pointer.json` only after the snapshot write succeeds, so retrieval refreshes only to a published snapshot

7. **BM25 update worker returns an SQS partial-batch response**
   - Successful rebuilds return `{"batchItemFailures": []}`
   - Rebuild failures return the valid message IDs as batch failures so SQS can retry those update events

<br/>

## Workflow Diagrams

### Indexing/Ingestion Pipeline

```text

[User/Frontend]
      |
      v
[FastAPI POST /upload]  (backend/src/main.py)
      + ---> Each upload request can contain multiple documents,
      |      but each document is packaged into a separate event 
      |      and each event is processed on its own by the ingestion worker
      |
      v
[S3GPRawDocumentStore.upload_docs_async]  (backend/src/indexing/services/s3_gp_raw_document_store.py)
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

```

<br>

### Deletion Pipeline

```text

[User/Frontend]
      |
      v
[FastAPI DELETE /documents/{doc_id}]  (backend/src/main.py)
      + ---> Each delete request is for a single uploaded document only
      |
      v
[S3GPRawDocumentStore.delete_raw_doc]  (backend/src/indexing/services/s3_gp_raw_document_store.py)
      |
      v
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

```

<br>

### BM25 Artifacts Update Pipeline

```text

[Ingestion Worker]--Upload Finalized--+
                                      |
[Deletion Worker]---Delete Finalized--+--> [BM25 Update SQS Queue] -----> [DLQ]
                                                  |
                                                  v
                                            [BM25 Update Worker]
                                                  |
                                                  +--> Parse/validate queue payloads
                                                  +--> Compare target_version vs bm25/pointer.json
                                                  +--> Warm-start from bm25/snapshot.json (if exists)
                                                  +--> Fallback bootstrap from manifest indexed docs
                                                  +--> Apply corpus deltas from corpus-change table
                                                  +--> Validate BM25 build
                                                  +--> Write bm25/snapshot.json
                                                  +--> Write bm25/pointer.json
```

<br/>

## Indexing Components

### Upload API endpoint

- File: `backend/src/main.py`
- Exposes `POST /upload` for raw document uploads
- Validates that files are present before attempting S3 writes
- Delegates raw object persistence to `S3GPRawDocumentStore`
- Returns after upload success; downstream ingestion is event-driven through S3/SQS/Lambda

### Document listing and deletion API endpoints

- File: `backend/src/main.py`
- Exposes `GET /documents` for frontend document inventory/status display
- Combines raw S3 object listing with manifest status lookups
- Exposes `DELETE /documents/{doc_id}` for deleting a raw document by exact S3 key
- Allows delete only when manifest status is `indexed`, then relies on S3 delete events to trigger asynchronous cleanup

### `S3GPRawDocumentStore`

- File: `backend/src/indexing/services/s3_gp_raw_document_store.py`
- Uploads raw files under the configured raw prefix using UUID-suffixed S3 keys
- Stores the original filename in S3 object metadata
- Lists raw documents for the Knowledge Base UI
- Deletes a raw document by exact object key, which later emits the S3 deletion event consumed by the deletion worker

### AWS configuration and clients

- Files:
  - `backend/src/indexing/config.py`
  - `backend/src/shared/config.py`
  - `backend/src/shared/aws_session.py`
  - `backend/src/shared/clients/bedrock_client.py`
  - `backend/src/shared/clients/dynamodb_client.py`
  - `backend/src/shared/clients/s3_client.py`
  - `backend/src/indexing/clients/sqs_client.py`
- Behaviour:
  - Centralizes environment-driven resource names and creates shared AWS sessions/clients for Bedrock, DynamoDB, S3, S3 Vectors, and SQS used by indexing workers
  - Keeps worker/service code focused on indexing Behaviour instead of boto3 setup details

### Lambda workers

- Files:
  - `backend/src/indexing/workers/ingest_lambda_worker.py`
  - `backend/src/indexing/workers/delete_lambda_worker.py`
  - `backend/src/indexing/workers/bm25_update_lambda_worker.py`
- Behaviour:
  - `ingestion_handler` processes SQS-wrapped S3 create events into chunk artifacts, vectors, manifest updates, corpus-change records, domain lexicon updates, and BM25 update events
  - `deletion_handler` processes SQS-wrapped S3 delete events into chunk/vector cleanup, manifest deletion finalization, corpus-change records, domain lexicon cleanup, and BM25 update events
  - `bm25_update_handler` consumes BM25 update events, applies corpus deltas, and publishes the latest BM25 snapshot/pointer artifacts

### Document reading and text extraction

- File: `backend/src/indexing/services/document_reader_service.py`
- Downloads user-uploaded documents as raw source objects from S3 by `doc_id`
- Extracts text from `.pdf`, `.docx`, `.txt`, and `.md` files
- Normalizes whitespace and returns a `DocumentText` payload for chunking and term extraction

### Chunking and embedding services

- Files:
  - `backend/src/indexing/services/chunking_service.py`
  - `backend/src/indexing/services/embedding_service.py`
- Behaviour:
  - `SemanticChunkingService` creates storage-ready `Chunk` objects from extracted document text
  - Primary chunking uses LangChain semantic chunking with a Bedrock-backed embedding model
  - Oversized chunks fall back to recursive character splitting with overlap
  - `EmbeddingService` embeds chunk text with the shared Bedrock embedding model and wraps results as `VectorRecord` payloads suitable for upsert into S3 Vector index

### Chunk and vector stores

- Files:
  - `backend/src/shared/services/s3_base_store.py`
  - `backend/src/shared/services/s3_gp_chunk_store.py`
  - `backend/src/shared/services/s3_vector_store.py`
- Behaviour:
  - `BaseStore` provides the shared S3/S3 Vector client wrapper used by storage services
  - `S3GPChunkStore` writes, reads, and deletes per-document chunk JSONL artifacts
    - Chunks are stored in same bucket as uploaded documents but in different folders (`raws/` vs `chunks/`)
  - `S3VectorStore` upserts and deletes embedded chunk vectors (`VectorRecord` objects) in the S3 Vector index
  - The same chunk/vector artifacts are later read by retrieval services for keyword and semantic search

### State tracking (document manifest and corpus change state) tables

- Files:
  - `backend/src/indexing/services/manifest_repository.py`
  - `backend/src/shared/services/corpus_change_table.py`
- Behaviour:
  - `ManifestRepository` tracks document lifecycle state: `ingesting`, `indexed`, `ingest failed`, `deleting`, `deleted`, and `delete failed`
  - Ingestion finalization stores vector keys and marks the document `indexed`
  - Deletion finalization clears vector keys and marks the document `deleted`
  - `CorpusChangeTable` appends ordered `upsert`/`delete` records used by retrieval freshness checks and BM25 artifact rebuilds

### Domain lexicon services (for query-time spell correction support)

- Files:
  - `backend/src/indexing/services/document_terms_extractor.py`
  - `backend/src/shared/services/domain_lexicon_store.py`
- Behaviour:
  - Ingestion worker extracts per-document term frequencies from normalized document text
  - Ingestion worker upserts `(doc_id, term, doc_tf)` and collection-level term stats into DynamoDB
  - Deletion worker removes a document's term contributions from DynamoDB
  - Lexicon update path is best-effort and does not fail core indexing lifecycle transitions

### BM25 update event and artifact helpers

- Files:
  - `backend/src/indexing/services/bm25_update_event_publisher.py`
  - `backend/src/indexing/services/indexed_documents_loader.py`
  - `backend/src/indexing/services/latest_chunk_index_loader.py`
  - `backend/src/shared/services/chunk_loader.py`
  - `backend/src/shared/services/chunk_index.py`
  - `backend/src/shared/services/corpus_monitor.py`
  - `backend/src/shared/services/corpus_delta_applier.py`
  - `backend/src/shared/services/latest_bm25_pointer_loader.py`
- Behaviour:
  - `BM25UpdateEventService` publishes post-finalization update events to the BM25 update queue
  - `load_latest_pointer` reads `bm25/pointer.json` so the update worker can skip stale/redundant rebuilds
    - `pointer.json` stored in same S3 Bucket as uploaded documents but under `bm25/` folder
  - `load_chunk_index_from_latest_snapshot` warm-starts from `bm25/snapshot.json` when available
    - `snapshot.json` also stored in same S3 Bucket as uploaded documents but under `bm25/` folder
  - `load_indexed_documents` bootstraps from manifest rows and chunk artifacts when no snapshot exists
  - `CorpusMonitor` and `apply_changes` apply ordered corpus deltas to `InMemoryChunkIndex`
  - `load_documents_for_doc_id` reads changed document chunks from S3 during BM25 delta application


<br/>

## Source-of-Truth Files

- `backend/src/main.py`
- `backend/src/indexing/config.py`
- `backend/src/shared/config.py`
- `backend/src/shared/aws_session.py`
- `backend/src/shared/clients/bedrock_client.py`
- `backend/src/shared/clients/dynamodb_client.py`
- `backend/src/shared/clients/s3_client.py`
- `backend/src/shared/services/s3_base_store.py`
- `backend/src/shared/services/s3_gp_chunk_store.py`
- `backend/src/shared/services/s3_vector_store.py`
- `backend/src/shared/services/corpus_change_table.py`
- `backend/src/indexing/services/s3_gp_raw_document_store.py`
- `backend/src/indexing/services/document_reader_service.py`
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
- `backend/src/shared/services/latest_bm25_pointer_loader.py`
- `backend/src/shared/services/domain_lexicon_store.py`

