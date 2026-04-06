from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Dict, List

from .s3_base_store import BaseStore
from ..utils.build_chunk_key import build_chunks_jsonl_key

@dataclass(frozen=True)
class Chunk:
    doc_id: str
    chunk_id: str
    text: str


class S3GPChunkStore(BaseStore):

    def __init__(self, bucket: str, chunks_prefix: str = "chunks"):
        super().__init__(bucket, vectors=False)
        normalized = (chunks_prefix or "").strip().strip("/")
        if not normalized:
            raise ValueError("chunks_prefix must be a non-empty path segment")
        self.chunks_prefix = normalized

    def upload_chunks_jsonl(self, doc_id: str, chunks: List[Chunk],) -> dict[str, Any]:
        """
        Uploads a document's chunks as a JSONL object to the configured S3 bucket
        """
        if not doc_id:
            raise ValueError("doc_id is required")
        if not chunks:
            raise ValueError("chunks must be non-empty")

        key = build_chunks_jsonl_key(self.chunks_prefix, doc_id)
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
    

    @staticmethod
    def _to_jsonl_bytes(chunks: List[Chunk]) -> bytes:
        """
        Serialize a list of Chunk objects into UTF-8 encoded JSONL bytes
        """
        lines = []
        for chunk in chunks:
            if isinstance(chunk, Chunk):
                payload = asdict(chunk)
            else:
                raise TypeError("Each chunk must be a Chunk object")
            lines.append(json.dumps(payload, ensure_ascii=False))
        return ("\n".join(lines) + "\n").encode("utf-8")


    def delete_chunks_for_docid(self, doc_id:str):
        """
        Takes a raw doc_id, converts it into chunk key format ('chunks/{doc_id}_chunks.jsonl') 
        and deletes the associated .jsonl object referenced by the built chunk key
        """
        doc_id_chunk_jsonl_key = build_chunks_jsonl_key(self.chunks_prefix ,doc_id)
        self.s3.client.delete_object(
            Bucket=self.bucket,
            Key=doc_id_chunk_jsonl_key,
        )
        return {
            "doc_id": doc_id,
            "bucket": self.bucket,
            "key": doc_id_chunk_jsonl_key
        }
    

    def load_chunks_for_doc_id(self, doc_id: str) -> Dict[str, str]:
        """
        Load a single doc_id's chunk JSONL artifact from S3 and map chunk_id -> Document.

        Behaviour:
        - Takes in doc_id in the form of raw/{doc_id body}.{file ext.} (i.e. raws/lolol69.md)
        - converts doc_id into chunk key (chunks/{doc_id body}_chunks.jsonl) and fetches the object from S3 using the built key
        - 
        """
        # Build chunk key consistent to indexing and fetch chunk.jsonl file
        chunk_key = build_chunks_jsonl_key(self.chunks_prefix, doc_id)
        response = self.s3.client.get_object(
            Bucket=self.bucket,
            Key=chunk_key,
        )

        out: Dict[str, str] = {}

        # Iterate through all chunk json objects within .jsonl file and load k:v = chunk_id:text into out dictionary
        for line in response["Body"].iter_lines():
            if not line:
                continue
            chunk_data = json.loads(line.decode("utf-8")) # { "doc_id":..., "chunk_id":..., "text": ... }
            chunk_id = chunk_data["chunk_id"] 
            text = chunk_data["text"]
            out[chunk_id] = text
        return out