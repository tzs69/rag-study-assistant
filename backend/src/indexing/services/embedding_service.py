"""
Embedding service to generate vectors from chunked text
 - Includes
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Optional 

from langchain_aws.embeddings.bedrock import BedrockEmbeddings

from ..clients.bedrock_client import BedrockClient
from .chunking_service import Chunk


@dataclass(frozen=True)
class VectorRecord:
    key: str
    data: Dict[str, List[float]]
    metadata: Optional[Dict[str, Any]] = None

class EmbeddingService:
    """
    Embedding service to embed convert chunked text as vectors
    Uses: amazon titan text embedding model v2
    """

    def __init__(self, embedding_model_id: str):
        bedrock = BedrockClient(embedding_model_id)
        self.embedding_model = BedrockEmbeddings(
            client=bedrock.client,
            model_id=bedrock.model_id
        )

    def embed_chunks(self, chunks_list: List[Chunk]) -> List[VectorRecord]:
        """
        Processes a list of Chunk objects, embeds each chunk
        and returns a list of VectorRecord objects for storage into s3 vectors
        """
        
        if len(chunks_list)==0:
            raise ValueError("chunks_list cannot be empty")
        
        vector_records_list: List[VectorRecord] = []

        # Pass as input to embedding model
        text_only: List[str] = [chunk.text for chunk in chunks_list]

        # Embed the chunk texts and return list of vectors 
        vectors_only: List[List[float]] = self.embedding_model.embed_documents(text_only) 
        
        # Construct list of VectorRecords to be passed as input to Vector uploader service
        for idx, chunk in enumerate(chunks_list):
            """
            Sample of payload format into s3 vectors:
            {
                "key": "raw/a.pdf#0001",
                "data": {"float32": [0.12, -0.03, ...]},
                "metadata": {
                    "doc_id": "raw/a.pdf",
                    ... 
                }
            }
            """
            vector = vectors_only[idx]
            vector_wrapped = {"float32": vector}

            metadata = dict()
            metadata["doc_id"] = chunk.doc_id

            vector_records_list.append(
                VectorRecord(
                    key=chunk.chunk_id,
                    data=vector_wrapped,
                    metadata=metadata
                )
            )

        return vector_records_list