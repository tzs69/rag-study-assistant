from __future__ import annotations
from typing import Dict
from langchain_core.documents import Document

from .s3_gp_chunk_store import S3GPChunkStore


def load_documents_for_doc_id(doc_id: str, s3_chunk_store: S3GPChunkStore) -> Dict[str, Document]:
    """
    Load one document's chunk artifact from S3 and convert it into retrieval Documents.

    Behavior:
    - Calls s3_chunk_store.load_chunks_for_doc_id(doc_id) to fetch chunk_ids and their respective texts,
      and converts each chunk_id, chunk text pair into a LangChain Document with:
      - id = chunk_id
      - page_content = chunk text
    """
    out: Dict[str, Document] = {}

    chunks = s3_chunk_store.load_chunks_for_doc_id(doc_id=doc_id)
    for chunk_id, text in chunks.items():
        out[chunk_id] = Document(
            id=chunk_id,
            page_content=text
        )
    return out
