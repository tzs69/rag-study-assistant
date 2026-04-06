import json
from typing import Dict, Set

from botocore.exceptions import ClientError
from langchain_core.documents import Document
from ...shared.services.chunk_index import InMemoryChunkIndex
from ...shared.services.s3_base_store import BaseStore


def load_chunk_index_from_latest_snapshot(
    *,
    bucket: str,
    snapshot_key: str,
    base_store: BaseStore,
) -> InMemoryChunkIndex | None:
    """
    Load the latest persisted BM25 snapshot and convert it into in-memory
    chunk index artifacts.

    To be executed as a warm-start path before applying corpus deltas.

    Behavior:
    - Reads snapshot JSON from S3 using the provided `snapshot_key`.
    - Returns `None` when the snapshot object does not exist yet (`NoSuchKey`/`404`).
    - Validates snapshot shape and parses `documents` rows.
    - Reconstructs:
      - `documents_by_chunk_id`: chunk_id -> Document(page_content)
      - `doc_chunk_index`: doc_id -> set(chunk_id)
    - Skips malformed document rows instead of failing the whole load.

    Returns:
        InMemoryChunkIndex | None:
            - `InMemoryChunkIndex` when snapshot is readable and parseable
              (including empty corpus snapshots).
            - `None` when snapshot is missing or payload shape is invalid.
    """

    try:
        response = base_store.s3.client.get_object(Bucket=bucket, Key=snapshot_key)
        raw_payload = response["Body"].read()
        snapshot_payload = json.loads(raw_payload.decode("utf-8"))
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code")
        if code in ("NoSuchKey", "404"):
            return None
        raise

    if not isinstance(snapshot_payload, dict):
        return None

    snapshot_documents = snapshot_payload.get("documents")
    if not isinstance(snapshot_documents, list):
        return None

    documents_by_chunk_id: Dict[str, Document] = {}
    doc_chunk_index: Dict[str, Set[str]] = {}

    for row in snapshot_documents:
        if not isinstance(row, dict):
            continue
        chunk_id = row.get("id")
        page_content = row.get("page_content")
        metadata = row.get("metadata")
        if (
            not isinstance(chunk_id, str)
            or not chunk_id.strip()
            or not isinstance(page_content, str)
            or not isinstance(metadata, dict)
        ):
            continue

        doc_id = metadata.get("doc_id")
        if not isinstance(doc_id, str) or not doc_id.strip():
            continue

        cleaned_chunk_id = chunk_id.strip()
        cleaned_doc_id = doc_id.strip()
        documents_by_chunk_id[cleaned_chunk_id] = Document(id=cleaned_chunk_id, page_content=page_content)
        doc_chunk_index.setdefault(cleaned_doc_id, set()).add(cleaned_chunk_id)

    return InMemoryChunkIndex(
        documents_by_chunk_id=documents_by_chunk_id,
        doc_chunk_index=doc_chunk_index,
    )
