# Query Spell-Correction Plan (P2)

## Runtime Architecture (Latest)
- Query preprocessor is a function:
  - `preprocess_query(raw_query) -> ExtractedQuery`
  - no class initialization needed
- Spell corrector is a service class:
  - initialized once in retrieval orchestrator startup
  - loads base lexicon artifact once from `backend/src/retrieval/data/base_english_lexicon.json`
  - queries domain lexicon candidates from DynamoDB collection term stats table by prefix GSIs (`prefix1-index`, `prefix2-index`)
- Retrieval orchestrator owns spell-correction invocation:
  - feature flag `ENABLE_SPELL_CORRECTION` controls whether correction runs
  - if disabled, pass original query directly to retrieval
  - if enabled, run preprocess -> spell correct -> retrieval
  - if spell-correction fails, fallback to original query (do not fail request)

---

### 1) Build Base English Lexicon
- Source: `wordfreq.top_n_list("en", 10000)`
- Keep as a fallback lexicon for general English typo correction.

### 2) Build Query Preprocessor
For each incoming query:
1. Tokenize query by whitespace.
2. For each token, strip leading/trailing non-alphanumeric characters before normalization
   (example: `the, -> the`, `in. -> in`).
3. Normalize each cleaned token using `normalize_query_token` (same regex/alphabet gate policy as domain and base lexicon construction).
4. Build `ExtractedQuery`:
   - `raw_query`
   - `tokens`
   - `tokens_normalized` (per-position normalized token or `None`)
   - `pass_regex_gate` (normalized term -> list of positional indexes)
5. For each normalized token, run lexicon membership screening first:
   - If token exists in domain lexicon (`collection_term_stats`), keep unchanged.
   - Else if token exists in base lexicon, keep unchanged.
   - Else proceed to the 2-layer spell-correction pipeline.

---

## Spell-Correction Strategy (2 Layers)

### Layer 1: Domain Lexicon Correction
1. Filter candidate set from domain lexicon using prefix GSIs:
   - query `prefix2-index` when token length >= 2
   - fallback query `prefix1-index` when needed
2. Gate candidates by edit-distance threshold `X` (strict; initial default `X=1`).
3. For each remaining candidate, compute overall score:

```text
s(c | t) = w1 * edit_sim(t,c) + w2 * jaccard_bigram(t,c) + w3 * freq_score(c)
```

Where:
- `t` = input token, `c` = candidate
- `edit_sim(t,c)` = normalized edit similarity (higher is better)
- `jaccard_bigram(t,c)` = Jaccard similarity over character bigram sets:

```text
|Bigrams(t) ∩ Bigrams(c)| / |Bigrams(t) ∪ Bigrams(c)|
```

- `freq_score(c)` = domain frequency signal from lexicon stats (normalized)
4. Rank by descending score `s`.
5. If a valid high-confidence candidate exists, apply correction and continue to next token.
6. If no suitable candidate, move token to Layer 2.

### Layer 2: Base English Lexicon Correction
1. Filter candidate set from in-memory base lexicon prefix maps:
   - prefer `terms_by_prefix2` when token length >= 2
   - fallback to `terms_by_prefix1` when needed
2. Gate candidates by edit-distance threshold `Y` (more permissive; initial default `Y=2`).
3. Compute the same overall score:

```text
s(c | t)=w1*edit_sim(t,c)+w2*jaccard_bigram(t,c)+w3*freq_score(c)
```

- In this layer, `freq_score(c)` is based on `wordfreq.zipf_frequency`.
4. Rank by descending score `s`.
5. If a valid high-confidence candidate exists, apply correction.
6. Else leave token uncorrected.

---

## Threshold Policy (Initial)
- Domain threshold: `X = 1`
- Base threshold: `Y = 2`
- For short tokens (`len <= 4`): cap both layers to edit distance `<= 1` to reduce over-correction.

---

## Scoring and Decision Rules
- Normalize each component (`edit_sim`, `jaccard_bigram`, `freq_score`) before weighted sum.
- Tune weights `w1, w2, w3` empirically.
- Use confidence gating before auto-correct:
  - minimum top score threshold
  - minimum margin between top-1 and top-2 candidates
- If confidence is too low, do not auto-correct token.

---

## Initial Weight Priority (to tune)
- `w1` (edit similarity): highest
- `w2` (Jaccard bigram): medium
- `w3` (frequency score): medium-low

---

## Orchestrator Invocation Flow
1. Receive raw query in retrieval orchestrator.
2. Check feature flag:
   - if disabled: run retrieval on original query
   - if enabled: run spell-correction pipeline
3. Spell-correction pipeline:
   - `preprocess_query(raw_query)` to build `ExtractedQuery`
   - run spell corrector on gated tokens
   - reconstruct corrected query using token positions
4. Run retrieval with corrected query.
5. If any spell-correction error occurs, log and fallback to original query.
