from __future__ import annotations

from typing import Any, Dict, List
import re

from langchain_experimental.text_splitter import SemanticChunker
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_aws.embeddings.bedrock import BedrockEmbeddings
from ...shared.clients.bedrock_client import BedrockClient
from .document_reader_service import DocumentText
from ...shared.services.s3_gp_chunk_store import Chunk
from ...shared.utils.parse_docid import extract_doc_id_from_raw_key

class SemanticChunkingService:
    """
    Semantic chunker using aws bedrock models.
    Secondary(backup) chunker using langchain recursive char text splitter
    is also used to complement primary semantic chunker.
    """

    def __init__(self, chunking_llm_model_id: str) -> None:
        bedrock = BedrockClient(chunking_llm_model_id)
        self.embeddings_model = BedrockEmbeddings(
            client=bedrock.client,
            model_id=bedrock.model_id,
        )
        self.primary_chunker = SemanticChunker(
            self.embeddings_model,
            breakpoint_threshold_type="percentile",
            breakpoint_threshold_amount=80,
            min_chunk_size=400
        )
        self.secondary_chunker = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=80,
            separators=[
                "\n\n",   # paragraph
                ". ",     # sentence full stop
                "? ",     # question
                "! ",     # exclamation
                "; ",     # semicolon
                ", ",     # comma fallback
                " ",      # word fallback
                "",       # character fallback
            ],
            keep_separator="end"
        )

    def build_chunks_from_doctext(self, doctext: DocumentText) -> list[Chunk]:
        """
        Build storage-ready chunks from extracted document text.

        Process:
        1. Validate and normalize the extracted text.
        2. Split extracted text into primary chunks with semantic chunker.
        3. Merge undersized primary chunks into a neighbour.
        4. Split oversized primary chunks and merge undersized overlapping sub-chunks.
        5. Assign deterministic chunk IDs and return Chunk objects.
        """
        doctext_processed = self._validate_document_text(doctext)
        doc_id, text = doctext_processed['doc_id'], doctext_processed['text']

        if not doc_id:
            raise ValueError("doc_id is required")

        # 1. Text pre-processing
        cleaned = self._normalize_text(text)
        if not cleaned:
            return []

        # 2-3. Create semantic chunks, then merge undersized primary chunks.
        primary_chunks: List[str] = self.primary_chunker.split_text(cleaned)
        primary_chunks = self.merge_chunks(primary_chunks, min_size=200, primary=True)

        merged: List[str] = []
        for chunk in primary_chunks:
            # 4. Split oversized primary chunks, then clean up small overlapping sub-chunks.
            if len(chunk) > 800:
                sub_chunks = self.secondary_chunker.split_text(chunk)
                sub_chunks = self.merge_chunks(sub_chunks, min_size = 200, primary=False)
                merged.extend(sub_chunks)
            else:
                merged.append(chunk)

        # 5. Build Chunk objects to be passed as input to
        #   A) s3 chunk store  
        #   B) Embedding service
        chunks_list: list[Chunk] = []
        for idx, chunk_str in enumerate(merged):
            chunk_id = f"{extract_doc_id_from_raw_key(doc_id)}_chunk_{idx + 1:04d}"

            chunks_list.append(
                Chunk(
                    doc_id=doc_id,
                    chunk_id=chunk_id,
                    text=chunk_str
                )
            )

        return chunks_list

    @staticmethod
    def _validate_document_text(doctext: DocumentText) -> Dict[str, Any]:
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
        paragraphs = re.split(r"\n\s*\n+", text or "")
        return "\n\n".join(
            " ".join(paragraph.split())
            for paragraph in paragraphs
            if paragraph.strip()
        )

    def merge_chunks(self, chunks: List[str], min_size: int, primary: bool = True) -> List[str]:
        """
        Helper function to merge undersized chunks into an adjacent neighbour.
        Removes splitter overlap only when processing secondary chunks
        as primary chunks (produced by Semantic Chunker) less likely to contain overlap.
        """
        merged: list[str] = []

        for chunk in chunks:
            if len(chunk) < min_size and merged:
                if primary:
                    merged[-1] = f"{merged[-1].rstrip()} {chunk.lstrip()}"
                else:
                    merged[-1] = self._join_sub_chunks(merged[-1], chunk)
            else:
                merged.append(chunk)

        # Edge case: The first chunk has no left neighbour, so merge it into its right neighbour.
        if len(merged) > 1 and len(merged[0]) < min_size:
            if primary:
                merged[0] = f"{merged[0].rstrip()} {merged[1].lstrip()}"
            else:
                merged[0] = self._join_sub_chunks(merged[0], merged[1])
            merged.pop(1)

        return merged

    @staticmethod
    def _join_sub_chunks(left: str, right: str) -> str:
        """Helper function to deduplicate and merge two sub-chunk texts with potential overlaps."""
        min_overlap = 10
        max_overlap = min(len(left), len(right), 80)

        # Prefer the longest suffix-prefix match to avoid duplicating splitter overlap.
        for size in range(max_overlap, min_overlap-1, -1):
            if left.endswith(right[:size]):
                return left + right[size:]

        return f"{left.rstrip()} {right.lstrip()}"
