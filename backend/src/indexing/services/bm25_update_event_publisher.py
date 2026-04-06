from typing import Any, Dict
import json

from ..clients.sqs_client import SQSClient


class BM25UpdateEventService:


    def __init__(self, queue_url):
        self.sqs = SQSClient(queue_url)
        

    def publish_bm25_update_event_to_queue(self, event_payload: Dict[Any, Any]):
        """
        Given an event payload in dict format, send it to the queue 
        """

        # Verify valid event payload
        if not self._validate_bm25_update_event_payload(event_payload):
            raise ValueError()
        
        self.sqs.client.send_message(
            QueueUrl = self.sqs.queue_url,
            MessageBody = json.dumps(event_payload)
        )


    def _validate_bm25_update_event_payload(self, event_payload: Dict[Any, Any]) -> bool:
        """
        Helper function to verify that the event payload is in
        """

        # Check "doc_id" key exists and event_payload["doc_id"] is non-empty string
        doc_id = event_payload.get("doc_id")
        if not doc_id:
            return False
        elif not doc_id.strip():
            return False

        # Verify "op" key exists and payload["op"] is either "upsert" or "delete"
        op = event_payload.get("op")
        if not op:
            return False
        elif op != "upsert" and op != "delete":
            return False
        
        # Verify "corpus_version" key exists and event_payload["corpus_version"] is an int
        corpus_version = event_payload.get("corpus_version")
        if not corpus_version:
            return False
        elif not isinstance(corpus_version, int):
            return False
        
        return True