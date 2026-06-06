from typing import Any, Dict, List, Tuple
from langchain_core.documents import Document


def rrf_combine(
    keyword_results_list: List[Document], 
    vector_results_list: List[Document],
    k: int = 60
) -> List[Tuple[str, str]]:
    """
    Fuse keyword and vector search result lists using Reciprocal Rank Fusion (RRF).

    Process flow:
     1 - Walk through both ranked result lists in parallel by rank position.
     2 - For each chunk, compute its RRF contribution as 1 / (k + rank).
     3 - Deduplicate chunks by chunk_id while accumulating scores across both lists.
     4 - Track tie-break priority based on whether the chunk appears in one or both lists.
     5 - Sort fused chunks by descending RRF score, then descending tie-break priority.
     6 - Return the fused chunk_id and chunk text pairs in final ranked order.
        
    Order of tie-breaking (priority) is as follows: 
     - Chunk appears in: BOTH result lists > ONLY vector search results list > ONLY keyword search results list
    """

    index = max(len(keyword_results_list), len(vector_results_list))
    chunk_tracker: Dict[str, Dict[str, Any]] = dict()

    # Step 1: walk both result lists
    for i in range(index):

        # Keyword search results list
        if i <= len(keyword_results_list)-1:
            l1_chunk = keyword_results_list[i]
            l1_chunk_id = l1_chunk.id

            # Step 2: compute RRF contribution
            rrf_score = 1/(k + i + 1)

            # Step 3, 4: Deduplicate on chunk_id and accumulate RRF score
            # If already present in chunk_tracker, update tie-breaking priority weight
            if l1_chunk_id not in chunk_tracker:
                chunk_tracker[l1_chunk_id] = dict()
                chunk_tracker[l1_chunk_id]["rrf_score"] = rrf_score
                chunk_tracker[l1_chunk_id]["text"] = l1_chunk.page_content
                chunk_tracker[l1_chunk_id]["priority"] = 0
            else:
                chunk_tracker[l1_chunk_id]["rrf_score"] += rrf_score
                chunk_tracker[l1_chunk_id]["priority"] = 2
        
        # Vector search results list
        if i <= len(vector_results_list)-1:
            l2_chunk = vector_results_list[i]
            l2_chunk_id = l2_chunk.id

            # Step 2: compute RRF contribution
            rrf_score = 1/(k + i + 1)

            # Step 3, 4: Deduplicate on chunk_id and accumulate RRF score
            # If already present in chunk_tracker, update tie-breaking priority weight
            if l2_chunk_id not in chunk_tracker:
                chunk_tracker[l2_chunk_id] = dict()
                chunk_tracker[l2_chunk_id]["rrf_score"] = rrf_score
                chunk_tracker[l2_chunk_id]["text"] = l2_chunk.page_content
                chunk_tracker[l2_chunk_id]["priority"] = 1
            else:
                chunk_tracker[l2_chunk_id]["rrf_score"] += rrf_score
                chunk_tracker[l2_chunk_id]["priority"] = 2

    out: List[Tuple[str, str, float, int]] = []
    
    # Step 5: flatten accumulated chunk metadata into sortable tuples
    for chunk_id, metadata in chunk_tracker.items():
        chunk_text, rrf_score, priority = metadata["text"], metadata["rrf_score"], metadata["priority"]
        out.append((chunk_id, chunk_text, rrf_score, priority))

    # Step 5: sort by highest RRF score first, then highest tie-break priority
    out = sorted(out, key = lambda x : (-x[2], -x[3]))

    # Step 6: return only the fused chunk identifier and text payload
    return [(chunk_id, chunk_text) for chunk_id, chunk_text, _, _ in out]
