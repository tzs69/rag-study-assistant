from threading import Lock
from typing import Optional
import re

from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document


class KeywordSearchService:
    def __init__(self, chunks_list: list[Document], retriever: Optional[BM25Retriever] = None):
        self._lock = Lock()
        self._corpus_version: Optional[str] = None
        if retriever is not None:
            self._retriever = retriever
        elif chunks_list:
            self._retriever = BM25Retriever.from_documents(chunks_list)
        else:
            self._retriever = None

    def ensure_index(self, docs: list[Document], corpus_version: str):
        """
        Helper function to rebuild the in-memory BM25 index when the corpus version changes.
        """
        with self._lock:
            if self._corpus_version == corpus_version:
                return

            if not docs:
                self._retriever = None
                self._corpus_version = corpus_version
                return

            self._retriever = BM25Retriever.from_documents(docs)
            self._corpus_version = corpus_version

    def search(self, query: str, top_k: int = 10):
        """
        Takes in a query as a string, runs BM25 keyword search over the in-memory
        chunk document corpus, and returns the top k chunks in ranked order.

        Process flow:
        1) Pulls a wider BM25 candidate set than requested top_k
        2) Tokenizes the query and candidate chunk content
        3) Re-ranks BM25 candidates by lexical overlap while preserving BM25 rank as tie-breaker
        4) Returns the top k matching chunk Document objects
        """
        with self._lock:
            if self._retriever is None:
                return []

            # Pull a wider candidate set, then re-rank by lexical overlap so short
            # factual queries (e.g. "asian bmi threshold") prioritize exact matches.
            candidate_k = max(top_k * 4, 20)
            self._retriever.k = candidate_k
            candidates = self._retriever.invoke(query)

        query_tokens = _tokenize(query)
        if not query_tokens:
            return candidates[:top_k]

        scored: list[tuple[int, int, Document]] = []
        for rank, doc in enumerate(candidates):
            content_tokens = _tokenize(doc.page_content)
            overlap = len(query_tokens & content_tokens)
            if overlap > 0:
                scored.append((overlap, rank, doc))

        scored.sort(key=lambda item: (-item[0], item[1]))
        return [doc for _, _, doc in scored[:top_k]]


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))
