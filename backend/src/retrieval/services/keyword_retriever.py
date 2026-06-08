from threading import Lock
from typing import List, Optional

from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document


class KeywordRetrievalService:
    def __init__(self, chunks_list: List[Document], retriever: Optional[BM25Retriever] = None):
        self._lock = Lock()
        self._corpus_version: Optional[str] = None
        if retriever is not None:
            self._retriever = retriever
        elif chunks_list:
            self._retriever = BM25Retriever.from_documents(chunks_list)
        else:
            self._retriever = None


    def ensure_index(self, docs: List[Document], corpus_version: str):
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


    def search(self, query: str, top_k: int = 10) -> List[Document]:
        """
        Takes in a query as a string, runs BM25 keyword search over the in-memory
        chunk document corpus, and returns the top k chunks in ranked order.
        """
        with self._lock:
            if self._retriever is None:
                return []

            candidate_k = max(top_k * 4, 20)
            self._retriever.k = candidate_k
            candidates = self._retriever.invoke(query)

        return candidates[:top_k]
