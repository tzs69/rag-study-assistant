import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Set

from botocore.exceptions import ClientError
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document

from ..config import settings
from ..services.manifest_repository import ManifestRepository
from ..services.indexed_documents_loader import load_indexed_documents
from ..services.latest_chunk_index_loader import load_chunk_index_from_latest_snapshot
from ...shared.services.chunk_loader import load_documents_for_doc_id
from ...shared.services.chunk_index import InMemoryChunkIndex
from ...shared.services.corpus_delta_applier import apply_changes
from ...shared.services.corpus_monitor import CorpusMonitor
from ...shared.services.s3_base_store import BaseStore
from ...shared.services.s3_gp_chunk_store import S3GPChunkStore
from ...shared.services.latest_bm25_pointer_loader import load_latest_pointer


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

POINTER_KEY = "bm25/pointer.json"
SNAPSHOT_KEY = "bm25/snapshot.json"

def bm25_update_handler(event, context):
    """
    Process BM25 update SQS events and publish the latest BM25 snapshot/pointer.

    Trigger/input:
    - Invoked by SQS with event["Records"] (list of SQS record objects).
    - Each record object must be JSON with:
      {
        "doc_id": "<non-empty str>",
        "op": "upsert" | "delete",
        "corpus_version": <positive int>
      }

    Processing flow:
    1. Parse and validate SQS record payloads; skip malformed records (non-retried).
    2. Compute:
       - target_version: max corpus_version across valid events.
       - coalesced_event_count: latest-op-per-doc count for observability.
    3. Read BM25 pointer (bm25/pointer.json) and compare versions.
       - If pointer version >= target version, skip rebuild and return success.
    4. Build baseline in-memory chunk index.
       - Prefer warm-start from latest snapshot (SNAPSHOT_KEY).
       - Fallback to manifest bootstrap (status == "indexed") if snapshot is unavailable.
    5. Query corpus-change deltas newer than pointer version and apply net changes
       (upsert/delete) to in-memory state.
    6. Force BM25 construction in-memory to fail fast before publishing artifacts.
    7. Persist latest snapshot, then update pointer to latest snapshot once snapshot is successfully written.
    8. Return SQS partial-batch response.
       - Success: {"batchItemFailures": []}.
       - Failure: retry valid messages by returning their messageIds as failures.

    Version semantics:
    - latest_pointer_version: currently published BM25 corpus version.
    - target_version: highest version observed in the incoming SQS batch.
    - snapshot_version: version written for this rebuild.
    """

    req_id = context.aws_request_id

    sqs_records = event.get("Records")
    if not isinstance(sqs_records, list):
        raise ValueError("Invalid event format: 'Records'")

    logger.info(
        json.dumps(
            {
                "event": "bm25_update_handler_started",
                "aws_request_id": req_id,
                "record_count": len(sqs_records),
            }
        )
    )

    valid_events: List[Dict[str, Any]] = []
    valid_message_ids: List[str] = []
    invalid_message_ids: List[str] = []

    for sqs_record in sqs_records:
        sqs_message_id = sqs_record.get("messageId")
        try:
            payload = json.loads(sqs_record["body"])
        except (KeyError, TypeError, json.JSONDecodeError):
            logger.warning(
                f"BM25 update skip SQS event: invalid json body (sqs_message_id={sqs_message_id})"
            )
            invalid_message_ids.append(sqs_message_id)
            continue

        normalized_payload = _normalize_event_payload(payload)
        if normalized_payload is None:
            logger.warning(
                f"BM25 update skip SQS event: invalid payload shape (sqs_message_id={sqs_message_id})"
            )
            invalid_message_ids.append(sqs_message_id)
            continue

        valid_events.append(normalized_payload)
        if sqs_message_id:
            valid_message_ids.append(sqs_message_id)

    if not valid_events:
        logger.info(
            json.dumps(
                {
                    "event": "bm25_update_no_valid_events",
                    "aws_request_id": req_id,
                    "invalid_record_count": len(invalid_message_ids),
                }
            )
        )
        return {"batchItemFailures": []}

    try:
        target_version = max(event_payload["corpus_version"] for event_payload in valid_events)
        coalesced_event_count = len(_coalesce_by_doc_latest(valid_events))

        manifest_repository = ManifestRepository(table_name=settings.DYNAMODB_MANIFEST_TABLE_NAME)
        base_store = BaseStore(bucket=settings.S3_GP_BUCKET_NAME, vectors=False)
        chunk_store = S3GPChunkStore(bucket=settings.S3_GP_BUCKET_NAME, chunks_prefix=settings.S3_GP_CHUNK_PREFIX)
        corpus_monitor = CorpusMonitor(table_name=settings.DYNAMODB_CORPUS_CHANGE_TABLE_NAME)

        # Get latest pointer version pointer to compare against target_version for this update batch before commencing updates. 
        latest_pointer = load_latest_pointer(base_store=base_store, pointer_key=POINTER_KEY)
        latest_pointer_version = int(latest_pointer.get("corpus_version", 0))

        # If latest pointer version is already ahead of target_version, skip update processing to avoid redundant work.
        if latest_pointer_version >= target_version:
            logger.info(
                json.dumps(
                    {
                        "event": "bm25_snapshot_up_to_date_skip",
                        "aws_request_id": req_id,
                        "target_version": target_version,
                        "latest_pointer_version": latest_pointer_version,
                        "coalesced_event_count": coalesced_event_count,
                    }
                )
            )
            return {"batchItemFailures": []}

        # Build a baseline corpus state:
        # - Prefer latest persisted BM25 snapshot for cheap warm-start.
        # - Fall back to indexed-doc bootstrap (from manifest table) when no snapshot exists yet.
        chunk_index = load_chunk_index_from_latest_snapshot(
            bucket=settings.S3_GP_BUCKET_NAME,
            snapshot_key=SNAPSHOT_KEY,
            base_store=base_store
        )
        if chunk_index is None:
            documents_by_chunk_id, doc_chunk_index = load_indexed_documents(
                manifest_repository=manifest_repository,
                s3_chunk_store=chunk_store,
            )
            chunk_index = InMemoryChunkIndex(
                documents_by_chunk_id=documents_by_chunk_id,
                doc_chunk_index=doc_chunk_index,
            )

    
        latest_changes = corpus_monitor.get_latest_changes(prev_latest_change_id=latest_pointer_version)
        if not latest_changes and latest_pointer_version < target_version:
            raise RuntimeError(
                f"No corpus deltas found after pointer version={latest_pointer_version} despite "
                f"target_version={target_version}"
            )

        apply_changes(
            latest_changes=latest_changes,
            chunk_index=chunk_index,
            chunk_loader=lambda doc_id: load_documents_for_doc_id(doc_id, chunk_store),
        )

        all_documents: List[Document] = list(chunk_index.documents_by_chunk_id.values())
        docs_by_chunk_id = chunk_index.documents_by_chunk_id
        doc_chunk_index = chunk_index.doc_chunk_index
        chunk_to_doc_id = _build_chunk_to_doc_id_map(doc_chunk_index)

        snapshot_version = max(target_version, corpus_monitor.latest_change_id)

        # Validation: force construct BM25 index (not persisted) to fail fast on invalid corpus before snapshot/pointer publish.
        if all_documents:
            BM25Retriever.from_documents(all_documents)

        # Update and persist snapshot json with new corpus state after changes applied 
        built_at_utc = datetime.now(timezone.utc).isoformat()
        snapshot_payload = {
            "corpus_version": snapshot_version,
            "built_at_utc": built_at_utc,
            "stats": {
                "doc_count": len(doc_chunk_index),
                "chunk_count": len(all_documents),
                "coalesced_event_count": coalesced_event_count,
            },
            "documents": [
                {
                    "id": doc.id,
                    "page_content": doc.page_content,
                    "metadata": {
                        "doc_id": chunk_to_doc_id.get(chunk_id, ""),
                        "chunk_id": chunk_id,
                    },
                }
                for chunk_id, doc in docs_by_chunk_id.items()
            ],
        }
        base_store.s3.client.put_object(
            Bucket=base_store.bucket,
            Key=SNAPSHOT_KEY,
            Body=json.dumps(snapshot_payload).encode("utf-8"),
            ContentType="application/json",
        )

        # Update and persist pointer after snapshot successfully persisted.
        pointer_payload = {
            "corpus_version": snapshot_version,
            "s3_key": SNAPSHOT_KEY,
            "updated_at_utc": built_at_utc,
        }
        base_store.s3.client.put_object(
            Bucket=base_store.bucket,
            Key=POINTER_KEY,
            Body=json.dumps(pointer_payload).encode("utf-8"),
            ContentType="application/json",
        )

        logger.info(
            json.dumps(
                {
                    "event": "bm25_snapshot_publish_success",
                    "aws_request_id": req_id,
                    "target_version": snapshot_version,
                    "snapshot_key": SNAPSHOT_KEY,
                    "doc_count": len(doc_chunk_index),
                    "chunk_count": len(all_documents),
                    "coalesced_event_count": coalesced_event_count,
                }
            )
        )
        return {"batchItemFailures": []}

    except Exception:
        logger.exception(
            f"BM25 snapshot rebuild failed (aws_request_id={req_id} valid_record_count={len(valid_message_ids)})"
        )
        return {"batchItemFailures": _to_batch_failures(valid_message_ids)}


