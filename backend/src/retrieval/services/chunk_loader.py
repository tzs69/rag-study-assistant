from __future__ import annotations
from typing import Dict, Set, Tuple
from langchain_core.documents import Document

from ...shared.services.s3_gp_chunk_store import S3GPChunkStore
from ...indexing.services.manifest_repository import ManifestRepository


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


def load_indexed_documents(
    *,
    manifest_repository: ManifestRepository,
    s3_chunk_store: S3GPChunkStore,
) -> Tuple[Dict[str, Document], Dict[str, Set[str]]]:
    """
    Load all currently indexed document chunks from S3 JSONL artifacts and convert
    them into in-memory lookup structures.

    To be executed once in initial in-memory bootstrap when no change deltas yet.

    Behavior:
    - Queries manifest table for doc_ids with status == "indexed".
    - Loads each indexed document's chunks and converts them to Document entries.
    - Populates doc_chunk_index with set of all associated chunk_ids for each indexed document for doc/chunk tracking.

    Returns:
        (documents_by_chunk_id, doc_chunk_index):
            - documents_by_chunk_id: Dict[str, Document] = in-memory Documents keyed by chunk_id
            - doc_chunk_index:  Dict[str, Set[str]] = doc_id -> set(chunk_id) index for fast doc-level deletes
    """
    documents_by_chunk_id: Dict[str, Document] = {}
    doc_chunk_index: Dict[str, Set[str]] = {}

    # Query manifest table for all doc_ids with status == "indexed"
    indexed_docids = manifest_repository.fetch_indexed_docids()

    # Process each doc_id and load its associated chunks into Document objects
    for doc_id in indexed_docids:
        chunks_by_id = load_documents_for_doc_id(
            doc_id=doc_id,
            s3_chunk_store=s3_chunk_store,
        )
        # Build doc_id -> chunk_id index for efficient doc-level deletes
        doc_chunk_index[doc_id] = set(chunks_by_id.keys())

        # Merge per-doc chunk documents into global chunk_id -> Document map
        documents_by_chunk_id.update(chunks_by_id)

    return documents_by_chunk_id, doc_chunk_index
