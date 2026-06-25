# RAG Study Assistant

RAG Study Assistant is a full-stack, cloud-backed study workspace for turning uploaded source documents into an indexed knowledge base and chatting against it with retrieval-augmented answers. The app combines a Next.js frontend, FastAPI backend APIs, AWS event-driven ingestion/deletion workers, S3/S3 Vectors/DynamoDB storage, hybrid BM25 + semantic retrieval, cross-encoder reranking, and Bedrock-powered streaming answer generation.

This repository contains:
- a Next.js frontend (`frontend/src/`)
- a FastAPI backend (`backend/src/`)
- Dockerfiles and Docker Compose config for the local/dev application services
- AWS SAM infrastructure for event-driven indexing/deletion (`infra/`)

<br/>

## Product Scope

- Maintain a source-document knowledge base for supported filetypes (`.pdf`, `.docx`, `.txt`, `.md`)
- Upload source documents and asynchronously process them into searchable chunks, embeddings, vector records, and retrieval metadata
- Display uploaded documents with indexing lifecycle status so users can tell whether a document is ready for chat
- Delete indexed documents and trigger backend cleanup of raw documents, vectors, manifests, and retrieval metadata
- Pose natural language queries against the indexed knowledge base through a chat interface
- Generate streamed RAG answers grounded in retrieved document chunks, using hybrid keyword/semantic retrieval, fusion, reranking, and LLM generation

<br/>

## Features
- Frontend Knowledge Base flow:
  - list documents with indexing status
  - upload documents
  - delete indexed documents
- Frontend Chat page and Next API proxy routes under `frontend/src/app/api/**` for backend communication
- Backend upload/list/delete/chat endpoints in `backend/src/main.py`
- Backend document listing with per-document indexing status
- Backend delete guard that blocks deletion until a document is indexed
- S3 raw document storage with original filename metadata
- Event-driven indexing/deletion architecture and worker code under `backend/src/indexing`
- Chunking, embedding, chunk artifact storage, vector upsert/delete, and manifest lifecycle handling
- Domain lexicon tracking for retrieval-time prefix-based spell correction support
- Corpus change tracking plus BM25 snapshot/pointer update pipeline
- Hybrid retrieval flow with keyword retrieval (BM25), semantic retrieval (S3 Vector cosine similarity), RRF fusion, and best-effort cross-encoder reranking
- Separate FastAPI cross-encoder reranker service under `backend/src/ce_rerank`
- Containerized local/dev runtime for the frontend, main backend API, and reranker service via `compose.yaml.dev` at project root
- Chat answer generation pipeline under `backend/src/chat`
- Bedrock Converse-based LLM answer generation over retrieved/reranked chunks
- Server-sent event (SSE) streaming from backend `/chat` through the Next API proxy to the frontend chat UI

<br/>

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
- SSE streaming

### Retrieval / Indexing
- LangChain ecosystem (`langchain-aws`, `langchain-experimental`, `langchain_community`)
- `rank_bm25` (keyword retrieval / BM25)
- Reciprocal Rank Fusion (hybrid keyword/semantic retrieval fusion)
- `sentence-transformers` CrossEncoder reranker service
- Bedrock Converse chat generation via `ChatBedrockConverse`
- `pypdf`, `python-docx` (document text extraction)

### Infrastructure / Cloud
- Docker + Docker Compose for local/dev service orchestration
- AWS SAM (CloudFormation)
- AWS Lambda
- Amazon S3 (raw docs + chunk artifacts)
- Amazon S3 Vectors
- Amazon SQS (+ DLQs)
- Amazon DynamoDB
- Amazon Bedrock

<br/>

## Runtime Boundaries

The application currently has two distinct runtime surfaces:

1. Containerized local/dev application services:
   - `frontend-main`: Next.js frontend, built from `frontend/Dockerfile.main.dev`, exposed on port `3000`.
   - `backend-main`: main FastAPI API, built from `backend/Dockerfile.main.dev`, exposed on port `8000`.
   - `backend-reranker`: separate FastAPI cross-encoder reranker service, built from `backend/Dockerfile.reranker.dev`, exposed on port `8080`.

