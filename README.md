# RAG Study Assistant

A study assistant app that lets users upload source documents, index them for retrieval, and chat against the indexed knowledge base.

This repository contains:
- a Next.js frontend (`src/`)
- a FastAPI backend (`backend/src/`)
- AWS SAM infrastructure for event-driven indexing/deletion (`infra/`)

## Product Scope

- Upload documents (`.pdf`, `.docx`, `.txt`, `.md`)
- View uploaded documents in a Knowledge Base page
- Delete uploaded documents
- Trigger backend ingestion pipeline to chunk, embed, and index content
- Chat UI for question answering over indexed sources

## Current Status

Implemented:
- Frontend Knowledge Base flow:
  - list documents
  - upload documents
  - delete documents
- Next API proxy routes under `src/app/api/**` for backend communication
- Backend upload/list/delete/chat endpoints in `backend/src/main.py`
- S3 raw document storage with original filename metadata
- Event-driven indexing/deletion architecture and worker code under `backend/src/indexing`
- Hybrid retrieval flow with BM25 keyword search, S3 Vector semantic search, RRF fusion, and best-effort cross-encoder reranking

In progress / partial:
- Better UX around ingestion lifecycle states (for example: disable delete while ingesting)
- More consistent error surfacing and logging strategy across UI + API route layers

Planned next:
- Surface ingestion status on the Knowledge Base page
- Add document-level status transitions (`ingesting`, `indexed`, `failed`) to UI
- Harden API contracts and shared types between frontend/backend
- Improve observability and test coverage (route contracts + end-to-end flows)

## Tech Stack

### Frontend
- Next.js 16
- React 19
- TypeScript
- Material UI (MUI) + Emotion
- Tailwind CSS 4

### Backend API
- FastAPI
- Pydantic + pydantic-settings
- python-multipart
- httpx

### Retrieval / Indexing
- LangChain ecosystem (`langchain-aws`, `langchain-experimental`, `langchain_community`)
- `rank_bm25` (keyword retrieval)
- Reciprocal Rank Fusion (hybrid keyword/vector candidate fusion)
- `sentence-transformers` CrossEncoder reranker service
- `pypdf`, `python-docx` (document text extraction)

### Infrastructure / Cloud
- AWS SAM (CloudFormation)
- AWS Lambda
- Amazon S3 (raw docs + chunk artifacts)
- Amazon SQS (+ DLQs)
- Amazon DynamoDB
- Amazon Bedrock
- Amazon S3 Vectors

## High-Level Flow

1. User uploads documents from the frontend.
2. Frontend calls Next API route (`/api/upload`) which proxies to backend (`/upload`).
3. Backend stores raw docs in S3.
4. S3 events trigger ingestion/deletion workers (via SQS) for downstream indexing lifecycle.
5. Frontend fetches document list via `/api/documents`.
6. Chat requests call backend `/chat`, which runs BM25 and semantic retrieval in parallel.
7. Retrieval candidates are deduplicated/fused with RRF, then optionally reranked by the cross-encoder service.

## Indexing Demo

https://github.com/user-attachments/assets/ad8b1e81-bc23-4858-84c2-17be012acbbf


## Local Development

### Requirements
- Node.js + npm
- Python 3.11+ (recommended for backend)
- AWS credentials/config for real S3-backed flows

### Run frontend
From repo root:

```bash
npm install
npm run dev
```

Frontend runs on `http://localhost:3000`.

### Run backend
Example from repo root:

```bash
uvicorn backend.src.main:app --reload --port 8000
```

Backend runs on `http://127.0.0.1:8000`.

Set frontend env so proxy routes can reach backend:

```env
BACKEND_URL=http://127.0.0.1:8000
```

### Run reranker service
The retrieval orchestrator can call a separate cross-encoder reranker app. Example from repo root:

```bash
uvicorn backend.src.ce_rerank.main:app --reload --port 8080
```

The reranker service exposes:
- `GET /health`
- `POST /rerank`

First startup may download the configured Hugging Face model.

## API Proxy Routes (Frontend)

- `POST /api/upload` -> backend `/upload`
- `GET /api/documents` -> backend `/documents`
- `DELETE /api/documents/:id` -> backend `/documents/{doc_id}`
- `POST /api/chat` -> backend `/chat`

## Reference Docs

For deeper implementation details, see:
- Backend indexing lifecycle notes: [`backend/src/indexing/README.md`](backend/src/indexing/README.md)
- Backend retrieval lifecycle notes: [`backend/src/retrieval/README.md`](backend/src/retrieval/README.md)
- Infrastructure/SAM details: [`infra/README.md`](infra/README.md)

This root README is intentionally product-level and cross-cutting; nested READMEs hold subsystem specifics.
