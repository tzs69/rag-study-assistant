import logging
from functools import lru_cache
from ...shared.aws_session import get_aws_session

@lru_cache(maxsize=1)
def _get_dynamodb_client():
    """Return a cached low-level dynamodb client using cached boto3 session"""
    session = get_aws_session()
    return session.client("dynamodb")

class DyanmoDBClient:
    """
    Reusable DynamoDB for appending to doc-vector lookup table
    """
    def __init__(self, table_name):
        self.table_name = table_name
        self.client = _get_dynamodb_client()
        