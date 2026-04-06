from typing import Dict, Set, Tuple
from langchain_core.documents import Document

from ...shared.services.chunk_loader import load_documents_for_doc_id
from ...shared.services.s3_gp_chunk_store import S3GPChunkStore
from .manifest_repository import ManifestRepository


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
