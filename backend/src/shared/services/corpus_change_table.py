from ..clients.dynamodb_client import DyanmoDBClient
from datetime import datetime, timezone
from typing import Any, Dict, List
from botocore.exceptions import ClientError

class CorpusChangeTable:


    def __init__(self, table_name: str) -> None:
        if not table_name or not str(table_name).strip():
            raise ValueError("table_name is required")

        self.table_name = table_name
        self.dynamodb = DyanmoDBClient(table_name)
        self.pk = "CORPUS"


    def get_latest_change_id(self) -> int:
        """
        Return the largest change_id in the corpus change stream.
        Returns 0 when no change events exist yet.
        """
        response: dict[str, Any] = self.dynamodb.client.query(
            TableName=self.table_name,
            KeyConditionExpression="#pk = :pk",
            ExpressionAttributeNames={"#pk": "pk"},
            ExpressionAttributeValues={":pk": {"S": self.pk}},
            ScanIndexForward=False,  # descending by sort key (change_id)
            Limit=1,
            ConsistentRead=True,
        )

        items = response.get("Items", [])
        if not items:
            return 0

        change_attr = items[0].get("change_id", {})
        return int(change_attr.get("N", "0"))
    
    def add_change_record(self, doc_id: str, op: str, max_attempts: int = 3):

        updated_at = datetime.now(timezone.utc).isoformat()

        for attempt in range(1, max_attempts + 1):
            change_id = str(self.get_latest_change_id() + 1)
            try:
                self.dynamodb.client.put_item(
                    TableName=self.table_name,
                    Item={
                        "pk": {"S": self.pk},
                        "change_id": {"N": change_id},
                        "doc_id": {"S": doc_id},
                        "op": {"S": op},
                        "updated_at": {"S": updated_at}
                    },
                    ConditionExpression="attribute_not_exists(#pk) AND attribute_not_exists(#cid)",
                    ExpressionAttributeNames={
                        "#pk": "pk",
                        "#cid": "change_id",
                    },
                )
                return {"change_id": int(change_id), "updated_at": updated_at}
            
            except ClientError as e:
                if e.response['Error']['Code'] != "ConditionalCheckFailedException":
                    raise
                if attempt == max_attempts:
                    raise RuntimeError(
                        f"Failed to allocate unique change_id after {max_attempts} attempts"
                    ) from e
