# Retrieval Pipeline

## Scope

This document describes the overall retrieval architecture under `backend/src/retrieval`, the relevant shared services under `backend/src/shared`, and the related cross-encoder reranker service under `backend/src/ce_rerank`. It covers query normalization, optional query-time spell correction, BM25 keyword retrieval, S3 vector cosine similarity semantic search, Reciprocal Rank Fusion (RRF), best-effort cross-encoder reranking, and in-memory BM25/chunk-index refresh mechanism. The documented retrieval pipeline produces the ranked chunk context consumed by the chat generation pipeline under `backend/src/chat`.

<br/>

## Current Runtime Flow

1. `/chat` receives a user query and passes it to `RetrievalOrchestrator.search`
2. The orchestrator normalizes the query
3. Optional spell correction rewrites the retrieval query when enabled
4. The orchestrator snapshots the current BM25 retriever and chunk index under lock
5. Keyword retrieval (BM25) and semantic retrieval (vector cosine similarity) run concurrently
6. Each branch returns a ranked `List[Document]`; failed branches log and fall back to an empty list
7. `rrf_combine` deduplicates by `chunk_id`, computes RRF scores, and returns the top fused candidates
8. If the reranker service is healthy, the orchestrator sends RRF candidates to the cross-encoder reranker
9. Reranking failures are logged and the orchestrator falls back to the RRF-ranked candidates
10. The final ranked `Document` list is returned to `/chat`, which then passes the same list down to `ChatOrchestrator` for LLM answer generation

<br/>

## Workflow Diagrams

### Retrieval + Chat Pipeline

```text         

[User/Frontend Chat UI]
      |
      v
[Next.js POST /api/chat]
      |
      v
[FastAPI POST /chat]  (backend/src/main.py)
      |
      v
[RetrievalOrchestrator.search]  (backend/src/retrieval/retrieval_orchestrator.py)
      |
      +--> Normalize query
      |
      +--> Optional spell correction
      |       |
      |       +--> Domain lexicon candidates (DynamoDB collection term stats)
      |       +--> Base English lexicon fallback (backend/src/retrieval/data/base_english_lexicon.json)
      |
      +--> Snapshot current retrieval state under lock
      |       |
      |       +--> In-memory chunk index
      |       +--> In-memory BM25 retriever
      |
      +-----------> Run retrieval branches concurrently
                                   |
                                   |
                                   v
[SemanticRetrievalService] <-------+-------> [KeywordRetrievalService]
              |                                         |
              v                                         |                       
   Embed query with Bedrock                             |
              |                                         |
              v                                         v
    Query S3 Vector index             BM25 search over in-memory chunk corpus
              |                                         |
              v                                         |
   Map returned vector keys                             |
   back to in-memory chunk Documents                    |
              |                                         |
              v                                         v
         [Keyword results]-------> + <--------[Semantic results]
                                   |
                                   v
                        [Reciprocal Rank Fusion]
                                   |
                                   +--> Deduplicate by chunk_id
                                   +--> Add keyword/semantic rank metadata
                                   +--> Return top fused candidates
                                   |
                                   |
                                   v
                           [RerankerClient]
                                   |
                                   +--> GET /health on reranker service
                                   |
                                   +--> If healthy:
                                   |       POST /rerank with [query, candidate_text] pairs
                                   |       attach rerank_score and sort descending
                                   |
                                   +--> If unavailable or rerank fails:
                                   |       fall back to RRF-ranked candidates
                                   |
                                   v
                     [Final ranked chunk Documents]
                                   |
                                   v
                    [ChatOrchestrator.stream_answer]
                                   |
                                   +--> Build messages from:
                                   |       - system prompt
                                   |       - in-memory session chat history
                                   |       - retrieved context chunks
                                   |
                                   +--> Stream answer from Bedrock Converse
                                   |
                                   v
                          [FastAPI SSE stream]
                                   |
                                   +--> sse_started
                                   +--> sse_in_progress
                                   +--> sse_completed / sse_error
                                   |
                                   v
                     [Next.js API proxy forwards SSE]
                                   |
                                   v
                  [Frontend appends assistant message chunks]

```


### In-memory BM25 Index Update Workflow
         
