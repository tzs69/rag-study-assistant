"""
Provides a shared base class for indexing persistence stores backed by S3-compatible clients.
"""
from ..clients.s3_client import S3ClientModular

class BaseStore:
    def __init__(self, bucket:str, vectors:bool):
        self.bucket = bucket
        self.s3 = S3ClientModular(bucket, vectors)
