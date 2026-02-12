import asyncio
import logging
import os
from functools import lru_cache
from typing import Any, Dict, List

import boto3
from botocore.exceptions import ClientError

from .config import settings

@lru_cache(maxsize=1)
def _get_s3_client():
    """Create a cached boto3 session configured from env/settings (profile/region)."""
    profile = settings.AWS_PROFILE
    region = settings.AWS_REGION
    session = boto3.Session(profile_name=profile, region_name=region)
    return session.client("s3")


class S3Client:
    """
    Reusable S3Client for uploads into GP buckets (raw pdf docs) & vector buckets  
    """
    def __init__(self, s3_bucket_name: str):
        self.s3_bucket_name = s3_bucket_name
        self.client = _get_s3_client()

    

def get_s3_client(bucket_name) -> S3Client:
    try:
        return S3Client(bucket_name)
    except Exception as e:
        raise e