```text

         
         [BM25 update Lambda]
               +--> Document /
               |
               +--> Writes bm25/snapshot.json and bm25/pointer.json to S3
                       |
                       v
         [RetrievalOrchestrator background poller]
               |
               +--> Poll bm25/pointer.json every BM25_POLL_INTERVAL_SECONDS
               +--> If corpus_version advanced:
                       |
                       +--> Load bm25/snapshot.json
                       +--> Rebuild in-memory chunk index
                       +--> Rebuild in-memory BM25 retriever
                       +--> Atomically swap retrieval state under lock
```

<br/>

## Retrieval Components

### `RetrievalOrchestrator`

- File: `backend/src/retrieval/retrieval_orchestrator.py`
- Retrieval orchestrator service owns the retrieval flow used by `/chat` (not to be confused with chat orchestrator which owns the LLM answer generation process);
- Coordinates query normalization, optional spell correction, keyword retrieval, semantic retrieval, RRF, and reranking
- Starts a background BM25 pointer poller on FastAPI lifespan startup
- Bootstraps retrieval state from indexed document manifests and S3 chunk artifacts
- Refreshes in-memory BM25/chunk state from the latest S3 BM25 snapshot when the pointer version advances

### Query preprocessing

- Files:
  - `backend/src/retrieval/services/query_basic_normalizer.py`
  - `backend/src/retrieval/services/spell_correction/spell_correction_query_preprocessor.py`
- Behavior:
  - `basic_query_normalize` tokenizes the raw query, strips leading/trailing punctuation, and applies the shared token normalization policy
  - `extract_for_spell_correction` builds spell-correction lookup metadata from normalized query tokens

### `SpellCorrector`

- File: `backend/src/retrieval/services/spell_correction/spell_corrector.py`
- Adds isolated word spell correction functionality with candidates generated using prefix matching
- Runs only when `ENABLE_SPELL_CORRECTION` is enabled
- Spell correction candidates retrieval process:
  - Initial retrieval from domain lexicon candidates from DynamoDB collection term stats through `DomainLexiconReader`
  - Falls back to base English lexicon `backend/src/retrieval/data/base_english_lexicon.json` (generated by `\backend\scripts\generate_base_lexicon.py`) if not enough domain lexicon candidates found
- Scores candidates with edit similarity, character-bigram Jaccard similarity, and frequency signals
- Falls back to the original query if spell correction fails

### `KeywordRetrievalService`

- File: `backend/src/retrieval/services/keyword_retriever.py`
- Uses LangChain's BM25 retriever over the in-memory chunk corpus
- Returns `List[Document]` in ranked order
- Uses a lock around BM25 search because the underlying retriever `k` value is mutated per search

### `SemanticRetrievalService`

- File: `backend/src/retrieval/services/semantic_retriever.py`
- Embeds the query with the same Bedrock embedding model used during indexing
- Queries the S3 Vector index for nearest chunk vectors
- Maps returned vector keys back to chunk `Document` objects through the in-memory chunk index
- Adds vector distance/similarity metadata to returned `Document` objects

### Reciprocal Rank Fusion (RRF) service

- File: `backend/src/retrieval/services/reciprocal_rank_fusion.py`
- Fuses keyword and semantic retrieval ranked candidate lists
  - Scores each candidate using `rrf_score = 1 / (c + rank)` 
    - `c` is a constant
    - `rank` = position of candidate inside respective candidate list
  - Deduplicates candidates by `Document.id`(`chunk_id`) and returns combined list of sorted by descending `rrf_score`
    - Sum the `rrf_score` of a candidate in both result lists if they appear in both semantic and keyword retrieval results
- Returns `Document` objects with source-rank metadata:
  - `keyword_retrieval_rank`
  - `semantic_retrieval_rank`

### `RerankerClient`

- File: `backend/src/retrieval/clients/reranker_client.py`
- Interfaces with the separate cross-encoder reranker app through specified API endpoint contracts
- Checks reranker health before reranking (GET /health)
- Posts rrf candidates to the reranker (POST /rerank) and validates performs response validation on reranked candidate set
- Adds `rerank_score` metadata and sorts candidates by descending score

### `ChatOrchestrator`

- File: `backend/src/chat/chat_orchestrator.py`
- Consumes the final ranked retrieval results after `/chat` calls `RetrievalOrchestrator.search`
- Uses `build_messages` to combine the user query, retrieved chunks, system prompt, and in-memory session chat history
- Streams Bedrock Converse response chunks back to `backend/src/main.py`, which wraps them as SSE events for the frontend
- Stores completed user/assistant turns in `SessionChatHistory` after successful streaming for subsequent query context enrichment