2. SAM-managed AWS indexing infrastructure:
   - S3 notifications publish raw document create/delete events to SQS.
   - SQS event source mappings invoke Lambda workers for ingestion, deletion, and BM25 snapshot updates.
   - Lambda workers use S3, DynamoDB, Bedrock, and S3 Vectors for the indexing lifecycle.

The indexing workers are not containerized services in the current repo. They are Python Lambda handlers under `backend/src/indexing/workers` and are deployed by the SAM template in `infra/template.yaml`.

<br/>

## High-Level Flow

1. User uploads documents from the frontend.
2. Frontend calls Next API route (`/api/upload`) which proxies to backend (`/upload`).
3. Backend stores raw docs in S3.
4. S3 events trigger ingestion/deletion workers (via SQS) for downstream indexing lifecycle.
5. Frontend fetches document list via `/api/documents`.
6. Chat requests call backend `/chat`, which runs keyword retrieval (BM25) and semantic retrieval in parallel.
7. Retrieval candidates are deduplicated/fused with RRF, then optionally reranked by the cross-encoder service.
8. The chat orchestrator builds prompt messages from chat history plus retrieved context and streams generated answer chunks through SSE.

## Full Pipeline Demo (Indexing -> Retrieval -> Answer Generation)

https://github.com/user-attachments/assets/3c912496-ad49-462a-ac7d-754ff7fb6ed3




<br/>


## Local Development

### Requirements
- Node.js + npm
- Python 3.11+ (recommended for backend)
- Docker + Docker Compose for the containerized dev stack
- AWS credentials/config for real S3-backed flows

### Run with Docker Compose

Create `frontend/.env` and `backend/.env` from the example files:

```powershell
Copy-Item frontend/.env.example frontend/.env
Copy-Item backend/.env.example backend/.env
```

Then start the local/dev service stack:

```bash
docker compose -f <absolute-path-to-compose.yaml> up --build
```

The Compose stack starts:

- Frontend: `http://localhost:3000`
- Main backend API: `http://localhost:8000`
- Reranker service: `http://localhost:8080`

In the Compose runtime, the frontend should use:

```env
BACKEND_URL=http://backend-main:8000
```

The main backend should use:

```env
RERANKER_BASE_URL=http://backend-reranker:8080
```

The backend container mounts the local AWS config directory so AWS-backed S3, DynamoDB, Bedrock, SQS, and S3 Vectors flows can use local credentials during development.

### Run without containers

#### Run frontend

```bash
# run from repo root
cd frontend
npm install
npm run dev
```

Frontend runs on `http://localhost:3000`.

#### Run main backend API service

```bash
# from repo root
cd backend
python -m uvicorn main:app --reload --port 8000 
```

Backend runs on `http://127.0.0.1:8000`.

Set `frontend/.env` so proxy routes can reach backend:

```env
BACKEND_URL=http://127.0.0.1:8000
```

#### Run reranker service
The retrieval orchestrator can call a separate cross-encoder reranker app.

```bash
# run from repo root
cd backend/src/ce_rerank
python -m uvicorn main:app --reload --port 8080
```

The reranker service exposes:
- `GET /health`
- `POST /rerank`

Startup of reranker service may be slow due to downloading/loading of the configured Hugging Face model into memory.

<br/>

## API Proxy Routes (Frontend)

- `POST /api/upload` -> backend `/upload`
- `GET /api/documents` -> backend `/documents`
- `DELETE /api/documents/:id` -> backend `/documents/{doc_id}`
- `POST /api/chat` -> backend `/chat`

<br/>

## Reference Docs

For deeper implementation details, see:
- Backend indexing lifecycle notes: [`backend/src/indexing/README.md`](backend/src/indexing/README.md)
- Backend retrieval lifecycle notes: [`backend/src/retrieval/README.md`](backend/src/retrieval/README.md)
- Infrastructure/SAM details: [`infra/README.md`](infra/README.md)

This root README is intentionally product-level and cross-cutting; nested READMEs hold subsystem specifics.