def _normalize_event_payload(payload: Dict[str, Any]) -> Dict[str, Any] | None:
    """Validate and normalize one BM25 event payload, else return None."""
    doc_id = payload.get("doc_id")
    op = payload.get("op")
    corpus_version = payload.get("corpus_version")

    if not isinstance(doc_id, str) or not doc_id.strip():
        return None
    if op not in ("upsert", "delete"):
        return None

    try:
        corpus_version_int = int(corpus_version)
    except (TypeError, ValueError):
        return None

    if corpus_version_int <= 0:
        return None

    return {
        "doc_id": doc_id.strip(),
        "op": op,
        "corpus_version": corpus_version_int,
    }


def _coalesce_by_doc_latest(valid_events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Helper function that takes in a list of bm25 update event payloads 
    and de-duplicates events by doc_id, keeping only the latest event per doc_id by corpus_version.
    """
    latest_by_doc_id: Dict[str, Dict[str, Any]] = {}
    for event_payload in valid_events:
        doc_id = event_payload["doc_id"]
        existing = latest_by_doc_id.get(doc_id)
        if existing is None or event_payload["corpus_version"] >= existing["corpus_version"]:
            latest_by_doc_id[doc_id] = event_payload
    return list(latest_by_doc_id.values())


def _build_chunk_to_doc_id_map(doc_chunk_index: Dict[str, Set[str]]) -> Dict[str, str]:
    """Invert doc->chunk mapping into chunk->doc mapping."""
    out: Dict[str, str] = {}
    for doc_id, chunk_ids in doc_chunk_index.items():
        for chunk_id in chunk_ids:
            out[chunk_id] = doc_id
    return out


def _to_batch_failures(message_ids: List[str]) -> List[Dict[str, str]]:
    """Convert message IDs into SQS partial-batch failure entries."""
    return [{"itemIdentifier": message_id} for message_id in message_ids if message_id]
