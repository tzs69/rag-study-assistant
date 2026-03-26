from __future__ import annotations

from typing import Dict, Set
from langchain_core.documents import Document


class InMemoryChunkIndex:
    """
    In-memory store for retrieval documents and doc(langchain document object)->chunk membership index.

    example doc_chunk_index:
    {
        "raws/doc_1.pdf": {"doc_1_chunk_#0001", "doc_1_chunk_#0002", ...},
        "raws/doc_2.pdf": {"doc_2_chunk_#0001", "doc_2_chunk_#0002", ...},
        ...
    }

    example documents_by_chunk_id:
    {
        "doc_1_chunk_#0001": langchain.Document(...),
        "doc_1_chunk_#0002": langchain.Document(...),
        ...
        "doc_2_chunk_#0001": langchain.Document(...),
        "doc_2_chunk_#0002": langchain.Document(...),
        ...
    }
    """
    def __init__(
        self,
        documents_by_chunk_id: Dict[str, Document] | None = None,
        doc_chunk_index: Dict[str, Set[str]] | None = None,
    ) -> None:
        self.documents_by_chunk_id: Dict[str, Document] = documents_by_chunk_id or {}
        self.doc_chunk_index: Dict[str, Set[str]] = doc_chunk_index or {}


    def add_doc_chunks(self, doc_id: str, doc_chunks: Dict[str, Document]) -> None:
        """
        For one document, add all of its related chunk docs to documents_by_chunk_id,
        and add doc_id: set(chunk_ids) to doc_chunk_index for fast lookup

        Takes in the output of chunk_loader.py's load_documents_for_doc_id() as doc_chunks
        """
        chunk_ids = self.doc_chunk_index.setdefault(doc_id, set())
        for chunk_id, doc_obj in doc_chunks.items():
            chunk_ids.add(chunk_id)
            self.documents_by_chunk_id[chunk_id] = doc_obj


    def remove_doc(self, doc_id: str) -> None:
        """
        Remove one document and all of its tracked chunk docs from the in-memory index.
        This keeps both internal maps consistent after a delete event.

        Behavior:
        - Looks up doc_id in doc_chunk_index to get set of all associated chunk_ids.
        - Removes each associated chunk_id: Document from documents_by_chunk_id.
        - Removes the doc_id entry from doc_chunk_index once all associated chunks cleaned up.
        """
        chunk_ids = self.doc_chunk_index.get(doc_id)
        if not chunk_ids:
            return
        for chunk_id in chunk_ids:
            self.documents_by_chunk_id.pop(chunk_id, None)
        self.doc_chunk_index.pop(doc_id, None)
