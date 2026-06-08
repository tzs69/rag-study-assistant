# Retrieval Pipeline - Backend Notes

This document describes the current retrieval architecture under `backend/src/retrieval`, including hybrid keyword/semantic candidate retrieval, Reciprocal Rank Fusion (RRF), and best-effort cross-encoder reranking.

## Scope

- Folder scope: `backend/src/retrieval`
- App purpose: Retrieve relevant indexed chunks for `/chat` requests before answer generation.
- Current status:
  - Keyword retrieval is implemented with an in-memory LangChain BM25 retriever.
  - Semantic retrieval is implemented against S3 Vectors using Bedrock query embeddings.
  - Keyword and semantic retrieval branches run in parallel.
  - Retrieval branch failures are isolated so one failed branch does not fail the whole request.
  - RRF deduplicates keyword/semantic retrieval results into a single ranked `Document` result list.
  - Cross-encoder reranking is implemented as a best-effort post-RRF step through a separate FastAPI app.
    - Separation due to Cross-Encoder's heavy import dependencies at application start-up time

## Current Runtime Flow

1. `/chat` receives a user query and passes it to `RetrievalOrchestrator.search`.
2. The orchestrator normalizes the query.
3. Optional spell correction rewrites the retrieval query when enabled.
4. The orchestrator snapshots the current BM25 retriever and chunk index under lock.
5. Keyword retrieval (BM25) and semantic retrieval (vector cosine similarity) run concurrently.
6. Each branch returns a ranked `List[Document]`; failed branches log and fall back to an empty list.
7. `rrf_combine` deduplicates by `chunk_id`, computes RRF scores, and returns the top fused candidates.
8. If the reranker service is healthy, the orchestrator sends RRF candidates to the cross-encoder reranker.
9. Reranking failures are logged and the orchestrator falls back to the RRF-ranked candidates.
10. The final ranked `Document` list is returned to `/chat`.

## Retrieval Components

### `RetrievalOrchestrator`

- File: `backend/src/retrieval/retrieval_orchestrator.py`
- Owns the retrieval flow used by `/chat`.
- Coordinates query normalization, optional spell correction, keyword retrieval, semantic retrieval, RRF, and reranking.
- Starts a background BM25 pointer poller on FastAPI lifespan startup.

### `KeywordRetrievalService`

- File: `backend/src/retrieval/services/keyword_retriever.py`
- Uses LangChain's BM25 retriever over the in-memory chunk corpus.
- Returns `List[Document]` in ranked order.
- Uses a lock around BM25 search because the underlying retriever `k` value is mutated per search.

### `SemanticRetrievalService`

- File: `backend/src/retrieval/services/semantic_retriever.py`
- Embeds the query with the same Bedrock embedding model used during indexing.
- Queries the S3 Vector index for nearest chunk vectors.
- Maps returned vector keys back to chunk `Document` objects through the in-memory chunk index.
- Adds vector distance/similarity metadata to returned `Document` objects.

### `rrf_combine`

- File: `backend/src/retrieval/services/reciprocal_rank_fusion.py`
- Fuses keyword and semantic retrieval ranked lists using `1 / (c + rank)`.
- Deduplicates candidates by `Document.id` / chunk id.
- Returns `Document` objects with source-rank metadata:
  - `keyword_retrieval_rank`
  - `semantic_retrieval_rank`

### `RerankerClient`

- File: `backend/src/retrieval/clients/reranker_client.py`
- Calls the separate cross-encoder reranker app.
- Checks reranker health before reranking.
- Validates the reranker response has one score per input `Document`.
- Adds `rerank_score` metadata and sorts candidates by descending score.

## Cross-Encoder Reranker App

- File: `backend/src/ce_rerank/main.py`
- Runs as a separate FastAPI app from the main backend.
- Default model: `Alibaba-NLP/gte-reranker-modernbert-base`.
- Endpoint contract:
  - `GET /health` returns `{"ok": true}`.
  - `POST /rerank` accepts a JSON list of `[query, candidate_text]` pairs.
  - `POST /rerank` returns `{"ok": true, "scores_list": [...]}`.

Example local run command from repo root:

```bash
uvicorn backend.src.ce_rerank.main:app --reload --port 8080
```

First startup may be slow due to downloading of the model from Hugging Face.

## Configuration

Retrieval config is loaded from `backend/src/retrieval/.env.local` through `backend/src/retrieval/config.py`.

Relevant settings:

- `BM25_POLL_INTERVAL_SECONDS`: interval for polling the latest BM25 pointer.
- `ENABLE_SPELL_CORRECTION`: enables retrieval-time spell correction.
- `MIN_COSINE_THRESHOLD`: minimum semantic similarity threshold for vector candidates.
- `BASE_ENGLISH_LEXICON_PATH`: base lexicon path for spell correction.
- `RERANKER_BASE_URL`: base URL for the cross-encoder reranker app. Defaults to `http://localhost:8080/`.

## Source-of-Truth Files

- `backend/src/main.py`
- `backend/src/retrieval/config.py`
- `backend/src/retrieval/retrieval_orchestrator.py`
- `backend/src/retrieval/clients/reranker_client.py`
- `backend/src/retrieval/services/keyword_retriever.py`
- `backend/src/retrieval/services/semantic_retriever.py`
- `backend/src/retrieval/services/reciprocal_rank_fusion.py`
- `backend/src/ce_rerank/main.py`
