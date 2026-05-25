from typing import List, Tuple
from nltk.util import ngrams

def build_term_features(term: str) -> Tuple[str, str | None, List[str]]:
    """Build deterministic per-term features used by retrieval spell-correction."""
    prefix1 = term[0]
    prefix2 = term[:2] if len(term) >= 2 else None
    bigrams = sorted({"".join(bigram) for bigram in ngrams(term, n=2)})
    return prefix1, prefix2, bigrams