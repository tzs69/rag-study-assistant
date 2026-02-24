from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_experimental.text_splitter import SemanticChunker
from ..clients.bedrock_client import BedrockClient
from .document_reader_service import DocumentText


@dataclass(frozen=True)
class Chunk:
    doc_id: str
    chunk_id: str
    text: str


class SemanticChunkingService:
    """
    Semantic chunker using aws bedrock models.
    """

    def __init__(self, chunking_llm_model_id: str) -> None:
        self.chunking_llm_model = BedrockClient(chunking_llm_model_id)
        self.chunker = SemanticChunker(self.chunking_llm_model)

    def build_semantic_chunks_from_doctext(self, doctext: DocumentText) -> list[Chunk]:
        """
            Processes a single DocumentText object
            and returns context-aware Chunk objects
        """
        doctext_processed = self._process_document_text(doctext)
        doc_id, text = doctext_processed['doc_id'], doctext_processed['text']

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
    def _process_document_text(doctext: DocumentText) -> dict[str, Any]:
        """
            Checks that DocumentText object contains doc_id and text fields
            and return them inside a dict format
        """
        processed = dict()
        try:
            processed['doc_id'] = doctext.doc_id
            processed['text'] = doctext.text
            return processed
        
        except AttributeError as e:
            raise

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
