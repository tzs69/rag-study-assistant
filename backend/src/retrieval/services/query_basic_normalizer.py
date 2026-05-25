from typing import List
import re

from ...shared.utils.clean_and_tokenize_text import normalize_query_token
from ..retrieval_types import NormalizedQuery


def basic_query_normalize(raw_query: str) -> NormalizedQuery:
    """
    Normalize a raw query into token-aligned query metadata reusable across retrieval flows.

    Pipeline:
     1) Split raw query into tokens by whitespace.
     2) Strip leading/trailing non-alphanumeric chars from each token
        (e.g., "the," -> "the", "in." -> "in").
     3) Normalize each cleaned token with normalize_query_token using the same
        filtering policy used by domain and base lexicon construction.
     4) Preserve original token order and spans for downstream reconstruction.

    Arg:
     - raw_query: raw user query string, may contain punctuation and mixed casing.
    """
    split_on_whitespace_pattern = re.compile(r"\S+")
    token_matches = list(split_on_whitespace_pattern.finditer(raw_query))
    tokens = [match.group(0) for match in token_matches]
    token_spans = [match.span() for match in token_matches]

    normalized_tokens: List[str | None] = []
    for token in tokens:
        token_cleaned = re.sub(r"^[^a-zA-Z0-9]+|[^a-zA-Z0-9]+$", "", token)
        token_normalized = normalize_query_token(token_cleaned)
        normalized_tokens.append(token_normalized)

    return NormalizedQuery(
        raw_query=raw_query,
        tokens=tokens,
        token_spans=token_spans,
        tokens_normalized=normalized_tokens,
    )

