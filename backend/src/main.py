# backend/src/main.py
import json
import logging
import re
from contextlib import asynccontextmanager
from typing import List, Literal, Optional

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from langchain_core.documents import Document
from .indexing.services.manifest_repository import ManifestRepository
from .indexing.services.s3_gp_raw_document_store import S3GPRawDocumentStore
from .retrieval.retrieval_orchestrator import RetrievalOrchestrator
from .chat.chat_orchestrator import ChatOrchestrator

from .indexing.config import settings as indexing_settings
from .retrieval.config import settings as retrieval_settings
from .chat.config import settings as chat_settings
from .shared.config import settings as shared_settings

app = FastAPI()
logger = logging.getLogger(__name__)
raw_doc_store = S3GPRawDocumentStore(
    bucket=shared_settings.S3_GP_BUCKET_NAME,
    raw_prefix=shared_settings.S3_GP_RAW_PREFIX,
)
manifest_repository = ManifestRepository(table_name=indexing_settings.DYNAMODB_MANIFEST_TABLE_NAME)
retrieval_orchestrator = RetrievalOrchestrator(
    manifest_table_name=indexing_settings.DYNAMODB_MANIFEST_TABLE_NAME,
    corpus_change_table_name=shared_settings.DYNAMODB_CORPUS_CHANGE_TABLE_NAME,
    s3_gp_bucket_name=shared_settings.S3_GP_BUCKET_NAME,
    chunks_prefix=shared_settings.S3_GP_CHUNK_PREFIX,
    s3_vector_bucket_name=shared_settings.S3_VECTOR_BUCKET_NAME,
    s3_vector_index_name=shared_settings.S3_VECTOR_INDEX_NAME,
    embedding_model_id=shared_settings.EMBEDDING_MODEL_ID,
    min_cosine_threshold=retrieval_settings.MIN_COSINE_THRESHOLD,
    bm25_pointer_key=shared_settings.BM25_POINTER_KEY,
    bm25_snapshot_key=shared_settings.BM25_SNAPSHOT_KEY,
    bm25_poll_interval_seconds=retrieval_settings.BM25_POLL_INTERVAL_SECONDS,
    enable_spell_correction=retrieval_settings.ENABLE_SPELL_CORRECTION,
    collection_term_stats_table_name=shared_settings.DYNAMODB_COLLECTION_TERM_STATS_TABLE_NAME,
    base_english_lexicon_path=retrieval_settings.BASE_ENGLISH_LEXICON_PATH,
    reranker_base_url=retrieval_settings.RERANKER_BASE_URL
)
chat_orchestrator = ChatOrchestrator(
    generator_model_id=chat_settings.GENERATOR_MODEL_ID,
    temperature=chat_settings.GENERATOR_MODEL_TEMPERATURE
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    retrieval_orchestrator.start_background_polling()
    try:
        yield
    finally:
        retrieval_orchestrator.stop_background_polling()

app = FastAPI(lifespan=lifespan)

# ==================================================================================
#             INDEXING ENTRY POINTS
# ==================================================================================

@app.post("/upload")
async def upload(files: list[UploadFile] = File(...)):
    """Upload one or more raw source documents into S3."""
    if not files:
        raise HTTPException(status_code=400, detail="No files were uploaded")

    try:
        result = await raw_doc_store.upload_docs_async(files)
        return {
            "ok": True,
            "files": result
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Upload failed")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@app.get("/documents")
def list():
    """Return raw document list for Knowledge Base display, including per-document indexing status."""
    try:
        docs_data_list = raw_doc_store.list_raw_docs()
        if manifest_repository and docs_data_list:
            doc_ids = [doc["docId"] for doc in docs_data_list if "docId" in doc]
            status_by_doc_id = manifest_repository.fetch_status_by_doc_ids(doc_ids)
            for doc in docs_data_list:
                doc_id = doc.get("docId")
                doc["status"] = status_by_doc_id.get(doc_id, "uploaded")
        else:
            for doc in docs_data_list:
                doc["status"] = "uploaded"
        return {
            "ok": True,
            "documents": docs_data_list
        }
    except Exception as e:
        logger.exception("List documents failed")
        raise HTTPException(status_code=500, detail=f"List documents failed: {str(e)}")

@app.delete("/documents/{doc_id:path}")
def delete(doc_id: str):
    """Delete an indexed raw document by exact S3 object key."""
    try:
        status = manifest_repository.fetch_status_by_doc_ids(doc_ids=[doc_id]).get(doc_id)
        if status != "indexed":
            raise HTTPException(status_code=409, detail=f"Document cannot be deleted while status is {status}")

        raw_doc_store.delete_raw_doc(doc_id)

        return {
            "ok": True,
            "docId": doc_id,
            "deleted": True
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Delete document failed for doc_id={doc_id}")
        raise HTTPException(status_code=500, detail=f"Failed to delete document {doc_id}: {str(e)}")


# ==================================================================================
#             RETRIEVAL CLASSES & ENTRY POINT
# ==================================================================================

class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str

class ChatRequest(BaseModel):
    message: str
    history: Optional[List[ChatMessage]] = None

def stream_events_sse(
    user_query: str, 
    retrieved_chunks_raw: List[Document],
    max_chunks_to_format: int = 10
):
    """
    SSE streaming helper function.

    Wraps text chunks yielded from chat orchestrator's stream_answer method
    as `sse_in_progress` events, and emits `sse_started`, `sse_completed` 
    or `sse_error` lifecycle events for frontend consumption.
    """
    try:
        yield "event: sse_started\ndata: {}\n\n"

        for text in chat_orchestrator.stream_answer(
            user_query=user_query,
            retrieved_chunks_raw=retrieved_chunks_raw,
            max_chunks_to_format=max_chunks_to_format
        ):
            in_progress_payload = json.dumps({"text": text})
            yield f"event: sse_in_progress\ndata: {in_progress_payload}\n\n"

        yield "event: sse_completed\ndata: {}\n\n"

    except Exception:
        logger.exception("Chat stream failed")
        error_payload = json.dumps({"error": "Chat stream failed"})
        yield f"event: sse_error\ndata: {error_payload}\n\n"

@app.post("/chat")
def chat(req: ChatRequest):
    """
    Handle a user's chat request by retrieving relevant chunks, passing those chunks as 
    context for LLM answer generation, and streaming the generated answer to client through SSE.
    """
    try:
        user_query = req.message.strip()

        if not user_query:
            raise HTTPException(status_code=400, detail="message is required")

        ranked_chunks, query_for_retrieval, correction_result = retrieval_orchestrator.search(
            raw_query=user_query,
            keyword_retrieval_candidates_size=30,
            semantic_retrieval_candidates_size=30,
            rrf_candidates_size=20
        )

        return StreamingResponse(
            content=stream_events_sse(
                user_query=query_for_retrieval,
                retrieved_chunks_raw=ranked_chunks,
                max_chunks_to_format=10
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Content-Type-Options": "nosniff",
            }
        )

    except HTTPException:
        raise
    except Exception:
        logger.exception("Chat request failed")
        raise HTTPException(status_code=500, detail="Chat request failed")


class ChatResponse(BaseModel):
    answer: str
