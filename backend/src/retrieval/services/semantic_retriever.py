from typing import Dict, List

from langchain_core.documents import Document
from langchain_aws.embeddings.bedrock import BedrockEmbeddings
from ...shared.clients.bedrock_client import BedrockClient
from ...shared.services.s3_vector_store import S3VectorStore


class SemanticRetrievalService:
    def __init__(self, bucket: str, vector_index: str, embedding_model_id: str, min_cosine_threshold: float = 0.60):
        bedrock = BedrockClient(embedding_model_id)
        self.embedding_model = BedrockEmbeddings(
            client=bedrock.client,
            model_id=bedrock.model_id,
            dimensions=512
        )
        self.s3_vector_store = S3VectorStore(bucket=bucket, vector_index=vector_index, read_only=True)
        if not -1.0 <= min_cosine_threshold <= 1.0:
            raise ValueError(f"Minimum cosine similarity score threshold {min_cosine_threshold} is out of bounds")
        else:
            self.min_cosine_threshold = min_cosine_threshold

    
    def search(self, query: str, top_k: int, documents_by_chunk_id: Dict[str, Document]) -> List[Document]:
        """
        Takes in a query as a string, embeds it into a high dimensional vector (same
        dimension as target vector index we want to run search on), runs a cosine similarity search
        and returns copied top k chunk Documents in sorted order (nearest cosine distance to furthest).
        Each returned Document includes additional metadata (vector distance metric, cosine similarity score).

        Process flow:
        1) Embeds query using same embedding model used to embed chunks during indexing
        2) Runs S3 Vector Store instance's query_vector_index on embedded query vectors to obtain keys of 
            top k nearest neighbours
        3) Map obtained keys back to copied chunk Documents and attach vector similarity score metadata
        """

        if not query:
            raise ValueError("Query cannot be empty")
        
        # 1) Embed the query text and return vector 
        query_embedded: List[float] = self.embedding_model.embed_query(query)
        
        # 2) Query the vector index with embedded query vector
        distance_metric, top_k_vectors = self.s3_vector_store.query_vector_index(
            query_embedded,
            top_k,
            self.min_cosine_threshold,
        )

        # 3) Map obtained vector keys to copied chunk Documents with score metadata
        top_k_chunks = []
        for vector in top_k_vectors:
            chunk = documents_by_chunk_id.get(vector.get("key"))
            distance = vector.get("distance")
            if chunk is None or distance is None:
                continue

            top_k_chunks.append(
                chunk.model_copy(
                    update={
                        "metadata": {
                            **chunk.metadata,
                            "vector_distance_metric": distance_metric,
                            "vector_distance": distance,
                            "vector_similarity": 1.0 - distance,
                        }
                    }
                )
            )
        return top_k_chunks[:top_k]
