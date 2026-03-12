# backend/src/main.py
import logging

from fastapi import FastAPI, UploadFile, File
from fastapi import HTTPException
from .indexing.config import settings
from .indexing.services.s3_gp_raw_document_store import S3GPRawDocumentStore

app = FastAPI()
logger = logging.getLogger(__name__)
raw_doc_store = S3GPRawDocumentStore(
    settings.S3_GP_BUCKET_NAME,
    raw_prefix=settings.S3_GP_RAW_PREFIX,
)

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
        logger.exception("Delete document failed for doc_id=%s", doc_id)
        raise HTTPException(status_code=500, detail=f"Failed to delete document {doc_id}: {str(e)}")
