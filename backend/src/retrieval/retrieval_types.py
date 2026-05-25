from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class NormalizedQuery:
    raw_query: str
    tokens: List[str]
    token_spans: List[Tuple[int, int]]
    tokens_normalized: List[str | None]


@dataclass(frozen=True)
class SpellCorrectionQuery(NormalizedQuery):
    pass_regex_gate: Dict[str, List[int]]


@dataclass(frozen=True)
class QueryCorrectionResult:
    original_query: str
    corrected_query: str
    used_spell_correction: bool
    num_tokens_corrected: int = 0
    token_corrections: List[Dict[str, Any]] = field(default_factory=list)
