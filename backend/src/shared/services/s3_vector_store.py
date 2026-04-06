"""
Persistence service for writing document vectors into the configured S3 Vector bucket/index.
"""
from typing import Any, Dict, List, Optional
from dataclasses import asdict, dataclass

from .s3_base_store import BaseStore


@dataclass(frozen=True)
class VectorRecord:
    key: str
    data: Dict[str, List[float]]
    metadata: Optional[Dict[str, Any]] = None
    

class S3VectorStore(BaseStore):
    def __init__(self, bucket, vector_index):
        super().__init__(bucket, vectors=True)
        self.vector_index = vector_index

    def upload_vectors(
        self,
        vector_records_list: List[VectorRecord],
        vector_list_size_threshold: int, # Minimally above 100 for efficiency 
        batch_size_divisor: int,
    ):
        if not vector_records_list:
            raise ValueError("vector_records_list cannot be empty")

        # Check that size_treshold above 100 (no point batching small inputs)
        if vector_list_size_threshold <200:
            raise ValueError("size_treshold must be greater than or equal to 200")

        if batch_size_divisor <= 1:
            raise ValueError("batch_size_divisor must be > 1")

        # Format vector_records_list to match s3 vector payload shape
        vector_records_list_formatted: List[dict[str, Any]] = [
            asdict(v) for v in vector_records_list
        ]

        n = len(vector_records_list_formatted)

        # Decide whether to batch
        if n > vector_list_size_threshold:
            # Ensure batch size >= 1
            batch_size = max(1, n // batch_size_divisor)

            for batch in self._split_into_batches(vector_records_list_formatted, batch_size):
                self._put_vectors_helper(batch)
        else:
            self._put_vectors_helper(vector_records_list_formatted)

        # Build summary dict for logging successful upserts 
        # to give worker green light to change status to "indexed" in DynamoDB
        summary_dict = {
            "ok": True,
            "total_records": n,
            "batched": n > vector_list_size_threshold,
            "batch_size": batch_size if n > vector_list_size_threshold else n,
            "index_name": self.vector_index
        }

        return summary_dict

    @staticmethod
    def _split_into_batches(list_to_batch: List[Any], batch_size: int):
        if batch_size <= 0:
            raise ValueError("batch_size must be > 0")
        for i in range(0, len(list_to_batch), batch_size):
            yield list_to_batch[i : i + batch_size]
    

    def _put_vectors_helper(self, vectors: List[dict[str, Any]]):
        self.s3.client.put_vectors(
            vectorBucketName=self.bucket,
            indexName=self.vector_index,
            vectors=vectors,
        )        

    def delete_vectors(self, vector_keys_list: List[str]):
        """
        Delete vectors from the configured S3 Vector index by key list.

        Args:
            vector_keys_list: List of vector keys associated with a document.

        Returns:
            Summary metadata for deletion logging.
        """
        self.s3.client.delete_vectors(
            vectorBucketName=self.bucket,
            indexName=self.vector_index,
            keys=vector_keys_list
        )
        return {
            "vector_bucket": self.bucket,
            "vector_index": self.vector_index,
            "vector_keys": vector_keys_list
        }
