# backend/src/main.py
from fastapi import FastAPI, UploadFile, File
from fastapi import HTTPException
from src.aws.config import settings
from src.aws.services.s3_uploader_service import S3DocUploaderService

app = FastAPI()
uploader = S3DocUploaderService(settings.S3_BUCKET_NAME)

@app.post("/upload")
async def upload(files: list[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="No files were uploaded")

    try:
        result = await uploader.upload_docs_async(files)
        return {"ok": True, "files": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")