### Retrieval state and freshness helpers

- Files:
  - `backend/src/shared/services/chunk_index.py`
  - `backend/src/indexing/services/indexed_documents_loader.py`
  - `backend/src/indexing/services/latest_chunk_index_loader.py`
  - `backend/src/shared/services/latest_bm25_pointer_loader.py`
- Behaviour:
  - `InMemoryChunkIndex` stores `chunk_id -> Document` and `doc_id -> chunk_id set` mappings for query-time retrieval
  - `load_indexed_documents` bootstraps retrieval state from indexed manifest rows and chunk JSONL artifacts
  - `load_chunk_index_from_latest_snapshot` loads the latest BM25 snapshot from S3 into an in-memory chunk index
  - `load_latest_pointer` reads the S3 BM25 pointer used by the background poller

### Backing stores used by retrieval

- Files:
  - `backend/src/indexing/services/manifest_repository.py`
  - `backend/src/shared/services/s3_gp_chunk_store.py`
  - `backend/src/shared/services/s3_vector_store.py`
  - `backend/src/shared/services/domain_lexicon_store.py`
- Behaviour:
  - `ManifestRepository` provides indexed document IDs and document status metadata
  - `S3GPChunkStore` reads chunk JSONL artifacts from the general-purpose S3 bucket
  - `S3VectorStore` queries S3 Vectors for semantic nearest-neighbor search
  - `DomainLexiconReader` reads DynamoDB-backed domain lexicon candidates for spell correction

<br/>

## Cross-Encoder Reranker App

- File: `backend/src/ce_rerank/main.py`
- Runs as a separate FastAPI app from the main backend
- Dual runtime compatibility:
  - Standard uvicorn runtime (isolated):
    ```bash
    # run from repo root
    cd backend/src/ce_rerank
    python -m uvicorn main:app --reload --port 8080
    ```
  - Containerized runtime through docker through Docker Compose or Docker run (use either):
    ```bash
    # 1) Multi Container orchestration through Docker Compose
    docker compose -f <absolute-path-to-compose.yaml> up --build  

    # 2) Single Container isolated runtime (Docker run)
    # Build reranker app container image
    docker build -f <absolute-path-to-Dockerfile.reranker> -t backend-reranker-app-dev backend 
    # Take built container image and spin up active runtime instance
    docker run --rm -p 8080:8080 --name backend-reranker backend-reranker-app-dev 
    ```
- Default model: `Alibaba-NLP/gte-reranker-modernbert-base`
- Endpoint contracts:
  - `GET /health`
    - health/status check endpoint
    - returns `{"ok": true}`
  - `POST /rerank`
    - accepts a JSON list of `[query, candidate_text]` pairs
    - returns `{"ok": true, "scores_list": [...]}`

<br/>

## Source-of-Truth Files

- `backend/src/main.py`
- `backend/src/chat/chat_orchestrator.py`
- `backend/src/chat/services/message_builder_service.py`
- `backend/src/chat/services/session_chat_history.py`
- `backend/src/retrieval/config.py`
- `backend/src/retrieval/retrieval_orchestrator.py`
- `backend/src/retrieval/retrieval_types.py`
- `backend/src/retrieval/clients/reranker_client.py`
- `backend/src/retrieval/services/query_basic_normalizer.py`
- `backend/src/retrieval/services/keyword_retriever.py`
- `backend/src/retrieval/services/semantic_retriever.py`
- `backend/src/retrieval/services/reciprocal_rank_fusion.py`
- `backend/src/retrieval/services/spell_correction/spell_correction_query_preprocessor.py`
- `backend/src/retrieval/services/spell_correction/spell_corrector.py`
- `backend/src/retrieval/data/base_english_lexicon.json`
- `backend/src/indexing/services/indexed_documents_loader.py`
- `backend/src/indexing/services/latest_chunk_index_loader.py`
- `backend/src/indexing/services/manifest_repository.py`
- `backend/src/shared/services/chunk_index.py`
- `backend/src/shared/services/latest_bm25_pointer_loader.py`
- `backend/src/shared/services/s3_gp_chunk_store.py`
- `backend/src/shared/services/s3_vector_store.py`
- `backend/src/shared/services/domain_lexicon_store.py`
- `backend/src/ce_rerank/main.py`
