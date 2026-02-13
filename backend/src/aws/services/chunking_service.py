from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_experimental.text_splitter import SemanticChunker
from ..clients.bedrock_client import BedrockClient



@dataclass(frozen=True)
class Chunk:
    doc_id: str
    chunk_id: str
    text: str


class SemanticChunkingService:
    """Semantic chunker using aws bedrock models."""

    def __init__(self, embedding_model_id: str) -> None:
        self.bedrock_embedding_model = BedrockClient(embedding_model_id)
        self.chunker = SemanticChunker(self.bedrock_embedding_model)

    def build_semantic_chunks_from_doctext(self, doc_id: str, text: str) -> list[Chunk]:
        """
            Generate deterministic semantic chunks from raw document text
            and return chunk objects with stable chunk ID
        """
        if not doc_id:
            raise ValueError("doc_id is required")

        cleaned = self._normalize_text(text)
        if not cleaned:
            return []

        # Call helper function
        cleaned_split: list[str] = self._semantic_chunking_helper(cleaned)

        chunks_list: list[Chunk] = []

        for idx, chunk_str in enumerate(cleaned_split):
            chunk_id = f"{doc_id}#{idx + 1:04d}"

            chunks_list.append(
                Chunk(
                    doc_id=doc_id,
                    chunk_id=chunk_id,
                    text=chunk_str
                )
            )

        return chunks_list

    @staticmethod
    def _normalize_text(text: str) -> str:
        return " ".join((text or "").split())

    def _semantic_chunking_helper(self, text: str) -> list[str]:
        """
            Delegate to LangChain SemanticChunker 
            to split normalized text into semantically coherent chunk strings
        """
        return self.chunker.split_text(text)


def chunks_to_vector_records(chunks_list: list[Chunk]) -> list[dict[str, Any]]:
    """Convert chunks objects into a basic payload shape for downstream vector upsert."""
    return [
        {
            "id": chunk.chunk_id,
            "text": chunk.text,
            "metadata": {
                "doc_id": chunk.doc_id,
            },
        }
        for chunk in chunks_list
    ]
