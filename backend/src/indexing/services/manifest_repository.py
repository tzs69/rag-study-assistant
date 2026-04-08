from __future__ import annotations

from typing import Any, Dict, List, Optional
from botocore.exceptions import ClientError

from ...shared.clients.dynamodb_client import DyanmoDBClient
from ...shared.services.s3_vector_store import VectorRecord

class ManifestRepository:
    """
    Writes manifest records and ingestion status metadata into a DynamoDB table.

    Intended use:
    - Claim/reclaim ingestion work for a document (`ingesting` state)
    - Persist a manifest of vector keys by `doc_id` (for delete cleanup)
    - Track lifecycle status (`ingesting` / `indexed` / `ingest failed` / `deleting` / `delete failed` / `deleted`)

    Invariant:
    - Update-only operations include `attribute_exists(doc_id)` conditions so they never
      upsert/create a new row by accident.

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
          `status="ingesting"` and an empty `vector_keys` list.
        - If a record already exists, reclaim it only when current `status == "ingest failed"`
          by transitioning it back to `ingesting` and updating `req_id`.
        - If a record exists with any other status (for example `ingesting` or `indexed`),
          return a skipped status so the caller can avoid duplicate work.

        Returns a small status dict for handler control flow. Current outcomes include:
        - `ingesting` (new claim or successful reclaim)
        - `skipped ingestion` (record exists but is not reclaimable)
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
                    "status": {"S": "ingesting"}  # Initial status
                },
                ConditionExpression="attribute_not_exists(doc_id)"  # Ensure we don't overwrite an existing record
            )

            return {
                "doc_id": doc_id,
                "status": "ingesting",
            }
        
        except ClientError as e:

            # Record already exists. Only allow retry reclaim from ingest failed -> ingesting.
            if e.response['Error']['Code'] == "ConditionalCheckFailedException":
                try:
                    self.dynamodb.client.update_item(
                        TableName=self.table_name,
                        Key={"doc_id": {"S": doc_id}},
                        UpdateExpression="SET #s = :s, #r = :r",
                        ExpressionAttributeNames={"#s": "status", "#r": "req_id"},
                        ExpressionAttributeValues={
                            ":s": {"S": "ingesting"},
                            ":r": {"S": req_id},
                            ":ingest_failed": {"S": "ingest failed"},
                        },
                        ConditionExpression="attribute_exists(doc_id) AND #s = :ingest_failed",
                    )

                    return {
                        "doc_id": doc_id,
                        "status": "ingesting",
                    }
                except ClientError as update_error:
                    if update_error.response["Error"]["Code"] == "ConditionalCheckFailedException":
                        return {
                            "doc_id": doc_id,
                            "status": "skipped ingestion",
                        }
                    raise update_error
            
            else:
                self.dynamodb.client.update_item(
                    TableName=self.table_name,
                    Key={"doc_id": {"S": doc_id}},
                    UpdateExpression="SET #s = :s",
                    ExpressionAttributeNames={"#s": "status"},
                    ExpressionAttributeValues={":s": {"S": "ingest failed"}},
                    ConditionExpression="attribute_exists(doc_id)",
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
          `status == "ingesting"` and the stored `req_id` matches the caller's `req_id`.
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
            UpdateExpression="SET #v = :v, #s = :s",
            ExpressionAttributeNames={'#v': "vector_keys", "#s": "status", "#r": "req_id"},
            ExpressionAttributeValues={
                ":v": {"L": [{"S": key} for key in vector_keys]}, 
                ":s": {"S": status},
                ":ingesting": {"S": "ingesting"},
                ":req_id": {"S": req_id},
            },
            ConditionExpression="attribute_exists(doc_id) AND #s = :ingesting AND #r = :req_id"
        )

        return {
            "doc_id": doc_id,
            # "vector_key_count": len(vector_keys), # Check that this mathches the length of vector_records_list
            "status": status,
        }
    
    def mark_manifest_failed(self, ingest: bool, doc_id: str, *, error_message: Optional[str] = None,) -> Dict[str, Any]:
        """
        Mark an existing manifest record as `failed`.

        Optionally persists a non-empty `error_message` for debugging/observability.
        Intended to be called by the ingestion worker when processing fails after the
        manifest has already been claimed.
        """
        self._validate_doc_id(doc_id)
        status = "ingest failed" if ingest else "delete failed"

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
            ConditionExpression="attribute_exists(doc_id)",
        )

        return {"doc_id": doc_id, "status": status}
    

    @staticmethod
    def _validate_doc_id(doc_id: str) -> None:
        if not doc_id or not str(doc_id).strip():
            raise ValueError("doc_id is required")
    

    def claim_reclaim_deletion(self, doc_id: str, req_id: str) -> Dict[str, Any]:
        """
        Claim deletion for a document, or reclaim it only if a prior attempt failed.

        Behaviour:
        - Transition status to `deleting` only when current status is `indexed` or `delete failed`.
        - Return `vector_keys` from the same conditional update response (`ALL_NEW`) for downstream vector deletion.
        - Return `skipped deletion` when the row is not in a reclaimable state.
        """
        self._validate_doc_id(doc_id)
        if not req_id or not str(req_id).strip():
            raise ValueError("req_id is required")
        try:
            response = self.dynamodb.client.update_item(
                TableName=self.table_name,
                Key={"doc_id": {"S": doc_id}},
                UpdateExpression="SET #s = :s, #r = :r",
                ExpressionAttributeNames={"#s": "status", "#r": "req_id"},
                ExpressionAttributeValues={
                    ":s": {"S": "deleting"},
                    ":r": {"S": req_id},
                    ":indexed": {"S": "indexed"},
                    ":delete_failed": {"S": "delete failed"}
                },
                # Prevent creation of new row (deletion should only affect pre-existing rows)
                ConditionExpression="attribute_exists(doc_id) AND (#s = :indexed OR #s = :delete_failed)",
                ReturnValues="ALL_NEW",
            )

            # Build list of vector keys to be passed as input to s3 vector store for deletion
            attrs = response.get("Attributes", {})
            vector_keys_attr = attrs.get("vector_keys", {"L": []})
            vector_keys_list_raw = vector_keys_attr.get("L", [])
            vector_keys_list_mapped: List[str] = [vk["S"] for vk in vector_keys_list_raw if "S" in vk]

            return {
                "doc_id": doc_id,
                "status": "deleting",
                "vector_keys": vector_keys_list_mapped,
            }
        
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return {
                    "doc_id": doc_id,
                    "status": "skipped deletion",
                    "vector_keys": [],
                }
            raise e


    def clear_vectors_finalize_deletion(self, doc_id: str, req_id: str) -> Dict[str, Any]:
        """
        Finalize deletion by clearing list of vector keys for manifest row and transitioning status to `deleted`.
        
        Safety guard:
        - This update is conditional and only succeeds when the manifest is currently
          `status == "deleting"` and the stored `req_id` matches the caller's `req_id`.
        """
        self._validate_doc_id(doc_id)

        if not req_id or not str(req_id).strip():
            raise ValueError("req_id is required")
        
        status = "deleted"
        self.dynamodb.client.update_item(
            TableName=self.table_name,
            Key={"doc_id": {"S": doc_id}},
            UpdateExpression="SET #v = :v, #s = :s",
            ExpressionAttributeNames={'#v': "vector_keys", "#s": "status", "#r": "req_id"},
            ExpressionAttributeValues={
                ":v": {"L": []}, 
                ":s": {"S": status},
                ":deleting": {"S": "deleting"},
                ":req_id": {"S": req_id},
            },
            ConditionExpression="attribute_exists(doc_id) AND #s = :deleting AND #r = :req_id"
        )

        return {
            "doc_id": doc_id,
            "status": status,
        }


    def fetch_indexed_docids(self) -> List[str]:
        """
        Helper function for quick lookup of all indexed doc_ids 
        
        - Utilizes client.query if table contains status-index GSI
        - For tables without status-index GSI, falls back to client.scan
        """
        try:
            response = self.dynamodb.client.query(
                TableName=self.table_name,
                IndexName="status-index",
                KeyConditionExpression="#s = :s",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":s": {"S": "indexed"}}
            )

            items: List[Dict[str, Dict[str, str]]] = response.get("Items", [])
        except ClientError as e:
            error = e.response.get("Error", {})
            is_missing_status_index = (
                error.get("Code") == "ValidationException"
                and "status-index" in str(error.get("Message", ""))
            )
            if not is_missing_status_index:
                raise

            # Fallback for tables that do not have the optional status-index GSI.
            items = []
            scan_kwargs: Dict[str, Any] = {
                "TableName": self.table_name,
                "FilterExpression": "#s = :s",
                "ExpressionAttributeNames": {"#s": "status"},
                "ExpressionAttributeValues": {":s": {"S": "indexed"}},
            }
            while True:
                page = self.dynamodb.client.scan(**scan_kwargs)
                items.extend(page.get("Items", []))
                last_evaluated_key = page.get("LastEvaluatedKey")
                if not last_evaluated_key:
                    break
                scan_kwargs["ExclusiveStartKey"] = last_evaluated_key

        indexed_docids = [
            item["doc_id"]["S"]
            for item in items
            if "doc_id" in item and "S" in item["doc_id"]
        ]

        return indexed_docids


    def fetch_status_by_doc_ids(self, doc_ids: List[str]) -> Dict[str, str]:
        """
        Return {doc_id: status} for the provided doc_ids.
        Missing rows are omitted from the output map.
        """
        out: Dict[str, str] = {}
        for doc_id in doc_ids:
            if not doc_id or not str(doc_id).strip():
                continue
            response = self.dynamodb.client.get_item(
                TableName=self.table_name,
                Key={"doc_id": {"S": doc_id}},
                ProjectionExpression="#s",
                ExpressionAttributeNames={"#s": "status"},
            )
            status_attr = response.get("Item", {}).get("status", {})
            status = status_attr.get("S")
            if status:
                out[doc_id] = status
        return out
