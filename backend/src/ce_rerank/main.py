from typing import List, Set, Tuple

import numpy as np
from fastapi import FastAPI, HTTPException
from sentence_transformers import CrossEncoder

app = FastAPI()
reranker_model = CrossEncoder("Alibaba-NLP/gte-reranker-modernbert-base")


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/rerank")
def rerank(qa_pairs: List[Tuple[str, str]]):

    # Input validation
    _validate_rerank_input(qa_pairs)

    scores = reranker_model.predict(qa_pairs)

    # Output validation
    _validate_rerank_output(len(qa_pairs), scores)

    # Convert from numpy array to list of python float objects and return json dict
    scores = [float(score) for score in scores]
    return {
        "ok": True,
        "scores_list": scores
    }


def _validate_rerank_input(qa_pairs: List[Tuple[str, str]]):

    if not qa_pairs:
        raise HTTPException(status_code=400, detail="empty query-answer pairs detected")

    if not isinstance(qa_pairs, list):
        raise HTTPException(status_code=400, detail="malformed input: query-answer pairs for reranking not in list structure")

    # Initialize for single-query only check
    queries: Set = set()

    for qa_pair in qa_pairs:
        qa_pair_valid: bool = (
            (isinstance(qa_pair, tuple) or isinstance(qa_pair, list))
            and len(qa_pair) == 2
            and isinstance(qa_pair[0], str)
            and isinstance(qa_pair[1], str)
        )
        if not qa_pair_valid:
            raise HTTPException(status_code=400, detail="detected invalid format query-answer pair instance")

        query = qa_pair[0].strip()
        if len(query) > 0 and query not in queries:
            queries.add(query)

    # Final check: queries should only contain 1 item after checking through all qa pairs
    if len(queries) == 0:
        raise HTTPException(status_code=400, detail="no nonempty query detected")
    if len(queries) > 1:
        raise HTTPException(status_code=400, detail="multiple different queries detected")


def _validate_rerank_output(input_list_len: int, rerank_scores_output):

    if not isinstance(rerank_scores_output, np.ndarray):
        raise HTTPException(status_code=500, detail="malformed output: reranking scores not in numpy array structure")

    if rerank_scores_output.ndim != 1:
        raise HTTPException(status_code=500, detail="malformed output: reranking scores must be a 1D array")

    if rerank_scores_output.size == 0:
        raise HTTPException(status_code=500, detail="empty reranking output detected")

    if len(rerank_scores_output) != input_list_len:
        raise HTTPException(status_code=500, detail="malformed output: reranking scores count does not match input list length")

    if not np.issubdtype(rerank_scores_output.dtype, np.number):
        raise HTTPException(status_code=500, detail="malformed output: reranking scores must be numeric")

    if not np.isfinite(rerank_scores_output).all():
        raise HTTPException(status_code=500, detail="malformed output: reranking scores contain non-finite values")
