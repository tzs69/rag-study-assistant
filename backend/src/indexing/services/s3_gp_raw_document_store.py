"""
S3 general-purpose bucket store for raw document objects.

Responsibilities:
- Upload raw files under the configured prefix using UUID-suffixed keys
- Delete raw files by exact object key (`docId`)
- List raw files with frontend-oriented metadata shape
"""
from fastapi import UploadFile
from pathlib import PurePosixPath
from typing import Any, Dict, List
import uuid

from ...shared.services.s3_base_store import BaseStore


class S3GPRawDocumentStore(BaseStore):
    
    def __init__(self, bucket: str, raw_prefix: str = "raws"):
        """Create a raw document store bound to one bucket and raw prefix."""
        super().__init__(bucket, vectors=False)
        normalized = (raw_prefix or "").strip().strip("/")
        if not normalized:
            raise ValueError("raw_prefix must be a non-empty path segment")
        self.raw_prefix = normalized

    async def upload_docs_async(self, files: List[UploadFile]):
        """
        Uploads raw document into configured S3 GP bucket as is
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
        """Build a collision-resistant S3 key under `raw_prefix` for a filename."""
        unique_id = str(uuid.uuid4())
        filepath = PurePosixPath(filename)
        stem = filepath.stem
        extension = filepath.suffix
        return f"{self.raw_prefix}/{stem}-{unique_id}{extension}"


    def delete_raw_doc(self, doc_id: str):
        """
        Delete a raw document by its exact S3 object key (doc_id).
        """
        if not doc_id or not str(doc_id).strip():
            raise ValueError("doc_id is required")

        self.s3.client.delete_object(
            Bucket = self.bucket,
            Key = doc_id
        )


    def list_raw_docs(self) -> List[Dict[str, Any]]:
        """
        Within configured S3 GP bucket,
        list all documents under the configured prefix.
        """
        paginator = self.s3.client.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=self.bucket, Prefix=self.raw_prefix)

        docs_data_list: List[Dict[str, str]] = []

        for page in pages:
            for obj in page.get("Contents", []):
                key = obj["Key"]
                upload_date = obj["LastModified"]

                head = self.s3.client.head_object(Bucket=self.bucket, Key=key)
                original_filename = head.get("Metadata", {}).get("original_filename")

                docs_data_list.append(
                    {
                        "docId": key,
                        "fileName": original_filename,
                        "uploadedAt": upload_date.strftime("%Y-%m-%d")
                    }
                )

        return docs_data_list
