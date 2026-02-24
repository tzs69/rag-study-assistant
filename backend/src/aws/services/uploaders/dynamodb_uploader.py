from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from ...clients.dynamodb_client import DyanmoDBClient
from ..embedding_service import VectorRecord

class DynamoDBUploaderService:
    """
    Writes ingestion/indexing metadata into a DynamoDB table.

    Intended use:
    - Persist a manifest of vector keys by `doc_id` (for delete cleanup)
    - Optionally persist indexing status fields (processing/indexed/failed)

    This class uses the low-level boto3 DynamoDB client payload format.
    """

    def __init__(self, table_name: str) -> None:
        if not table_name or not str(table_name).strip():
            raise ValueError("table_name is required")

        self.table_name = table_name
        self.dynamodb = DyanmoDBClient(table_name)

    def insert_manifest(self, vector_records_list: List[VectorRecord], status: Optional[str] = "processing") -> Dict[str, Any]:
        """
        Insert a manifest record for a document with associated vector keys.

        `vector_records_list` is expected to be the list of VectorRecord objects corresponding to the document's chunks.
        The `key` field from each VectorRecord will be extracted and stored as the vector keys in DynamoDB.
        """
        if not vector_records_list:
            raise ValueError("vector_records_list cannot be empty")


        # Obtain and validate doc_id from first VectorRecord inside vector_records_list that contains it in its metadata
        doc_id = None
        for record in vector_records_list:
            if record.metadata and "doc_id" in record.metadata:
                doc_id = record.metadata["doc_id"]
                self._validate_doc_id(doc_id)
                break
        
        # Try second approach: attempt to extract doc_id from the key field of the first VectorRecord (assuming format like "raw/a.pdf#0001")
        if not doc_id:
            first_record = vector_records_list[0]
            if first_record.key and "#" in first_record.key:
                doc_id = first_record.key.split("#")[0]

        # Final validation check for doc_id
        if not doc_id:
            raise ValueError("At least one VectorRecord in vector_records_list must contain a valid doc_id in its metadata")
        
        # Extract vector keys from the VectorRecord list, ensuring they are valid non-empty strings
        vector_keys = [record.key for record in vector_records_list if record.key and str(record.key).strip()]

        # Validate that we have at least one valid vector key to store
        if not vector_keys:
            raise ValueError("At least one valid vector key is required in vector_records_list")

        # Validation passed, proceed to build and insert the manifest item into DynamoDB
        self.dynamodb.client.put_item(
            TableName=self.table_name,
            Item={
                "doc_id": {"S": doc_id},
                "vector_keys": {"L": [{"S": key} for key in vector_keys]},
                "status": {"S": status}
            }
        )


        return {
            "doc_id": doc_id,
            "table_name": self.table_name,
            "vector_key_count": len(vector_keys), # Check that this mathches the length of vector_records_list
            "status": status,
        }

    @staticmethod
    def _validate_doc_id(doc_id: str) -> None:
        if not doc_id or not str(doc_id).strip():
            raise ValueError("doc_id is required")
        

    def get_manifest(self, doc_id: str) -> Dict[str, Any]:
        """Fetch a manifest record by `doc_id`."""
        self._validate_doc_id(doc_id)

        response = self.dynamodb.client.get_item(
            TableName=self.table_name,
            Key={"doc_id": {"S": doc_id}},
        )
        return response

    def delete_manifest(self, doc_id: str) -> Dict[str, Any]:
        """Delete a manifest record by `doc_id`."""
        self._validate_doc_id(doc_id)

        self.dynamodb.client.delete_item(
            TableName=self.table_name,
            Key={"doc_id": {"S": doc_id}},
        )
        return {"doc_id": doc_id, "table_name": self.table_name, "deleted": True}

    def update_status(
        self,
        doc_id: str,
        status: str,
        *,
        error_message: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Status update helper function with guards against stale error messages from past status updates.
        Assumes the item already exists (or allows partial status-only records, depending on table usage).
        """
        self._validate_doc_id(doc_id)
        if not status or not status.strip():
            raise ValueError("status is required")

        expr_names = {"#s": "status"}
        expr_values = {":s": {"S": status}}

        if status == "failed":
            if not error_message:
                raise ValueError("error_message is required when status='failed'")
            expr_names["#e"] = "error_message"
            expr_values[":e"] = {"S": error_message}
            update_expression = "SET #s = :s, #e = :e"
        else:
            # Clear stale error details on success/retry states
            expr_names["#e"] = "error_message"
            update_expression = "SET #s = :s REMOVE #e"

        self.dynamodb.client.update_item(
            TableName=self.table_name,
            Key={"doc_id": {"S": doc_id}},
            UpdateExpression=update_expression,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_values,
        )

        return {"doc_id": doc_id, "table_name": self.table_name, "status": status}
