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
    def __init__(self, bucket: str, vector_index: str, read_only: bool):
        super().__init__(bucket, vectors=True)
        self.vector_index = vector_index
        self.read_only = read_only

        if read_only:
            resp = self.s3.client.get_index(
                vectorBucketName=bucket,
                indexName=vector_index
            )
            self.vector_index_dim = resp.get("index").get("dimension")
        else:
            self.vector_index_dim = None


    def upload_vectors(
        self,
        vector_records_list: List[VectorRecord],
        vector_list_size_threshold: int, # Minimally above 100 for efficiency 
        batch_size_divisor: int,
    ):  
        # Enforce instance permissions
        if self.read_only:
            raise PermissionError("This read-only S3VectorStore instance is not configured to upload vectors")

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

        # Enforce instance permissions
        if self.read_only:
            raise PermissionError("This read-only S3VectorStore instance is not configured to delete vectors")
        
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
    

    def query_vector_index(self, query_vector: List[float], top_k: int) -> List[str]:
        """
        Queries the vector index with an embedded query vector and returns the top k vector keys.
        Only for use by read-only vector store instances during retrieval.
        """

        # Enforce instance permissions
        if not self.read_only:
            raise PermissionError("This write-only S3VectorStore instance is not configured to query vectors")

        if len(query_vector) != self.vector_index_dim:
            raise ValueError(f"Query vector dimension {len(query_vector)} does not match index dimension {self.vector_index_dim}")
        
        query_vector_response = self.s3.client.query_vectors(
            vectorBucketName = self.bucket,
            indexName = self.vector_index,
            queryVector = { "float32" : query_vector },
            topK = top_k
        )
        
        # Extract keys of top k vectors in response (sorted nearest to furthest alr)
        top_k_vectors = list(map(lambda vector: vector.get("key"), query_vector_response.get("vectors", [])))
        return top_k_vectors

