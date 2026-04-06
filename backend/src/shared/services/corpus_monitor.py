from typing import Dict, List

from .corpus_change_table import CorpusChangeTable


class CorpusMonitor:
    def __init__(self, table_name):
        self.corpus_change_table = CorpusChangeTable(table_name=table_name)
        self.latest_change_id = self.corpus_change_table.get_latest_change_id()


    def validate_latest_change(self):
        """Simple helper to validate corpus is in its latest version """
        return self.latest_change_id == self.corpus_change_table.get_latest_change_id()


    def get_latest_changes(self, prev_latest_change_id: int) -> Dict[str, str]:
        """
        Query corpus change table rows where change_id is newer than the provided
        cursor and return a net-effect mapping of {doc_id: op}.
        """
        out = dict()
        start_key = None

        latest_cid = None

        response_incomplete = True
        while response_incomplete:
            params = {
                "TableName": self.corpus_change_table.table_name,
                "KeyConditionExpression": "#pk = :pk AND #cid > :x",
                "ExpressionAttributeNames": {"#pk": "pk", "#cid": "change_id"},
                "ExpressionAttributeValues": {
                    ":pk": {"S": "CORPUS"},
                    ":x": {"N": str(prev_latest_change_id)},
                },
                "ScanIndexForward": True,  # oldest to newest
            }
            # Continue querying from previous LastEvaluatedKey cursor, if present.
            if start_key:
                params["ExclusiveStartKey"] = start_key

            response = self.corpus_change_table.dynamodb.client.query(**params)
            items: List[Dict[str, str]] = (response.get("Items", []))
            if items:
                for entry in items:
                    #   "Items": [
                    #     {"doc_id": {"S": "raw/a.pdf"}, "status": {"S": "indexed"}},
                    #     {"doc_id": {"S": "raw/b.pdf"}, "status": {"S": "indexed"}}
                    #   ]

                    # Log latest change_id for status update before returning
                    latest_cid = entry.get("change_id", {}).get("N")
                    if latest_cid:
                        latest_cid = int(latest_cid)

                    doc_id = entry.get("doc_id", {}).get("S")
                    op = entry.get("op", {}).get("S")
                    if doc_id and op in {"upsert", "delete"}:
                        # Oldest->newest query order means "latest op wins" for net effect.
                        out[doc_id] = op

            start_key = response.get("LastEvaluatedKey")
            if not start_key:
                response_incomplete = False

        if latest_cid:
            self.latest_change_id = latest_cid

        return out
