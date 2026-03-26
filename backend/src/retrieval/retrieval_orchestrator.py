from typing import Any, Callable, Dict, List, Optional
from .services.corpus_monitor import CorpusMonitor

from .services.chunk_loader import load_documents_for_doc_id, load_indexed_documents
from .services.corpus_delta_applier import apply_changes
from .services.chunk_index import InMemoryChunkIndex
from ..indexing.services.manifest_repository import ManifestRepository
from ..shared.services.s3_gp_chunk_store import S3GPChunkStore


class RetrievalOrchestrator:

    def __init__(
            self, 
            corpus_change_table_name: str, 
            manifest_table_name: str, 
            s3_gp_bucket_name: str,
            chunks_prefix: str,
            chat_history: Optional[List[Dict[str, Any]]] = None,
        ):
        self.corpus_monitor = CorpusMonitor(table_name=corpus_change_table_name)
        self.manifest_table = ManifestRepository(table_name=manifest_table_name)

        self.chunks_prefix = chunks_prefix
        self.s3_gp_bucket_name = s3_gp_bucket_name
        self.s3_chunk_store = S3GPChunkStore(bucket=s3_gp_bucket_name, chunks_prefix=chunks_prefix)

        documents_by_chunk_id, doc_chunk_index = load_indexed_documents(
            manifest_repository=self.manifest_table,
            s3_chunk_store=self.s3_chunk_store
        )
        self.chunk_index = InMemoryChunkIndex(
            documents_by_chunk_id=documents_by_chunk_id,
            doc_chunk_index=doc_chunk_index,
        )

        self.chat_history = chat_history


    def refresh_documents_if_stale(self):
        """
        Corpus documents state refresh. 
        
        Behaviour:
        - Check if in-memory corpus state the latest by calling self.corpus_monitor.validate_latest_change() 
        - If false, calls self.corpus_monitor.get_latest_changes() to fetch dict of latest unapplied changes
        - Applies fetched changes and updates in-memory chunk index artifacts:
            - self.chunk_index.doc_chunk_index
            - self.chunk_index.documents_by_chunk_id 
        """
        if not self.corpus_monitor.validate_latest_change():
            latest_change_id: int = self.corpus_monitor.latest_change_id
            latest_changes: Dict[str, str] = self.corpus_monitor.get_latest_changes(latest_change_id)
            chunk_loader: Callable = lambda doc_id: load_documents_for_doc_id(doc_id, self.s3_chunk_store)

            apply_changes(
                latest_changes=latest_changes,
                chunk_index=self.chunk_index,
                chunk_loader=chunk_loader
            )
            

    def run_retrieval(self, raw_user_query: str) -> str:
        pass
