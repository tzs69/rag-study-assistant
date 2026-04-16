# backend/src/main.py
import logging
import re
from contextlib import asynccontextmanager
from fastapi import FastAPI

from pydantic import BaseModel
from fastapi import FastAPI, UploadFile, File
from fastapi import HTTPException
from typing import List, Literal, Optional
from .indexing.services.manifest_repository import ManifestRepository
from .indexing.services.s3_gp_raw_document_store import S3GPRawDocumentStore
from .retrieval.retrieval_orchestrator import RetrievalOrchestrator
from langchain_core.documents import Document

from .indexing.config import settings as indexing_settings
from .retrieval.config import settings as retrieval_settings
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
    bm25_pointer_key=shared_settings.BM25_POINTER_KEY,
    bm25_snapshot_key=shared_settings.BM25_SNAPSHOT_KEY,
    bm25_poll_interval_seconds=retrieval_settings.BM25_POLL_INTERVAL_SECONDS,
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
    """Delete a raw document by exact S3 object key (`docId`)."""
    try:
        raw_doc_store.delete_raw_doc(doc_id)
        return {
            "ok": True, 
            "docId": doc_id, 
            "deleted": True
        }
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

class ChatResponse(BaseModel):
    answer: str

def _extract_snippet(text: str, query: str, max_chars: int = 280) -> str:
    query_terms = [t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) > 1]
    if not text:
        return ""

    lowered = text.lower()
    best_index = -1
    for term in query_terms:
        idx = lowered.find(term)
        if idx != -1 and (best_index == -1 or idx < best_index):
            best_index = idx

    if best_index == -1:
        snippet = text[:max_chars].strip()
    else:
        start = max(0, best_index - max_chars // 3)
        end = min(len(text), start + max_chars)
        snippet = text[start:end].strip()

    if len(snippet) < len(text):
        return f"{snippet}..."
    return snippet

@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    try:
        user_query = req.message.strip()
        # message_history = req.history.strip()
        if not user_query:
            raise HTTPException(status_code=400, detail="message is required")

        # placeholder for now
        # answer = f"{user_query} testing_123"
        top_k_document: List[Document] = retrieval_orchestrator.bm25_retriever.search(user_query, top_k=5)
        if not top_k_document:
            return ChatResponse(answer="I couldn't find relevant content for that query in the indexed documents.")

        answer_lines: List[str] = []
        for rank, document in enumerate(top_k_document, start=1):
            snippet = _extract_snippet(document.page_content, user_query)
            answer_lines.append(f"{rank}) {snippet}")

        return ChatResponse(answer="\n".join(answer_lines))

    except HTTPException:
        raise
    except Exception:
        logger.exception("Chat request failed")
        raise HTTPException(status_code=500, detail="Chat request failed")
