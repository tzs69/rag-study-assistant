import logging
from threading import Event, Lock, Thread
from typing import Any, Dict, List, Optional

from ..shared.services.chunk_index import InMemoryChunkIndex
from ..indexing.services.indexed_documents_loader import load_indexed_documents
from ..indexing.services.latest_chunk_index_loader import load_chunk_index_from_latest_snapshot
from ..indexing.services.manifest_repository import ManifestRepository
from ..shared.services.s3_base_store import BaseStore
from ..shared.services.s3_gp_chunk_store import S3GPChunkStore
from .services.keyword_retriever import KeywordSearchService
from ..shared.services.latest_bm25_pointer_loader import load_latest_pointer

logger = logging.getLogger(__name__)


class RetrievalOrchestrator:

    def __init__(
            self, 
            corpus_change_table_name: str, 
            manifest_table_name: str, 
            s3_gp_bucket_name: str,
            chunks_prefix: str,
            bm25_pointer_key: str = "bm25/pointer.json",
            bm25_snapshot_key: str = "bm25/snapshot.json",
            bm25_poll_interval_seconds: int = 5,
            chat_history: Optional[List[Dict[str, Any]]] = None,
        ):
        self.corpus_change_table_name = corpus_change_table_name
        self.manifest_table = ManifestRepository(table_name=manifest_table_name)

        self.chunks_prefix = chunks_prefix
        self.s3_gp_bucket_name = s3_gp_bucket_name
        self.base_store = BaseStore(bucket=s3_gp_bucket_name, vectors=False)
        self.s3_chunk_store = S3GPChunkStore(bucket=s3_gp_bucket_name, chunks_prefix=chunks_prefix)
        self.bm25_pointer_key = bm25_pointer_key
        self.bm25_snapshot_key = bm25_snapshot_key
        self.bm25_poll_interval_seconds = max(1, int(bm25_poll_interval_seconds))
        self.latest_pointer_version = 0

        documents_by_chunk_id, doc_chunk_index = load_indexed_documents(
            manifest_repository=self.manifest_table,
            s3_chunk_store=self.s3_chunk_store
        )
        self.chunk_index = InMemoryChunkIndex(
            documents_by_chunk_id=documents_by_chunk_id,
            doc_chunk_index=doc_chunk_index,
        )

        self.bm25_retriever = KeywordSearchService(
            chunks_list=list(self.chunk_index.documents_by_chunk_id.values())
        )

        self._state_lock = Lock()
        self._poll_stop_event = Event()
        self._poll_thread: Optional[Thread] = None

        # Best-effort bootstrap from latest BM25 snapshot if already available.
        self._apply_bm25_index_refresh()

        self.chat_history = chat_history


    def start_background_polling(self) -> None:
        """Start the background BM25 pointer poll thread if it is not already running."""
        if self._poll_thread and self._poll_thread.is_alive():
            return
        self._poll_stop_event.clear()
        self._poll_thread = Thread(
            target=self._poll_bm25_pointer_loop,
            name="bm25-pointer-poller",
            daemon=True,
        )
        self._poll_thread.start()


    def stop_background_polling(self) -> None:
        """Signal the background BM25 pointer poll thread to stop and wait briefly for shutdown."""
        self._poll_stop_event.set()
        if self._poll_thread and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=2.0)


    def _poll_bm25_pointer_loop(self) -> None:
        """
        Background poll loop for BM25 freshness.

        Every bm25_poll_interval_seconds, checks whether the latest BM25 pointer
        version has advanced and triggers an in-memory state refresh when needed.
        Exceptions are contained and logged so polling continues running.
        """
        while not self._poll_stop_event.wait(self.bm25_poll_interval_seconds):
            try:
                self._apply_bm25_index_refresh()
            except Exception:
                logger.exception("BM25 pointer poll refresh failed")


    def _apply_bm25_index_refresh(self) -> bool:
        """
        Perform one pointer-driven refresh attempt.

        Loads the latest BM25 pointer, compares its corpus version against the
        in-memory version, and if corpus version is newer:
        - loads newest snapshot state,
        - rebuilds BM25 retriever with newest snapshot state
        - atomically swaps in-memory retrieval state.

        Returns:
            bool: True if state was refreshed, False if no update was applied.
        """
        latest_pointer_json = load_latest_pointer(base_store=self.base_store, pointer_key=self.bm25_pointer_key)
        retrieved_latest_pointer_version = int(latest_pointer_json.get("corpus_version", 0))
        snapshot_key = latest_pointer_json.get("s3_key", self.bm25_snapshot_key)

        # Early exit if malformed/missing snapshot key or pointer version already
        if not snapshot_key or not isinstance(snapshot_key, str):
            return False
        if retrieved_latest_pointer_version <= self.latest_pointer_version:
            return False

        chunk_index = load_chunk_index_from_latest_snapshot(
            bucket=self.s3_gp_bucket_name,
            snapshot_key=snapshot_key,
            base_store=self.base_store,
        )
        if chunk_index is None:
            return False

        bm25_retriever = KeywordSearchService(
            chunks_list=list(chunk_index.documents_by_chunk_id.values())
        )

        # Thread-safe commit of refreshed retrieval state after successful load and rebuild
        with self._state_lock:
            self.chunk_index = chunk_index
            self.bm25_retriever = bm25_retriever
            self.latest_pointer_version = retrieved_latest_pointer_version

        return True

