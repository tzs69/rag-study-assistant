from __future__ import annotations
from typing import Callable, Dict
from langchain_core.documents import Document
from .chunk_index import InMemoryChunkIndex


def apply_changes(
    *,
    latest_changes: Dict[str, str],
    chunk_index: InMemoryChunkIndex,
    chunk_loader: Callable[[str], Dict[str, Document]],
) -> None:
    """
    Takes in a dict of latest_changes, reads each doc_id : op pair and
    applies corpus delta operations to in-memory retrieval state.

    Rules:
    - delete: remove doc and all tracked chunks.
    - upsert: replace in-memory chunks for that doc with freshly loaded chunks.

    example latest_changes:
    {
        "raws/doc_1.pdf": "upsert",
        "raws/doc_2.pdf": "delete",
        ...
    }
    """
    for doc_id, op in latest_changes.items():
        
        # Apply deletes
        if op == "delete":
            chunk_index.remove_doc(doc_id)
            continue
        # Apply upserts
        elif op == "upsert":
            chunks_by_id = chunk_loader(doc_id)
            chunk_index.remove_doc(doc_id)
            if chunks_by_id:
                chunk_index.add_doc_chunks(doc_id, chunks_by_id)
        # Unknown op detected -> skip
        else:
            continue