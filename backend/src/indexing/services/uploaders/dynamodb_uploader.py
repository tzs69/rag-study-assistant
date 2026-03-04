from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional
from botocore.exceptions import ClientError

from ...clients.dynamodb_client import DyanmoDBClient
from ..embedding_service import VectorRecord

class DynamoDBUploaderService:
    """
    Writes manifest records and ingestion status metadata into a DynamoDB table.

    Intended use:
    - Claim/reclaim ingestion work for a document (`processing` state)
    - Persist a manifest of vector keys by `doc_id` (for delete cleanup)
    - Track ingestion lifecycle status (`processing` / `indexed` / `failed`)

    This class uses the low-level boto3 DynamoDB client payload format.
    """

    def __init__(self, table_name: str) -> None:
        if not table_name or not str(table_name).strip():
            raise ValueError("table_name is required")

        self.table_name = table_name
        self.dynamodb = DyanmoDBClient(table_name)

    def claim_reclaim_ingestion(self, doc_id: str, bucket: str, req_id: str) -> Dict[str, Any]:
        """
        Claim ingestion for a document, or reclaim it only if a prior attempt failed.

        Behavior:
        - If no manifest record exists, insert a new placeholder manifest with:
          `status="processing"` and an empty `vector_keys` list.
        - If a record already exists, reclaim it only when current `status == "failed"`
          by transitioning it back to `processing` and updating `req_id`.
        - If a record exists with any other status (for example `processing` or `indexed`),
          return a skipped status so the caller can avoid duplicate work.

        Returns a small status dict for handler control flow. Current outcomes include:
        - `processing` (new claim or successful reclaim)
        - `skipped` (record exists but is not reclaimable)
        """
        if not doc_id or not str(doc_id).strip():
            raise ValueError("doc_id is required")
        if not bucket or not str(bucket).strip():
            raise ValueError("bucket is required")
        if not req_id or not str(req_id).strip():
            raise ValueError("req_id is required")
        
        # Initial insert
        try:
            self.dynamodb.client.put_item(
                TableName=self.table_name,
                Item={
                    "doc_id": {"S": doc_id},
                    "bucket": {"S": bucket},
                    "req_id": {"S": req_id},
                    "vector_keys": {"L": []},  # Start with an empty list of vector keys
                    "status": {"S": "processing"}  # Initial status
                },
                ConditionExpression="attribute_not_exists(doc_id)"  # Ensure we don't overwrite an existing record
            )

            return {
                "doc_id": doc_id,
                "status": "processing",
            }
        
        except ClientError as e:

            # Record already exists. Only allow retry reclaim from failed -> processing.
            if e.response['Error']['Code'] == "ConditionalCheckFailedException":
                try:
                    self.dynamodb.client.update_item(
                        TableName=self.table_name,
                        Key={"doc_id": {"S": doc_id}},
                        UpdateExpression="SET #s = :s, #r = :r",
                        ExpressionAttributeNames={"#s": "status", "#r": "req_id"},
                        ExpressionAttributeValues={
                            ":s": {"S": "processing"},
                            ":r": {"S": req_id},
                            ":failed": {"S": "failed"},
                        },
                        ConditionExpression="#s = :failed",
                    )

                    return {
                        "doc_id": doc_id,
                        "status": "processing",
                    }
                except ClientError as update_error:
                    if update_error.response["Error"]["Code"] == "ConditionalCheckFailedException":
                        return {
                            "doc_id": doc_id,
                            "status": "skipped",
                        }
                    raise update_error
            
            else:
                self.dynamodb.client.update_item(
                    TableName=self.table_name,
                    Key={"doc_id": {"S": doc_id}},
                    UpdateExpression="SET #s = :s",
                    ExpressionAttributeNames={"#s": "status"},
                    ExpressionAttributeValues={":s": {"S": "failed"}}
                )
                raise e


    def update_vectors_finalize_ingestion(self, doc_id: str, req_id: str, vector_records_list: List[VectorRecord], )-> Dict[str, Any]: 
        """
        Finalize ingestion by writing vector keys and transitioning status to `indexed`.

        `vector_records_list` is expected to contain the chunk-level VectorRecord objects
        produced for the document. Their `key` values are extracted and stored as the
        manifest's `vector_keys`.

        Safety guard:
        - This update is conditional and only succeeds when the manifest is currently
          `status == "processing"` and the stored `req_id` matches the caller's `req_id`.
        - This prevents stale/duplicate invocations from overwriting the manifest after
          another attempt has reclaimed ownership.
        """

        self._validate_doc_id(doc_id)
        if not vector_records_list:
            raise ValueError("vector_records_list cannot be empty")

        # Validate req_id
        if not req_id or not str(req_id).strip():
            raise ValueError("req_id is required")

        # Extract vector keys from the VectorRecord list, ensuring they are valid non-empty strings
        vector_keys = [record.key for record in vector_records_list if record.key and str(record.key).strip()]
        if not vector_keys:
            raise ValueError("At least one valid vector key is required in vector_records_list")

        # Finalize only if the current invocation still owns the claim.
        status = "indexed"
        self.dynamodb.client.update_item(
            TableName=self.table_name,
            Key={"doc_id": {"S": doc_id}},
            UpdateExpression="SET #v = :v, #s = :status",
            ExpressionAttributeNames={'#v': "vector_keys", "#s": "status", "#r": "req_id"},
            ExpressionAttributeValues={
                ":v": {"L": [{"S": key} for key in vector_keys]}, 
                ":status": {"S": status},
                ":processing": {"S": "processing"},
                ":req_id": {"S": req_id},
            },
            ConditionExpression="#s = :processing AND #r = :req_id"
        )

        return {
            "doc_id": doc_id,
            # "vector_key_count": len(vector_keys), # Check that this mathches the length of vector_records_list
            "status": status,
            "error": None
        }
    
    def mark_ingestion_failed(self, doc_id: str, *, error_message: Optional[str] = None,) -> Dict[str, Any]:
        """
        Mark an existing manifest record as `failed`.

        Optionally persists a non-empty `error_message` for debugging/observability.
        Intended to be called by the ingestion worker when processing fails after the
        manifest has already been claimed.
        """
        self._validate_doc_id(doc_id)
        status = "failed"

        update_expression = "SET #s = :s"
        expression_attribute_names = {"#s": "status"}
        expression_attribute_values = {":s": {"S": status}}

        if error_message and str(error_message).strip():
            update_expression += ", #e = :e"
            expression_attribute_names["#e"] = "error_message"
            expression_attribute_values[":e"] = {"S": str(error_message)}
        
        self.dynamodb.client.update_item(
            TableName=self.table_name,
            Key={"doc_id": {"S": doc_id}},
            UpdateExpression=update_expression,
            ExpressionAttributeNames=expression_attribute_names,
            ExpressionAttributeValues=expression_attribute_values,
        )

        return {"doc_id": doc_id, "status": status}
    

    @staticmethod
    def _validate_doc_id(doc_id: str) -> None:
        if not doc_id or not str(doc_id).strip():
            raise ValueError("doc_id is required")
        

    def get_manifest_record(self, doc_id: str) -> Dict[str, Any]:
        """
        Fetch a manifest record by `doc_id` (raw DynamoDB get_item response shape)
        """
        self._validate_doc_id(doc_id)

        response = self.dynamodb.client.get_item(
            TableName=self.table_name,
            Key={"doc_id": {"S": doc_id}},
        )
        return response

    def delete_manifest_record(self, doc_id: str) -> Dict[str, Any]:
        """
        Delete a manifest record by `doc_id` (typically used by deletion cleanup flow)
        """
        self._validate_doc_id(doc_id)

        self.dynamodb.client.delete_item(
            TableName=self.table_name,
            Key={"doc_id": {"S": doc_id}},
        )
        return {"doc_id": doc_id, "table_name": self.table_name, "deleted": True}
