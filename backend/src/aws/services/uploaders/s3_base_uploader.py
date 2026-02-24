"""
    Provides parent class for s3 subclasses
     - S3GPUploaderService: Upload into general purpose buckets (for raw docs)
     - S3VectorUploaderService: Upload into 
"""
from ...clients.s3_client import S3ClientModular

class BaseUploader:
    def __init__(self, bucket:str, vectors:bool):
        self.bucket = bucket
        self.s3 = S3ClientModular(bucket, vectors)
