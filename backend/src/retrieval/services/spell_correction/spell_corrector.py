from pathlib import Path
from typing import Any, Dict, List, Literal, Tuple
from ...retrieval_types import QueryCorrectionResult, SpellCorrectionQuery
from ....shared.services.domain_lexicon_store import DomainLexiconReader
from ....shared.utils.build_term_features import build_term_features
from Levenshtein import distance as lev_dist
import json
import math

DEFAULT_BASE_ENGLISH_LEXICON_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "base_english_lexicon.json"
)
LAYER_1_EDIT_DIST_THRESHOLD=2
EDIT_DIST_THRESHOLD_SHORT_TOKEN=2
LAYER_2_EDIT_DIST_THRESHOLD=3

JACCARD_FLOOR = 0.2
JACCARD_FLOOR_SHORT_TOKEN = 0.3

LAYER_1_CONFIDENCE_FLOOR = 0.65
LAYER_1_CONFIDENCE_FLOOR_SHORT_TOKEN = 0.70

LAYER_1_MIN_TOP1_TOP2_MARGIN = 0.0 # 0.03
LAYER_1_MIN_TOP1_TOP2_MARGIN_SHORT_TOKEN = 0.0 # 0.07

LAYER_2_CONFIDENCE_FLOOR = 0.65
LAYER_2_CONFIDENCE_FLOOR_SHORT_TOKEN = 0.70

LAYER_2_MIN_TOP1_TOP2_MARGIN = 0.0 # 0.08
LAYER_2_MIN_TOP1_TOP2_MARGIN_SHORT_TOKEN = 0.0 # 0.12

# Scoring hyperparameters
W1 = 0.58 # Edit distance score weight
W2 = 0.40 # Bigram Jaccard similarity score weight
W3 = 0.02 # Domain/Base frequency score weight

# Minimal latency guards
MAX_OOV_TOKENS_TO_CORRECT = 12
MAX_DOMAIN_CANDIDATES = 1000
MAX_BASE_CANDIDATES = 2000

