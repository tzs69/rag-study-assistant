# backend/src/main.py
import logging
import re

from pydantic import BaseModel
from fastapi import FastAPI, UploadFile, File
from fastapi import HTTPException
from typing import List, Literal, Optional
from .indexing.config import settings as indexing_settings
from .indexing.services.s3_gp_raw_document_store import S3GPRawDocumentStore
from .retrieval.config import settings as retrieval_settings
from .retrieval.retrieval_orchestrator import RetrievalOrchestrator
from langchain_core.documents import Document

app = FastAPI()
logger = logging.getLogger(__name__)
raw_doc_store = S3GPRawDocumentStore(
    bucket=indexing_settings.S3_GP_BUCKET_NAME,
    raw_prefix=indexing_settings.S3_GP_RAW_PREFIX,
)
retrieval_orchestrator = RetrievalOrchestrator(
    manifest_table_name=retrieval_settings.DYNAMODB_MANIFEST_TABLE_NAME,
    corpus_change_table_name=retrieval_settings.DYNAMODB_CORPUS_CHANGE_TABLE_NAME,
    s3_gp_bucket_name=retrieval_settings.S3_GP_BUCKET_NAME,
    chunks_prefix=retrieval_settings.S3_GP_CHUNK_PREFIX
)

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
    """Return the current raw document list for Knowledge Base display."""
    try:
        docs_data_list = raw_doc_store.list_raw_docs()
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
        retrieval_orchestrator.refresh_documents_if_stale()

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
