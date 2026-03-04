# backend/src/main.py
from fastapi import FastAPI, UploadFile, File
from fastapi import HTTPException
from .indexing.config import settings
from .indexing.services.uploaders.s3_gp_raw_uploader_service import S3GPRawUploaderService

app = FastAPI()
rawdoc_uploader = S3GPRawUploaderService(
    settings.S3_GP_BUCKET_NAME,
    raw_prefix=settings.S3_GP_RAW_PREFIX,
)

@app.post("/upload")
async def upload(files: list[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="No files were uploaded")

    try:
        result = await rawdoc_uploader.upload_docs_async(files)
        return {"ok": True, "files": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")