class SpellCorrector:



    def __init__(self, 
        collection_term_stats_table_name: str,
        prefix1_gsi_name: str = "prefix1-index",
        prefix2_gsi_name: str = "prefix2-index",
        base_english_lexicon_path: Path | None = None
        ):
        self.domain_lexicon_reader = DomainLexiconReader(
            collection_term_stats_table_name=collection_term_stats_table_name,
            prefix1_gsi_name=prefix1_gsi_name,
            prefix2_gsi_name=prefix2_gsi_name
        )

        # Load base english lexicon from disk into memory as a dict for fast lookups
        self.base_english_lexicon_path = (
            (base_english_lexicon_path if base_english_lexicon_path else DEFAULT_BASE_ENGLISH_LEXICON_PATH)
            .resolve()
        )
        if not self.base_english_lexicon_path.is_file():
            raise FileNotFoundError(f"Base English lexicon file not found at: {self.base_english_lexicon_path}")
        self.base_english_lexicon = self._init_base_lexicon(self.base_english_lexicon_path)
        

    def _init_base_lexicon(self, base_english_lexicon_path: Path) -> Dict[str, Any]:
        """
        Helper function to load base english lexicon from base_english_lexicon_path upon init

        Process:
         1) Reads base_english_lexicon_path and loads base_english_lexicon dict
         2) Validates dict schema by checking that all required top-level keys are present in base_english_lexicon
             and each corresponding value is a dict
         3) Returns base_english_lexicon upon schema validation
        """

        # Read input filepath and load base_english_lexicon
        try:
            with open(base_english_lexicon_path, "r", encoding="utf-8") as f:
                base_english_lexicon = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Malformed JSON in base lexicon file: {self.base_english_lexicon_path}"
            ) from e

        # Validate required top-level keys and ensure each maps to a dict
        required_top_level_keys = ("terms", "terms_by_prefix1", "terms_by_prefix2")
        for key in required_top_level_keys:
            value = base_english_lexicon.get(key)
            if not isinstance(value, dict):
                raise ValueError(
                    f"Invalid base lexicon schema at {self.base_english_lexicon_path}: "
                    f"missing or non-dict key '{key}'"
                )
        
        return base_english_lexicon
    

    def _validate_extracted_query_payload(self, extracted_query: SpellCorrectionQuery) -> None:
        """
        Helper function to validate input ExtractedQuery payload into spell_correct_extracted_query
        
        Validation checklist:
         1) raw_query type:
             - must be a string

         2) tokens payload:
             - tokens must be a list
             - every item in tokens must be a string

         3) tokens_normalized payload:
             - tokens_normalized must be a list
             - tokens_normalized must have the same length as tokens
             - every item must be either string or None

         4) token_spans payload:
             - token_spans must be a list
             - token_spans must have the same length as tokens
             - each item must be a 2-int tuple (start, end)
             - each span must be valid in raw_query bounds
             - each span substring must match the corresponding token
             - spans must be monotonic and non-overlapping

         5) pass_regex_gate payload:
             - pass_regex_gate must be a dict
             - each key must be a non-empty normalized token string
             - each value must be a non-empty list of integer positions

         6) position integrity:
             - every index in pass_regex_gate must be within token bounds
             - for each key and index list, tokens_normalized[index] must equal that key

        Raises:
        - ValueError when any of the above checks fail
        """
        # raw query must remain the original user input string
        if not isinstance(extracted_query.raw_query, str):
            raise ValueError("Invalid ExtractedQuery: raw_query must be a string")

        # tokens must be a list of original token strings
        if not isinstance(extracted_query.tokens, list):
            raise ValueError("Invalid ExtractedQuery: tokens must be a list")
        if not all(isinstance(token, str) for token in extracted_query.tokens):
            raise ValueError("Invalid ExtractedQuery: every token must be a string")

        # normalized tokens must align 1:1 with tokens for deterministic reconstruction
        if not isinstance(extracted_query.tokens_normalized, list):
            raise ValueError("Invalid ExtractedQuery: tokens_normalized must be a list")
        if len(extracted_query.tokens) != len(extracted_query.tokens_normalized):
            raise ValueError("Invalid ExtractedQuery: tokens and tokens_normalized must have equal length")
        if not all(
            (normalized is None or isinstance(normalized, str))
            for normalized in extracted_query.tokens_normalized
        ):
            raise ValueError("Invalid ExtractedQuery: tokens_normalized values must be string or None")

        # token spans must align with raw query tokenization and preserve exact token boundaries
        if not isinstance(extracted_query.token_spans, list):
            raise ValueError("Invalid ExtractedQuery: token_spans must be a list")
        if len(extracted_query.tokens) != len(extracted_query.token_spans):
            raise ValueError("Invalid ExtractedQuery: tokens and token_spans must have equal length")
        raw_len = len(extracted_query.raw_query)
        last_end = -1
        for idx, span in enumerate(extracted_query.token_spans):
            if (
                not isinstance(span, tuple)
                or len(span) != 2
                or not isinstance(span[0], int)
                or not isinstance(span[1], int)
            ):
                raise ValueError("Invalid ExtractedQuery: each token_spans item must be a tuple[int, int]")
            start, end = span
            if not (0 <= start < end <= raw_len):
                raise ValueError("Invalid ExtractedQuery: token_spans entry out of raw_query bounds")
            if start < last_end:
                raise ValueError("Invalid ExtractedQuery: token_spans must be non-overlapping and sorted")
            if extracted_query.raw_query[start:end] != extracted_query.tokens[idx]:
                raise ValueError("Invalid ExtractedQuery: token_spans do not match tokens")
            last_end = end

        # pass_regex_gate must map normalized token -> list of token positions
        if not isinstance(extracted_query.pass_regex_gate, dict):
            raise ValueError("Invalid ExtractedQuery: pass_regex_gate must be a dict")

        max_index = len(extracted_query.tokens) - 1
        for normalized_token, positions in extracted_query.pass_regex_gate.items():
            # each regex-passed key must be a non-empty normalized token string
            if not isinstance(normalized_token, str) or not normalized_token:
                raise ValueError("Invalid ExtractedQuery: pass_regex_gate keys must be non-empty strings")
            # each key must map to at least one position index
            if not isinstance(positions, list) or not positions:
                raise ValueError("Invalid ExtractedQuery: each pass_regex_gate value must be a non-empty list")
            # position indexes must be integers
            if not all(isinstance(idx, int) for idx in positions):
                raise ValueError("Invalid ExtractedQuery: pass_regex_gate positions must be ints")
            # every position must be within token bounds
            if not all(0 <= idx <= max_index for idx in positions):
                raise ValueError("Invalid ExtractedQuery: pass_regex_gate index out of range")
            # mapped normalized token must match tokens_normalized at each referenced index
            if not all(extracted_query.tokens_normalized[idx] == normalized_token for idx in positions):
                raise ValueError(
                    "Invalid ExtractedQuery: pass_regex_gate term does not match tokens_normalized at one or more positions"
                )


    def spell_correct_extracted_query(self, extracted_query: SpellCorrectionQuery) -> QueryCorrectionResult:
        """
        Spell-correct a preprocessed query payload and return a correction result.

        Intended workflow for implementation:
         1) Validate extracted_query payload shape and index consistency.
         2) Iterate over regex-gated normalized tokens from pass_regex_gate.
         3) For each token, run lexicon membership screening first:
             - if token exists in domain lexicon, keep unchanged
             - else if token exists in base lexicon, keep unchanged
             - else proceed to correction layers
         4) Layer 1 domain correction:
             - fetch domain candidates by prefix
               - prefer prefix2 query for token length >= 2
               - fallback to prefix1 query when needed
             - gate by edit-distance threshold X
             - score each candidate:
               score = w1 * edit_sim + w2 * jaccard_bigram + w3 * freq_score
             - apply confidence checks (top score and top1-top2 margin)
             - if accepted, use candidate and continue
         5) Layer 2 base correction if Layer 1 did not produce accepted candidate:
             - fetch candidates from in-memory base prefix maps
               - prefer prefix2 bucket for token length >= 2
               - fallback to prefix1 bucket
             - gate by edit-distance threshold Y
             - score with same formula, where freq_score uses base lexicon frequency signal
             - apply same confidence checks
         6) Reconstruct corrected query using token positions.
         7) Return QueryCorrectionResult.

        Notes:
         - For short tokens (length <= 4), cap both layers to edit distance <= 1.
         - If no candidate passes confidence gates, keep original token unchanged.
         - This method should fail safe and fallback to original query on unexpected errors.

        Example ExtractedQuery payload:
        ExtractedQuery(
            raw_query="I want to eat all of the 69, bread in. the world",
            tokens=["I", "want", "to", "eat", "all", "of", "the", "69,", "bread", "in.", "the", "world"],
            token_spans=[(0, 1), (2, 6), (7, 9), (10, 13), (14, 17), (18, 20), (21, 24), (25, 28), (29, 34), (35, 38), (39, 42), (43, 48)],
            tokens_normalized=["i", "want", "to", "eat", "all", "of", "the", "", "bread", "in", "the", "world"],
            pass_regex_gate={
                "i": [0],
                "want": [1],
                "to": [2],
                "eat": [3],
                "all": [4],
                "of": [5],
                "the": [6, 10],
                "bread": [8],
                "in": [9],
                "world": [11]
            }
        )
        """
        self._validate_extracted_query_payload(extracted_query)
        corrected_tokens = list(extracted_query.tokens)
        token_corrections: List[Dict[str, Any]] = []
        num_tokens_corrected = 0
        num_oov_tokens_processed = 0

        # Per-request caches to reduce repeated remote lookups
        contains_term_cache: Dict[str, bool] = {}
        domain_prefix_cache: Dict[Tuple[bool, str], Dict[str, Dict[str, Any]]] = {}
        base_terms_map: Dict[str, Dict[str, Any]] = self.base_english_lexicon.get("terms", {})
        base_prefix1_map: Dict[str, List[str]] = self.base_english_lexicon.get("terms_by_prefix1", {})
        base_prefix2_map: Dict[str, List[str]] = self.base_english_lexicon.get("terms_by_prefix2", {})

        for token, positional_indices in extracted_query.pass_regex_gate.items():

            # Fast local membership screening first
            if token in base_terms_map:
                continue

            # Remote membership screening with request-level cache
            if token not in contains_term_cache:
                contains_term_cache[token] = self.domain_lexicon_reader.contains_term(term=token)
            if contains_term_cache[token]:
                continue

            num_oov_tokens_processed += 1
            if num_oov_tokens_processed > MAX_OOV_TOKENS_TO_CORRECT:
                continue

            # Token OOV wrt domain and base lexicons
            # Build term prefixes and bigrams to prepare for spell correction
            token_prefix1, token_prefix2, token_bigrams = build_term_features(term=token)

            # Fetch domain candidates by prefix2 first
            starts_with_token_prefix_domain: Dict[str, Dict[str, Any]] = {}
            if token_prefix2:
                cache_key = (False, token_prefix2)
                if cache_key not in domain_prefix_cache:
                    domain_prefix_cache[cache_key] = self.domain_lexicon_reader.query_on_prefix(
                        prefix_val=token_prefix2,
                        prefix1=False,
                    )
                starts_with_token_prefix_domain = domain_prefix_cache[cache_key]

            # If initial fetch does not yield any results or token does not have prefix2, fall back and fetch by prefix1
            if not starts_with_token_prefix_domain:
                cache_key = (True, token_prefix1)
                if cache_key not in domain_prefix_cache:
                    domain_prefix_cache[cache_key] = self.domain_lexicon_reader.query_on_prefix(
                        prefix_val=token_prefix1,
                        prefix1=True,
                    )
                starts_with_token_prefix_domain = domain_prefix_cache[cache_key]

            # Candidates found, attempt layer 1 spell correction
            if starts_with_token_prefix_domain:

                candidates_to_rank: List[Tuple[str, float]] = []
                gated_candidates: Dict[str, Dict[str, Any]] = {}

                # First pass: calculate edit dist, sim scores and filter out candidates that exceed/do not meet thresholds
                for candidate, candidate_metadata in list(starts_with_token_prefix_domain.items())[:MAX_DOMAIN_CANDIDATES]:
                    
                    edit_dist = lev_dist(token, candidate)
                    if len(token) <= 4:
                        if edit_dist > EDIT_DIST_THRESHOLD_SHORT_TOKEN:
                            continue
                    else:
                        if edit_dist > LAYER_1_EDIT_DIST_THRESHOLD:
                            continue
                    edit_sim = 1 - (edit_dist / max(len(token), len(candidate), 1))
                    candidate_metadata["edit_sim"] = edit_sim

                    candidate_bigrams = candidate_metadata.get("bigrams", [])
                    jaccard_score = self._jaccard_similarity(token_bigrams, candidate_bigrams)
                    if len(token) <= 4:
                        if jaccard_score < JACCARD_FLOOR_SHORT_TOKEN:
                            continue
                    else:
                        if jaccard_score < JACCARD_FLOOR:
                            continue
                    candidate_metadata["jaccard_score"] = jaccard_score

                    candidate_df = candidate_metadata.get("doc_freq", 0)
                    if not candidate_df:
                        continue

                    gated_candidates[candidate] = candidate_metadata

                # Layer 1 batched frequency scoring: freq_raw = log1p(df) + 0.5 * log1p(collection_tf)
                # then min-max normalize across gated candidates.
                self._compute_domain_frequency_scores(gated_candidates)
                
                # Second pass: compute weighted overall score and rank.
                for candidate, candidate_metadata in gated_candidates.items():
                    edit_sim = candidate_metadata.get("edit_sim", 0.0)
                    jaccard_score = candidate_metadata.get("jaccard_score")
                    freq_score = candidate_metadata.get("freq_score")
                    overall_candidate_score = W1 * edit_sim + W2 * jaccard_score + W3 * freq_score
                    candidates_to_rank.append((candidate, overall_candidate_score))

                candidates_sorted = sorted(candidates_to_rank, key=lambda x: x[1], reverse=True)
                accepted, accepted_candidate, accepted_score = self._accept_layer_x_candidate(1, candidates_sorted, len(token))
                if accepted:
                    original_tokens = [corrected_tokens[idx] for idx in positional_indices]
                    for idx in positional_indices:
                        corrected_tokens[idx] = accepted_candidate

                    token_corrections.append(
                        {
                            "normalized_token": token,
                            "original_tokens": original_tokens,
                            "corrected_token": accepted_candidate,
                            "positions": positional_indices,
                            "layer": "domain",
                            "score": accepted_score,
                        }
                    )
                    num_tokens_corrected += len(positional_indices)
                    continue
            
            # Layer 1 spell correction results unsatisfactory; attempting layer 2 spell correction (with base lexicon)

            # Layer 2 attempt A: prefix2 candidates (when available)
            layer2_accepted = False
            layer2_candidate: str | None = None
            layer2_score = 0.0

            starts_with_token_prefix_base_p2: List[str] = []
            if token_prefix2:
                starts_with_token_prefix_base_p2 = base_prefix2_map.get(token_prefix2, [])

            if starts_with_token_prefix_base_p2:
                candidates_to_rank: List[Tuple[str, float]] = []
                gated_candidates: Dict[str, Dict[str, Any]] = {}

                for candidate in starts_with_token_prefix_base_p2[:MAX_BASE_CANDIDATES]:
                    candidate_metadata = base_terms_map.get(candidate)
                    if not isinstance(candidate_metadata, dict):
                        continue

                    edit_dist = lev_dist(token, candidate)
                    if len(token) <= 4:
                        if edit_dist > EDIT_DIST_THRESHOLD_SHORT_TOKEN:
                            continue
                    else:
                        if edit_dist > LAYER_2_EDIT_DIST_THRESHOLD:
                            continue

                    edit_sim = 1 - (edit_dist / max(len(token), len(candidate), 1))
                    candidate_bigrams = candidate_metadata.get("bigrams", [])
                    jaccard_score = self._jaccard_similarity(token_bigrams, candidate_bigrams)
                    if len(token) <= 4:
                        if jaccard_score < JACCARD_FLOOR_SHORT_TOKEN:
                            continue
                    else:
                        if jaccard_score < JACCARD_FLOOR:
                            continue

                    gated_candidates[candidate] = {
                        "edit_sim": edit_sim,
                        "jaccard_score": jaccard_score,
                        "zipf_frequency": float(candidate_metadata.get("zipf_frequency", 0.0) or 0.0),
                    }

                self._compute_base_frequency_scores(gated_candidates)

                for candidate, candidate_metadata in gated_candidates.items():
                    edit_sim = candidate_metadata.get("edit_sim", 0.0)
                    jaccard_score = candidate_metadata.get("jaccard_score", 0.0)
                    freq_score = candidate_metadata.get("freq_score", 0.0)
                    overall_candidate_score = W1 * edit_sim + W2 * jaccard_score + W3 * freq_score
                    candidates_to_rank.append((candidate, overall_candidate_score))

                candidates_sorted = sorted(candidates_to_rank, key=lambda x: x[1], reverse=True)
                layer2_accepted, layer2_candidate, layer2_score = self._accept_layer_x_candidate(2, candidates_sorted, len(token))

            # Layer 2 attempt B: fallback to prefix1 when prefix2 attempt did not accept
            if not layer2_accepted:
                starts_with_token_prefix_base_p1 = base_prefix1_map.get(token_prefix1, [])
                if starts_with_token_prefix_base_p1:
                    candidates_to_rank = []
                    gated_candidates = {}

                    for candidate in starts_with_token_prefix_base_p1[:MAX_BASE_CANDIDATES]:
                        candidate_metadata = base_terms_map.get(candidate)
                        if not isinstance(candidate_metadata, dict):
                            continue

                        edit_dist = lev_dist(token, candidate)
                        if len(token) <= 4:
                            if edit_dist > EDIT_DIST_THRESHOLD_SHORT_TOKEN:
                                continue
                        else:
                            if edit_dist > LAYER_2_EDIT_DIST_THRESHOLD:
                                continue

                        edit_sim = 1 - (edit_dist / max(len(token), len(candidate), 1))
                        candidate_bigrams = candidate_metadata.get("bigrams", [])
                        jaccard_score = self._jaccard_similarity(token_bigrams, candidate_bigrams)
                        if len(token) <= 4:
                            if jaccard_score < JACCARD_FLOOR_SHORT_TOKEN:
                                continue
                        else:
                            if jaccard_score < JACCARD_FLOOR:
                                continue

                        gated_candidates[candidate] = {
                            "edit_sim": edit_sim,
                            "jaccard_score": jaccard_score,
                            "zipf_frequency": float(candidate_metadata.get("zipf_frequency", 0.0) or 0.0),
                        }

                    self._compute_base_frequency_scores(gated_candidates)

                    for candidate, candidate_metadata in gated_candidates.items():
                        edit_sim = candidate_metadata.get("edit_sim", 0.0)
                        jaccard_score = candidate_metadata.get("jaccard_score", 0.0)
                        freq_score = candidate_metadata.get("freq_score", 0.0)
                        overall_candidate_score = W1 * edit_sim + W2 * jaccard_score + W3 * freq_score
                        candidates_to_rank.append((candidate, overall_candidate_score))

                    candidates_sorted = sorted(candidates_to_rank, key=lambda x: x[1], reverse=True)
                    layer2_accepted, layer2_candidate, layer2_score = self._accept_layer_x_candidate(2, candidates_sorted, len(token))

            if layer2_accepted:
                original_tokens = [corrected_tokens[idx] for idx in positional_indices]
                for idx in positional_indices:
                    corrected_tokens[idx] = layer2_candidate

                token_corrections.append(
                    {
                        "normalized_token": token,
                        "original_tokens": original_tokens,
                        "corrected_token": layer2_candidate,
                        "positions": positional_indices,
                        "layer": "base",
                        "score": layer2_score,
                    }
                )
                num_tokens_corrected += len(positional_indices)
                continue

        used_spell_correction = num_tokens_corrected > 0
        corrected_query = (
            self._reconstruct_query_from_spans(
                raw_query=extracted_query.raw_query,
                corrected_tokens=corrected_tokens,
                token_spans=extracted_query.token_spans,
            )
            if used_spell_correction
            else extracted_query.raw_query
        )

        return QueryCorrectionResult(
            original_query=extracted_query.raw_query,
            corrected_query=corrected_query,
            used_spell_correction=used_spell_correction,
            num_tokens_corrected=num_tokens_corrected,
            token_corrections=token_corrections,
        )


    def _reconstruct_query_from_spans(
        self,
        raw_query: str,
        corrected_tokens: List[str],
        token_spans: List[Tuple[int, int]],
    ) -> str:
        """
        Rebuild query text by patching corrected tokens into original raw_query token spans.
        
        Example I/O:
            Input:
                raw_query = "I like, to eat bannnas",
                tokens = ["I", "like,", "to", "eat", "bannnas"],
                token_spans = [
                    (0, 1),   # "I"
                    (2, 7),   # "like,"
                    (8, 10),  # "to"
                    (11, 14), # "eat"
                    (15, 22)  # "bannnas"
                ],
                corrected_tokens = ["I", "like", "to", "eat", "bananas"]

            Output:
                corrected_query = "I like to eat bananas"
        """
        if not corrected_tokens or not token_spans:
            return raw_query

        parts: List[str] = []
        cursor = 0

        for idx, (start, end) in enumerate(token_spans):
            parts.append(raw_query[cursor:start])
            parts.append(corrected_tokens[idx])
            cursor = end

        parts.append(raw_query[cursor:])
        return "".join(parts)

    
    def _compute_domain_frequency_scores(
        self,
        candidates: Dict[str, Dict[str, Any]],
    ) -> None:
        """
        Compute bounded Layer 1 domain frequency score from doc_freq and collection_tf.

        Raw score:
         - log1p(doc_freq) + 0.5 * log1p(collection_tf)
        Normalization:
         - min-max across candidate set to [0, 1]
        """
        if not candidates:
            return

        raw_scores: Dict[str, float] = {}
        for candidate, metadata in candidates.items():
            df = int(metadata.get("doc_freq", 0) or 0)
            cf = int(metadata.get("collection_tf", 0) or 0)
            raw_scores[candidate] = math.log1p(max(df, 0)) + 0.5 * math.log1p(max(cf, 0))

        min_raw = min(raw_scores.values())
        max_raw = max(raw_scores.values())
        denom = (max_raw - min_raw) + 1e-9

        for candidate, raw in raw_scores.items():
            candidates[candidate]["freq_score"] = (raw - min_raw) / denom


    def _compute_base_frequency_scores(
        self,
        candidates: Dict[str, Dict[str, Any]],
    ) -> None:
        """Compute min-max normalized frequency scores for candidates obtained from layer 2"""
        if not candidates:
            return

        raw_scores: Dict[str, float] = {}
        for candidate, metadata in candidates.items():
            raw_scores[candidate] = float(metadata.get("zipf_frequency", 0.0) or 0.0)

        min_raw = min(raw_scores.values())
        max_raw = max(raw_scores.values())
        denom = (max_raw - min_raw) + 1e-9

        for candidate, raw in raw_scores.items():
            candidates[candidate]["freq_score"] = (raw - min_raw) / denom


    def _accept_layer_x_candidate(
        self,
        layer: Literal[1, 2], 
        candidates_sorted: List[Tuple[str, float]],
        token_len: int,
    ) -> Tuple[bool, str | None, float]:
        """
        Helper function to assess candidates list outputted from a spell correction layer,
        obtain top-scoring candidate and apply margin checking and confidence floor filtering/gating 
        on it before acceptance and output.

         - Applies different threshold levels for different layers inside the spell correction function
        """
        if not candidates_sorted:
            return False, None, 0.0

        # Get top candidate and calculate score difference between it and the next best candidate (if exists)
        top1_candidate, top1_score = candidates_sorted[0]
        top2_score = candidates_sorted[1][1] if len(candidates_sorted) > 1 else 0.0
        margin = top1_score - top2_score

        # Apply confidence gating filter to top 1 candidate
        # For shorter tokens (len <= 4), apply stricter score and margin filtering thresholds
        if token_len <= 4:
            if layer == 1:
                accepted = (
                    top1_score >= LAYER_1_CONFIDENCE_FLOOR_SHORT_TOKEN
                    and margin >= LAYER_1_MIN_TOP1_TOP2_MARGIN_SHORT_TOKEN
                )
            else:
                accepted = (
                    top1_score >= LAYER_2_CONFIDENCE_FLOOR_SHORT_TOKEN
                    and margin >= LAYER_2_MIN_TOP1_TOP2_MARGIN_SHORT_TOKEN
                )
        else:
            if layer == 1:
                accepted = (
                    top1_score >= LAYER_1_CONFIDENCE_FLOOR
                    and margin >= LAYER_1_MIN_TOP1_TOP2_MARGIN
                )
            else:
                accepted = (
                    top1_score >= LAYER_2_CONFIDENCE_FLOOR
                    and margin >= LAYER_2_MIN_TOP1_TOP2_MARGIN
                )
        return accepted, (top1_candidate if accepted else None), top1_score


    def _jaccard_similarity(self, bigrams_list_1: List[str], bigrams_list_2: List[str]) -> float:
        """
        Helper function to compute Jaccard Similarity score for spell correction candidate ranking
        
        jaccard score = |X ∩ Y| / |X ∪ Y|
        """
        bigrams_set_1 = set(bigrams_list_1)
        bigrams_set_2 = set(bigrams_list_2)

        intersection = bigrams_set_1 & bigrams_set_2
        union = bigrams_set_1 | bigrams_set_2

        if len(union) == 0:
            return 0.0

        return len(intersection)/len(union)
