from functools import lru_cache
from ...shared.aws_session import get_aws_session


@lru_cache(maxsize=1)
def _get_s3_client_modular(vectors:bool):
    """
    Return a cached s3 gp/vector client using cached boto3 session
    """
    session = get_aws_session()
    if not vectors:
        return session.client("s3")
    else: 
        return session.client("s3vectors")

class S3ClientModular:
    """
    Reusable S3Client for uploads into GP buckets (raw pdf docs) & vector buckets  
    """
    def __init__(self, s3_bucket_name: str, vectors: bool):
        self.s3_bucket_name = s3_bucket_name
        self.client = _get_s3_client_modular(vectors)
