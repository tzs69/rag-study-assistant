"""
S3 Bucket Uploading service
 - S3DocUploaderService: into document store 
 - S3VectorUploaderService: Upload into vector store 
"""

from fastapi import UploadFile
from ..clients.s3_client import S3Client

class BaseUploaderService:
    def __init__(self, bucket):
        self.bucket = bucket
        self.s3_client = S3Client(bucket)
        
class S3DocUploaderService(BaseUploaderService):
    def __init__(self, bucket_name):
        super().__init__(bucket_name)

    async def upload_docs_async(self, files: list[UploadFile]):
        uploaded = []
        for f in files:
            data = await f.read()
            self.s3_client.client.put_object(
                Bucket=self.bucket,
                Key=f.filename,
                Body=data,
                ContentType=f.content_type or "application/octet-stream",
            )
            uploaded.append({"name": f.filename, "size": len(data)})
        return uploaded
