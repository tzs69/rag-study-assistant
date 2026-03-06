import json
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
from urllib.parse import unquote_plus
from ..services.s3_gp_raw_document_store import S3GPRawDocumentStore
from ..services.manifest_repository import ManifestRepository
from ..services.s3_gp_chunk_store import S3GPChunkStore
from ..services.s3_vector_store import S3VectorStore
from ..config import settings

def deletion_handler(event, context):
    """
    Lambda function to handle deletion of documents and their associated vector data when an S3 delete event is triggered.

    This function performs the following steps:
    1. Parses SQS-wrapped S3 delete events to extract the deleted object key.
    2. Claims deletion ownership in the manifest table and reads associated vector keys.
    3. Deletes the chunk artifact from the general-purpose S3 bucket.
    4. Deletes associated vectors from the S3 Vector index.
    5. Finalizes deletion by clearing vector keys and transitioning manifest status to `deleted`.

    Args:
        event (dict): The event data containing information about the S3 delete action.
        context (object): The runtime information of the Lambda function.
    """
    req_id = context.aws_request_id

    sqs_delete_events_list = event.get("Records")
    if not isinstance(sqs_delete_events_list, list):
        raise ValueError("Invalid event format: 'Records'")
    
    logger.info(
        json.dumps(
            {
                "event": "deletion_handler_started",
                "aws_request_id": req_id,
                "record_count": len(event["Records"]),
            }
        )
    )

    # Initialize helper classes
    raw_doc_store = S3GPRawDocumentStore(bucket=settings.S3_GP_BUCKET_NAME, raw_prefix=settings.S3_GP_RAW_PREFIX)
    manifest_repository = ManifestRepository(table_name=settings.DYNAMODB_MANIFEST_TABLE_NAME)      
    chunk_store = S3GPChunkStore(bucket=settings.S3_GP_BUCKET_NAME, chunks_prefix=settings.S3_GP_CHUNK_PREFIX)
    vector_store = S3VectorStore(bucket=settings.S3_VECTOR_BUCKET_NAME, vector_index=settings.S3_VECTOR_INDEX_NAME)

    for sqs_deletion_record in sqs_delete_events_list:
        sqs_message_id = sqs_deletion_record.get("messageId")

        try:
            payload = json.loads(sqs_deletion_record["body"])
        except (KeyError, TypeError, json.JSONDecodeError):
            logger.warning(
                f"Deletion skip SQS event: invalid json body (sqs_message_id={sqs_message_id})"
            )
            continue

        s3_wrapper = payload.get("Records")
        if not isinstance(s3_wrapper, list):
            logger.warning(
                f"Deletion skip SQS event: unrecognized message (sqs_message_id={sqs_message_id})"
            )
            continue

        for s3_event in s3_wrapper:
            
            # Make sure s3 event payload is in appropiate format for further processing
            if not isinstance(s3_event, dict):
                logger.warning(
                    f"Deletion skip s3 event: payload detected in non-dict format (sqs_message_id={sqs_message_id})"
                )
                continue
            
            
            # Verify s3 key exists
            s3_data = s3_event.get("s3")
            if not isinstance(s3_data, dict):
                logger.warning(
                    f"Deletion skip s3 event: missing 's3' key in s3_event (sqs_message_id={sqs_message_id})"
                )
                continue
            
            # Validate existence of keys nested within s3 data 
            bucket_data = s3_data.get("bucket")
            if not isinstance(bucket_data, dict):
                logger.warning(
                    f"Deletion skip s3 event: missing 'bucket' key in s3_event[s3] (sqs_message_id={sqs_message_id})"
                )
                continue
            bucket = bucket_data.get("name")
            if not isinstance(bucket, str) or not bucket:
                logger.warning(
                    f"Deletion skip s3 event: missing 'name' key in s3_event[s3][bucket] (sqs_message_id={sqs_message_id})"
                )
                continue
            object_data = s3_data.get("object")
            if not isinstance(object_data, dict):
                logger.warning(
                    f"Deletion skip s3 event: missing 'object' key in s3_event[s3] (sqs_message_id={sqs_message_id})"
                )
                continue
            raw_key = object_data.get("key")
            if not isinstance(raw_key, str) or not raw_key:
                logger.warning(
                    f"Deletion skip s3 event: missing 'key' key in s3_event[s3][object] (sqs_message_id={sqs_message_id})"
                )
                continue

            # Verify eventName key exists and guard against non-upload events 
            eventName = s3_event.get("eventName")
            if not isinstance(eventName, str) or not eventName:
                logger.warning(
                    f"Deletion skip s3 event: missing 'eventName' key (sqs_message_id={sqs_message_id})"
                )
                continue
            if not eventName.startswith("ObjectRemoved:"):
                logger.warning(
                    f"Deletion skip s3 event: non-delete event detected (sqs_message_id={sqs_message_id} event_name={eventName})"
                )
                continue

            # Verify bucket of deleted object and guard against deletions from unrelated buckets
            if bucket != settings.S3_GP_BUCKET_NAME:
                logger.warning(
                    f"Deletion skip s3 event: delete event from unrelated bucket (sqs_message_id={sqs_message_id} bucket={bucket})"
                )
                continue

            # Decode doc_id
            doc_id = unquote_plus(raw_key)

            # Claim deletion of document
            deletion_claim_response = manifest_repository.claim_reclaim_deletion(
                doc_id=doc_id, req_id=req_id
            )
            logger.info(
                json.dumps(
                    {
                        "event": "deletion_claim_result",
                        "doc_id": doc_id,
                        "bucket": bucket,
                        "sqs_message_id": sqs_message_id,
                        "s3_event_name": eventName,
                        "status": deletion_claim_response.get("status"),
                        "aws_request_id": req_id,
                    }
                )
            )
            if deletion_claim_response["status"] != "deleting":
                continue

            # Delete associated document chunk jsonl object from S3 /chunks
            try:
                chunk_delete_response = chunk_store.delete_chunks_for_docid(doc_id=doc_id)
                logger.info(json.dumps(
                    {
                        "event": "deletion_chunk_delete_success", 
                        **chunk_delete_response
                    }
                ))
            except Exception as e:
                logger.exception(
                    f"Deletion document chunks delete failed (doc_id={doc_id} sqs_message_id={sqs_message_id} aws_request_id={req_id})"
                )
                manifest_repository.mark_manifest_failed(doc_id=doc_id, ingest=False, error_message=str(e))
                raise RuntimeError(f"Document chunks delete failed for doc_id='{doc_id}'") from e
            
            # Extract list of vector keys from deletion claim response
            vector_keys = deletion_claim_response["vector_keys"]

            # Delete associated chunk vectors from S3 vector store
            if vector_keys:
                try:
                    vector_delete_response = vector_store.delete_vectors(vector_keys_list=vector_keys)
                    logger.info(json.dumps(
                    {
                        "event": "deletion_vector_delete_success", 
                        **vector_delete_response
                    }
                ))
                except Exception as e:
                    logger.exception(
                        f"Deletion chunk vectors delete failed (doc_id={doc_id} sqs_message_id={sqs_message_id} aws_request_id={req_id})"
                    )
                    manifest_repository.mark_manifest_failed(doc_id=doc_id, ingest=False, error_message=str(e))
                    raise RuntimeError(f"Chunk vectors delete failed for doc_id='{doc_id}'") from e
                
            # Finalize deletion by clearing all vector keys for manifest row and updating status to `deleted`
            try:
                finalize_deletion_response = manifest_repository.clear_vectors_finalize_deletion(
                    doc_id=doc_id, req_id=req_id
                )
                logger.info(json.dumps(
                    {
                        "event": "deletion_finalize_success", 
                        **finalize_deletion_response, 
                        "aws_request_id": req_id
                    }
                ))
            except Exception as e:
                logger.exception(
                    f"Deletion finalization manifest upsert failed (doc_id={doc_id} sqs_message_id={sqs_message_id} aws_request_id={req_id})"
                )
                manifest_repository.mark_manifest_failed(doc_id=doc_id, ingest=False, error_message=str(e))
                raise RuntimeError(f"Deletion finalization failed for doc_id='{doc_id}'") from e
