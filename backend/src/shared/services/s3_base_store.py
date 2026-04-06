"""
Provides a shared base class for S3-backed persistence stores used across app modules.
"""
from ..clients.s3_client import S3ClientModular

class BaseStore:
    def __init__(self, bucket:str, vectors:bool):
        self.bucket = bucket
        self.s3 = S3ClientModular(bucket, vectors)
