from typing import Dict, List

from ...retrieval_types import NormalizedQuery, SpellCorrectionQuery


def extract_for_spell_correction(normalized_query: NormalizedQuery) -> SpellCorrectionQuery:
    """
    Second stage query preprocessing function to build spell-correction-specific query metadata from a normalized query.

    Pipeline:
     1) Iterate through normalized tokens produced by basic_query_normalize.
     2) Track normalized terms that pass normalization (non-None) and map each
        term to its token positions.
     3) Return SpellCorrectionQuery with pass_regex_gate for token-level
        spell-correction candidate processing.

    Arg:
     - normalized_query: normalized token/spans payload from basic_query_normalize.
    """
    pass_regex_gate: Dict[str, List[int]] = {}

    for idx, token_normalized in enumerate(normalized_query.tokens_normalized):
        if token_normalized:
            if token_normalized in pass_regex_gate:
                pass_regex_gate[token_normalized].append(idx)
            else:
                pass_regex_gate[token_normalized] = [idx]

    return SpellCorrectionQuery(
        **normalized_query.__dict__,
        pass_regex_gate=pass_regex_gate,
    )

