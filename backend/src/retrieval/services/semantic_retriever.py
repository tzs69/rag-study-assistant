from typing import Dict, List

from langchain_core.documents import Document
from langchain_aws.embeddings.bedrock import BedrockEmbeddings
from ...shared.clients.bedrock_client import BedrockClient
from ...shared.services.s3_vector_store import S3VectorStore


class SemanticSearchService:
    def __init__(self, bucket: str, vector_index: str, embedding_model_id: str):
        bedrock = BedrockClient(embedding_model_id)
        self.embedding_model = BedrockEmbeddings(
            client=bedrock.client,
            model_id=bedrock.model_id,
            dimensions=512
        )
        self.s3_vector_store = S3VectorStore(bucket=bucket, vector_index=vector_index, read_only=True)

    
    def search(self, query: str, top_k: int, documents_by_chunk_id: Dict[str, Document]) -> List[Document]:
        """
        Takes in a query as a string, embeds it into a high dimensional vector (same
        dimension as target vector index we want to run search on), runs a cosine similarity search
        and returns the top k chunks in sorted order (nearest cosine distance to furthest)

        Process flow:
        1) Embeds query using same embedding model used to embed chunks during indexing
        2) Runs S3 Vector Store instance's query_vector_index on embedded query vectors to obtain keys of 
            top k nearest neighbours
        3) Map obtained keys back to Chunk IDs for final vector search result
        """

        if not query:
            raise ValueError("Query cannot be empty")
        
        # 1) Embed the query text and return vector 
        query_embedded: List[float] = self.embedding_model.embed_query(query)
        
        # 2) Query the vector index with embedded query vector
        top_k_vector_keys = self.s3_vector_store.query_vector_index(query_embedded, top_k)

        # 3) Map obtained vector keys to chunk Document objects
        top_k_chunks = list(map(lambda vector_key: documents_by_chunk_id.get(vector_key), top_k_vector_keys))
        top_k_chunks_filtered = [chunk for chunk in top_k_chunks if chunk is not None]
        return top_k_chunks_filtered[:top_k]