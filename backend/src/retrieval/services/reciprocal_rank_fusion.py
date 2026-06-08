from typing import Any, Dict, List, Tuple
from langchain_core.documents import Document


def rrf_combine(
    keyword_retrieval_results_list: List[Document],
    semantic_retrieval_results_list: List[Document],
    top_k: int,
    c: int = 60
) -> List[Document]:
    """
    Fuse keyword retrieval and semantic retrieval result lists using Reciprocal Rank Fusion (RRF).

    Process flow:
     1 - Walk through both ranked result lists in parallel by rank position.
     2 - For each chunk, compute its RRF contribution as 1 / (c + rank).
     3 - Deduplicate chunks by chunk_id while accumulating scores across both lists.
     4 - Track tie-break priority and source-specific ranks for each chunk.
     5 - Rebuild fused chunks as Document objects with retrieval rank metadata.
     6 - Sort fused chunks by descending RRF score, then descending tie-break priority.
     7 - Return the fused Document objects in final ranked order.

    Order of tie-breaking (priority) is as follows:
     - Chunk appears in: BOTH result lists > ONLY semantic retrieval results list > ONLY keyword retrieval results list
    """

    index = max(len(keyword_retrieval_results_list), len(semantic_retrieval_results_list))
    chunk_tracker: Dict[str, Dict[str, Any]] = dict()

    # Step 1: walk both result lists
    for i in range(index):

        # Keyword retrieval results list
        if i <= len(keyword_retrieval_results_list)-1:
            l1_chunk = keyword_retrieval_results_list[i]
            l1_chunk_id = l1_chunk.id

            # Step 2: compute RRF contribution
            rrf_score = 1 / (c + i + 1)

            # Steps 3-4: deduplicate by chunk_id, accumulate RRF score, and track source rank.
            if l1_chunk_id not in chunk_tracker:
                chunk_tracker[l1_chunk_id] = dict()
                chunk_tracker[l1_chunk_id]["rrf_score"] = rrf_score
                chunk_tracker[l1_chunk_id]["text"] = l1_chunk.page_content
                chunk_tracker[l1_chunk_id]["priority"] = 0
            else:
                chunk_tracker[l1_chunk_id]["rrf_score"] += rrf_score
                chunk_tracker[l1_chunk_id]["priority"] = 2
            chunk_tracker[l1_chunk_id]["keyword_retrieval_rank"] = i + 1

        # Semantic retrieval results list
        if i <= len(semantic_retrieval_results_list)-1:
            l2_chunk = semantic_retrieval_results_list[i]
            l2_chunk_id = l2_chunk.id

            # Step 2: compute RRF contribution
            rrf_score = 1 / (c + i + 1)

            # Steps 3-4: deduplicate by chunk_id, accumulate RRF score, and track source rank.
            if l2_chunk_id not in chunk_tracker:
                chunk_tracker[l2_chunk_id] = dict()
                chunk_tracker[l2_chunk_id]["rrf_score"] = rrf_score
                chunk_tracker[l2_chunk_id]["text"] = l2_chunk.page_content
                chunk_tracker[l2_chunk_id]["priority"] = 1
            else:
                chunk_tracker[l2_chunk_id]["rrf_score"] += rrf_score
                chunk_tracker[l2_chunk_id]["priority"] = 2
            chunk_tracker[l2_chunk_id]["semantic_retrieval_rank"] = i + 1

    out: List[Tuple[Document, float, int]] = []

    # Step 5: rebuild fused chunks as Documents with source-rank metadata.
    for chunk_id, metadata in chunk_tracker.items():

        chunk_text, rrf_score, priority = metadata["text"], metadata["rrf_score"], metadata["priority"]

        keyword_retrieval_rank, semantic_retrieval_rank = metadata.get("keyword_retrieval_rank"), metadata.get("semantic_retrieval_rank")

        chunk_metadata = {}
        if keyword_retrieval_rank is not None:
            chunk_metadata["keyword_retrieval_rank"] = keyword_retrieval_rank
        if semantic_retrieval_rank is not None:
            chunk_metadata["semantic_retrieval_rank"] = semantic_retrieval_rank

        chunk_doc = Document(
            id=chunk_id,
            page_content=chunk_text,
            metadata=chunk_metadata
        )
        out.append((chunk_doc, rrf_score, priority))

    # Step 6: sort by highest RRF score first, then highest tie-break priority.
    out = sorted(out, key=lambda x: (-x[1], -x[2]))

    # Step 7: return the fused Document objects in final ranked order.
    return [chunk_doc for chunk_doc, _, _ in out][:top_k]
