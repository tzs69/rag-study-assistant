from typing import List

import httpx
from langchain_core.documents import Document


class RerankerClient:
    def __init__(self, base_url: str, timeout_secs: float = 20.0):
        self.reranker_client = httpx.Client(
            base_url=base_url,
            timeout=timeout_secs
        )


    def status_ok(self) -> bool:
        """
        Check whether the reranker app is reachable and reporting healthy.
        """
        try:
            response = self.reranker_client.get(url="/health")
            response.raise_for_status()
            payload = response.json()
            return payload.get("ok") is True
        except (httpx.HTTPError, ValueError):
            return False


    def rerank(self, query: str, docs_to_rerank: List[Document]) -> List[Document]:
        """
        Rerank candidate Documents by calling the cross-encoder reranker service.

        Process flow:
         1 - Return an empty list when there are no candidate Documents to rerank
         2 - Construct query-answer pairs using the query and each chunk text
         3 - Send a POST request to the reranker app and parse the JSON response
         4 - Validate the response contains one score per input Document
         5 - Copy candidate Documents into output list and update each Document's existing metadata
              with their associated rerank score
         6 - Sort Documents by descending order of score and return final sorted output list
        """
        if not docs_to_rerank:
            return []

        # Step 2: build query-answer pairs.
        qa_pairs = [(query, doc.page_content) for doc in docs_to_rerank]

        # Step 3: send rerank request and parse response.
        response = self.reranker_client.post(
            url="/rerank",
            json=qa_pairs
        )
        response.raise_for_status()
        payload = response.json()

        # Step 4: validate response shape before pairing scores back to Documents.
        rerank_scores = payload.get("scores_list")
        if not isinstance(rerank_scores, list):
            raise ValueError("Reranker response missing scores_list")
        if len(rerank_scores) != len(docs_to_rerank):
            raise ValueError("Reranker score count does not match document count")

        out: List = []

        # Step 5: attach rerank scores to copied Documents.
        for doc, score in zip(docs_to_rerank, rerank_scores):
            doc_metadata = doc.metadata
            doc_updated = Document(
                id=doc.id,
                page_content=doc.page_content,
                metadata={
                    **doc_metadata,
                    "rerank_score": score
                }
            )
            out.append((doc_updated, score))

        # Step 6: sort and return Documents by descending reranking score.
        out = sorted(out, key=lambda x: -x[1])
        return [doc for doc, _ in out]
