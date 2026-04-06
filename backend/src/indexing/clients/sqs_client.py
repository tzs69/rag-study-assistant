from functools import lru_cache
from ...shared.aws_session import get_aws_session

@lru_cache(maxsize=1)
def _get_sqs_client():
    """Return a cached sqs client"""
    session = get_aws_session()
    return session.client("sqs")

class SQSClient:
    """
    Reusable SQS for pushing events into queue
    """
    def __init__(self, queue_url):
        self.queue_url = queue_url
        self.client = _get_sqs_client()
        