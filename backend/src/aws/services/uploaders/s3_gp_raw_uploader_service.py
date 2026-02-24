"""
S3 gp bucket raw document uploading service
 - S3DocUploaderService: into general purpose document store 
"""

from fastapi import UploadFile
from pathlib import PurePosixPath
from typing import Any, List

from .s3_base_uploader import BaseUploader


class S3GPRawUploaderService(BaseUploader):
    """
    Uploads raw document into GP bucket as is
    """

    def __init__(self, bucket: str, raw_prefix: str = "raws"):
        
        super().__init__(bucket, vectors=False)
        normalized = (raw_prefix or "").strip().strip("/")
        if not normalized:
            raise ValueError("raw_prefix must be a non-empty path segment")
        self.raw_prefix = normalized

    async def upload_docs_async(self, files: List[UploadFile]):

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
            )
            uploaded.append({"name": filename, "key": key, "size": len(data)})
        return uploaded

    def _build_raw_key(self, filename: str) -> str:
        return f"{self.raw_prefix}/{filename}"
