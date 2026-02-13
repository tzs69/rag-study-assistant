import asyncio
import logging
from functools import lru_cache
from typing import Any, Dict, List

from ..session import get_aws_session

@lru_cache(maxsize=1)
def _get_s3_client():
    """Return a cached s3 client using cached boto3 session"""
    session = get_aws_session()
    return session.client("s3")


class S3Client:
    """
    Reusable S3Client for uploads into GP buckets (raw pdf docs) & vector buckets  
    """
    def __init__(self, s3_bucket_name: str):
        self.s3_bucket_name = s3_bucket_name
        self.client = _get_s3_client()
