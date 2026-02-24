from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import PurePosixPath
from typing import Any, List

from ..chunking_service import Chunk
from .s3_base_uploader import BaseUploader


class S3GPChunkUploaderService(BaseUploader):
    """Uploads one document's chunks as a JSONL object into the GP bucket."""

    def __init__(self, bucket: str, chunks_prefix: str = "chunks"):
        super().__init__(bucket, vectors=False)
        normalized = (chunks_prefix or "").strip().strip("/")
        if not normalized:
            raise ValueError("chunks_prefix must be a non-empty path segment")
        self.chunks_prefix = normalized

    def upload_chunks_jsonl(
        self,
        doc_id: str,
        chunks: List[Chunk],
    ) -> dict[str, Any]:
        if not doc_id:
            raise ValueError("doc_id is required")
        if not chunks:
            raise ValueError("chunks must be non-empty")

        key = self._build_chunks_key(doc_id)
        body = self._to_jsonl_bytes(chunks)

        self.s3.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=body,
            ContentType="application/x-ndjson",
        )

        return {
            "doc_id": doc_id,
            "bucket": self.bucket,
            "key": key,
            "chunk_count": len(chunks),
        }

    def _build_chunks_key(self, doc_id: str) -> str:
        doc_name = PurePosixPath(doc_id).stem
        if not doc_name:
            raise ValueError(f"Cannot derive document name from doc_id: {doc_id}")
        return f"{self.chunks_prefix}/{doc_name}_chunks.jsonl"

    @staticmethod
    def _to_jsonl_bytes(chunks: List[Chunk]) -> bytes:
        lines = []
        for chunk in chunks:
            if isinstance(chunk, Chunk):
                payload = asdict(chunk)
            else:
                raise TypeError("Each chunk must be a Chunk object")
            lines.append(json.dumps(payload, ensure_ascii=False))
        return ("\n".join(lines) + "\n").encode("utf-8")
