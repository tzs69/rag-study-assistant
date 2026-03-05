"""
S3 gp bucket raw document uploading service
 - S3DocUploaderService: into general purpose document store 
"""
from fastapi import UploadFile
from pathlib import PurePosixPath
from typing import Any, List
import uuid

from .s3_base_store import BaseStore


class S3GPRawDocumentStore(BaseStore):
    
    def __init__(self, bucket: str, raw_prefix: str = "raws"):
        
        super().__init__(bucket, vectors=False)
        normalized = (raw_prefix or "").strip().strip("/")
        if not normalized:
            raise ValueError("raw_prefix must be a non-empty path segment")
        self.raw_prefix = normalized

    async def upload_docs_async(self, files: List[UploadFile]):
        """
        Uploads raw document into GP bucket as is
        """
        uploaded = []
        for f in files:

            data = await f.read()
            filename = PurePosixPath(f.filename or "").name

            if not filename:
                raise ValueError("Upload file must have a filename")
            
            key = self._build_raw_key(filename)

            self.s3.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType=f.content_type or "application/octet-stream",
                Metadata={"original_filename": filename}
            )
            uploaded.append({"name": filename, "key": key, "size": len(data)})
        return uploaded

    def _build_raw_key(self, filename: str) -> str:
        """Builds the S3 key for the raw document, using the raw_prefix and a unique identifier to avoid collisions."""
        unique_id = str(uuid.uuid4())
        filepath = PurePosixPath(filename)
        stem = filepath.stem
        extension = filepath.suffix
        return f"{self.raw_prefix}/{stem}-{unique_id}{extension}"
