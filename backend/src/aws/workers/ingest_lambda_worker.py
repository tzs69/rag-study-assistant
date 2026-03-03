import json
import logging
from urllib.parse import unquote_plus
from ..services.document_reader_service import DocumentReaderService, DocumentText
from ..services.uploaders.dynamodb_uploader import DynamoDBUploaderService
from ..services.uploaders.s3_gp_chunk_uploader_service import S3GPChunkUploaderService
from ..services.chunking_service import SemanticChunkingService, Chunk
from ..services.embedding_service import EmbeddingService, VectorRecord
from ..services.uploaders.s3_vector_uploader_service import S3VectorUploaderService
from ..config import settings

from typing import List

VECTOR_LIST_SIZE_THRESHOLD = 200 # Follow vector uploader service validation that batching only occurs when len(list)>200 to balance efficiency and overhead of batching
VECTOR_UPLOAD_BATCH_SIZE_DIVISOR = 5
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

def ingestion_handler(event, context):
    """
    Lambda function to handle ingestion of documents and their associated vector data when an S3 create event is triggered.

    This function performs the following steps:
    1. Parses the incoming S3 create event to extract the bucket name and object key.
    2. Retrieves the document from S3 and processes it (e.g., text extraction, chunking).
    3. Generates vector embeddings for the processed document chunks.
    4. Stores the vector embeddings in the S3 vector bucket.
    5. Creates a manifest entry in DynamoDB to keep track of the ingested document and its associated vector data.

    Args:
        event (dict): The event data containing information about the S3 create action.
        context (object): The runtime information of the Lambda function.
    """
    
    if "Records" not in event:
        raise ValueError("Invalid event format: 'Records' key not found")
    
    logger.info(
        json.dumps(
            {
                "event": "ingestion_handler_started",
                "aws_request_id": context.aws_request_id,
                "record_count": len(event["Records"]),
            }
        )
    )

    # Initialize helper classes
    document_reader = DocumentReaderService(bucket_name=settings.S3_GP_BUCKET_NAME)
    dynamodb_uploader = DynamoDBUploaderService(table_name=settings.DYNAMODB_MANIFEST_TABLE_NAME)      
    chunking_service = SemanticChunkingService(chunking_llm_model_id=settings.CHUNKING_MODEL_ID)
    chunk_uploader = S3GPChunkUploaderService(bucket=settings.S3_GP_BUCKET_NAME, chunks_prefix=settings.S3_GP_CHUNK_PREFIX)
    embedding_service = EmbeddingService(embedding_model_id=settings.EMBEDDING_MODEL_ID)
    s3_vector_uploader = S3VectorUploaderService(bucket=settings.S3_VECTOR_BUCKET_NAME, vectors=True)
    
    req_id = context.aws_request_id

    for sqs_record in event["Records"]:
        sqs_message_id = sqs_record.get("messageId")

        try:
            payload = json.loads(sqs_record["body"])
        except (KeyError, TypeError, json.JSONDecodeError):
            logger.warning(
                f"Ingestion skip SQS event: invalid json body (sqs_message_id={sqs_message_id})"
            )
            continue

        s3_wrapper = payload.get("Records")
        if not isinstance(s3_wrapper, list):
            logger.warning(
                f"Ingestion skip SQS event: unrecognized message (sqs_message_id={sqs_message_id})"
            )
            continue

        for s3_event in s3_wrapper:
            
            # Make sure s3 event payload is in appropiate format for further processing
            if not isinstance(s3_event, dict):
                logger.warning(
                    f"Ingestion skip s3 event: payload detected in non-dict format (sqs_message_id={sqs_message_id})"
                )
                continue
            
            
            # Verify s3 key exists
            s3_data = s3_event.get("s3")
            if not isinstance(s3_data, dict):
                logger.warning(
                    f"Ingestion skip s3 event: missing 's3' key in s3_event (sqs_message_id={sqs_message_id})"
                )
                continue
            
            # Validate existence of keys nested within s3 data 
            bucket_data = s3_data.get("bucket")
            object_data = s3_data.get("object")
            if not isinstance(bucket_data, dict) or not isinstance(object_data, dict):
                logger.warning(
                    f"Ingestion skip s3 event: missing 'bucket' key in s3_event[s3] (sqs_message_id={sqs_message_id})"
                )
                continue
            bucket = bucket_data.get("name")
            if not isinstance(bucket, str) or not bucket:
                logger.warning(
                    f"Ingestion skip s3 event: missing 'name' key in s3_event[s3][bucket] (sqs_message_id={sqs_message_id})"
                )
                continue
            raw_key = object_data.get("key")
            if not isinstance(raw_key, str) or not raw_key:
                logger.warning(
                    f"Ingestion skip s3 event: missing 'key' key in s3_event[s3][object] (sqs_message_id={sqs_message_id})"
                )
                continue

            # Verify eventName key exists and guard against non-upload events 
            eventName = s3_event.get("eventName")
            if not isinstance(eventName, str) or not eventName:
                logger.warning(
                    f"Ingestion skip s3 event: missing 'eventName' key (sqs_message_id={sqs_message_id})"
                )
                continue
            if not eventName.startswith("ObjectCreated:"):
                logger.warning(
                    f"Ingestion skip s3 event: non-upload event detected (sqs_message_id={sqs_message_id} event_name={eventName})"
                )
                continue

            # Decode doc_id
            doc_id = unquote_plus(raw_key)

            # Claim ingestion of document
            claim_response = dynamodb_uploader.claim_reclaim_ingestion(
                doc_id=doc_id, bucket=bucket, req_id=req_id
            )
            logger.info(
                json.dumps(
                    {
                        "event": "ingestion_claim_result",
                        "doc_id": doc_id,
                        "bucket": bucket,
                        "sqs_message_id": sqs_message_id,
                        "s3_event_name": eventName,
                        "status": claim_response.get("status"),
                        "aws_request_id": req_id,
                    }
                )
            )
            if claim_response["status"] != "processing":
                continue


            # Read document from S3
            try:
                doc_text: DocumentText = document_reader.read_document_from_s3(doc_id=doc_id)
                if not doc_text:
                    raise ValueError(f"Document text extraction failed for doc_id='{doc_id}'")
                logger.info(json.dumps(
                    {
                        "event": "ingestion_read_success", 
                        "doc_id": doc_id, 
                        "bucket": bucket
                    }
                ))
            except Exception as e:
                logger.exception(
                    f"Ingestion raw document read failed (doc_id=doc_id{doc_id} bucket={bucket} sqs_message_id={sqs_message_id} aws_request_id={req_id})",                    
                )
                dynamodb_uploader.mark_ingestion_failed(doc_id=doc_id, error_message=str(e))
                raise RuntimeError(f"Document reading failed for doc_id='{doc_id}'") from e


            # Chunk extracted document text
            try:
                chunks: List[Chunk] = chunking_service.build_semantic_chunks_from_doctext(doc_text)
                if not chunks:
                    raise ValueError(f"Chunking produced no output for doc_id='{doc_id}'")
                logger.info(json.dumps(
                    {
                        "event": "ingestion_chunk_success", 
                        "doc_id": doc_id, 
                        "chunk_count": len(chunks)
                    }
                ))
            except Exception as e:
                logger.exception(
                    f"Ingestion chunking failed (doc_id={doc_id} sqs_message_id={sqs_message_id} aws_request_id={req_id})"
                )
                dynamodb_uploader.mark_ingestion_failed(doc_id=doc_id, error_message=str(e))
                raise RuntimeError(f"Document chunking failed for doc_id='{doc_id}'") from e
            
            
            # Upload chunks to S3 and get their vector embeddings
            try:
                chunk_upload_response = chunk_uploader.upload_chunks_jsonl(doc_id=doc_id, chunks=chunks)
                logger.info(json.dumps(
                    {
                        "event": "ingestion_chunk_upload_success", 
                        **chunk_upload_response
                    }
                ))
            except Exception as e:
                logger.exception(
                    f"Ingestion chunk upload failed (doc_id={doc_id} sqs_message_id={sqs_message_id} aws_request_id={req_id})"
                )
                dynamodb_uploader.mark_ingestion_failed(doc_id=doc_id, error_message=str(e))
                raise RuntimeError(f"Chunk upload failed for doc_id='{doc_id}'") from e
            
            
            # Generate embeddings for chunks and upload vectors to S3
            try:
                vector_payloads: List[VectorRecord] = embedding_service.embed_chunks(chunks)
                vector_upload_response = s3_vector_uploader.upload_vectors(
                    vector_records_list=vector_payloads, 
                    index_name=settings.S3_VECTOR_INDEX_NAME,
                    vector_list_size_threshold=VECTOR_LIST_SIZE_THRESHOLD,
                    batch_size_divisor=VECTOR_UPLOAD_BATCH_SIZE_DIVISOR
                )
                logger.info(json.dumps(
                    {
                        "event": "ingestion_vector_upload_success", 
                        "doc_id": doc_id, 
                        **vector_upload_response
                    }
                ))
            except Exception as e:
                logger.exception(
                    f"Ingestion vector upload failed (doc_id={doc_id} sqs_message_id={sqs_message_id} aws_request_id={req_id})"
                )
                dynamodb_uploader.mark_ingestion_failed(doc_id=doc_id, error_message=str(e))
                raise RuntimeError(f"Vector embedding generation or vector upload failed for doc_id='{doc_id}'") from e
            

            # Finalize ingestion by updating manifest with vector keys and transitioning status to `indexed`
            try:
                finalize_response = dynamodb_uploader.update_vectors_finalize_ingestion(
                    doc_id=doc_id, req_id=req_id, vector_records_list=vector_payloads
                )
                logger.info(json.dumps(
                    {
                        "event": "ingestion_finalize_success", 
                        **finalize_response, 
                        "aws_request_id": req_id
                    }
                ))
            except Exception as e:
                logger.exception(
                    f"Ingestion finalization manifest upsert failed (doc_id={doc_id} sqs_message_id={sqs_message_id} aws_request_id={req_id})"
                )
                dynamodb_uploader.mark_ingestion_failed(doc_id=doc_id, error_message=str(e))
                raise RuntimeError(f"Finalizing ingestion failed for doc_id='{doc_id}'") from e
