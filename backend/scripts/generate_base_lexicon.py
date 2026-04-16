"""
Generate a precomputed base English lexicon artifact for query spell-correction.

What this script does:
1. Pulls the top-K English words from the wordfreq library.
2. Builds per-term metadata used in candidate filtering/scoring:
   - len, prefix1, prefix2, word_frequency, zipf_frequency, bigrams.
3. Applies the same normalization/filtering policy used by query/index preprocessing
   (via clean_and_tokenize_text) and drops terms that fail the policy.
4. Builds prefix-grouped lookup maps:
   - terms_by_prefix1: first-character -> list[term]
   - terms_by_prefix2: first-two-characters -> list[term]
5. Writes a JSON artifact to disk with readable indentation, while keeping
   term-list arrays (bigrams/prefix groups) collapsed onto single lines.

Output schema (high level):
{
  "terms": { "<term>": { ...metadata... } },
  "terms_by_prefix1": { "<p1>": ["..."] },
  "terms_by_prefix2": { "<p2>": ["..."] },
  "timestamp": "YYYY-MM-DD HH:MM:SS"
}

How to run the script:
 - In terminal(dir = project root), execute command "python -m backend.scripts.generate_base_lexicon"
"""

from nltk.util import ngrams
from wordfreq import word_frequency, zipf_frequency, top_n_list
from datetime import datetime
from typing import TypedDict
from logging import getLogger
from pathlib import Path
from ..src.shared.utils.clean_and_tokenize_text import clean_and_tokenize_text
import json
import logging
import re


K = 20000
LANGUAGE = "en"
BASE_LEXICON_OUT_FILE = "backend/src/retrieval/data/base_english_lexicon.json"

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = getLogger(__name__)


class TermMetadata(TypedDict):
    """Per-term features used in candidate filtering and scoring."""
    len: int
    prefix1: str
    prefix2: str | None
    word_frequency: float
    zipf_frequency: float
    bigrams: list[str]


TermsMap = dict[str, TermMetadata]
PrefixGroups = dict[str, list[str]]


class BaseLexiconArtifact(TypedDict, total=False):
    """Serialized base-lexicon artifact written by this script."""
    terms: TermsMap
    terms_by_prefix1: PrefixGroups
    terms_by_prefix2: PrefixGroups
    timestamp: str


def build_term_metadata() -> BaseLexiconArtifact:
    """
    Build per-term metadata for top-K words and apply token filtering.

    Returns:
        BaseLexiconArtifact: Dictionary containing a `terms` map:
        {
            "terms": {
                term_1: term_1_metadata,
                term_2: term_2_metadata,
                ...
            }
        }
    """
    top_k_terms = top_n_list(LANGUAGE, K)
    top_k_terms_sorted = sorted(top_k_terms)

    terms_dict: TermsMap = {}
    for term in top_k_terms_sorted:
        if term in terms_dict:
            continue
        bigrams = sorted({"".join(bigram) for bigram in ngrams(term, n=2)})
        terms_dict[term] = {
            "len": len(term),
            "prefix1": term[0],
            "prefix2": term[:2] if len(term) >= 2 else None,
            "word_frequency": word_frequency(term, LANGUAGE),
            "zipf_frequency": zipf_frequency(term, LANGUAGE),
            "bigrams": bigrams,
        }

    term_keys = list(terms_dict.keys())
    term_keys_astext = " ".join(term_keys)

    # Apply the same regex/token normalization used by domain lexicon build.
    term_keys_filtered = clean_and_tokenize_text(term_keys_astext)
    terms_to_drop = set(term_keys) - set(term_keys_filtered)
    logger.info(f"{len(terms_to_drop)} terms did not meet regex filtering criteria. Dropping...")

    terms_dict = {term: metadata for term, metadata in terms_dict.items() if term not in terms_to_drop}
    logger.info(f"{len(terms_dict)} terms remaining.")
    dict_out: BaseLexiconArtifact = {"terms": terms_dict}
    return dict_out


def build_grouped_by_prefix_list(dict_with_terms: BaseLexiconArtifact) -> BaseLexiconArtifact:
    """
    Add prefix-grouped lookup maps to an artifact containing terms.

    Args:
        dict_with_terms: Artifact with a non-empty terms key.

    Returns:
        BaseLexiconArtifact: The same dictionary object enriched with
        terms_by_prefix1 and terms_by_prefix2 (when non-empty).
    """
    if not dict_with_terms.get("terms", {}):
        logger.error("Trying to group terms by prefixes on an empty terms dict")
        raise ValueError("terms_dict is empty")

    terms_dict = dict_with_terms["terms"]
    terms_by_prefix1: PrefixGroups = {}
    terms_by_prefix2: PrefixGroups = {}

    for term, metadata in terms_dict.items():
        prefix1 = metadata.get("prefix1", "")
        if prefix1:
            if prefix1 not in terms_by_prefix1:
                terms_by_prefix1[prefix1] = [term]
            else:
                terms_by_prefix1[prefix1].append(term)

        prefix2 = metadata.get("prefix2", "")
        if prefix2:
            if prefix2 not in terms_by_prefix2:
                terms_by_prefix2[prefix2] = [term]
            else:
                terms_by_prefix2[prefix2].append(term)

    if terms_by_prefix1:
        dict_with_terms["terms_by_prefix1"] = terms_by_prefix1
        logger.info(f"{len(terms_by_prefix1)} unique prefixes (prefix1) collected")
    if terms_by_prefix2:
        dict_with_terms["terms_by_prefix2"] = terms_by_prefix2
        logger.info(f"{len(terms_by_prefix2)} unique prefixes (prefix2) collected")

    return dict_with_terms


def main() -> None:
    """Run the full base-lexicon build pipeline and write output JSON to disk."""
    logger.info("=" * 60)
    logger.info("Running Base Lexicon JSON Generation Script")
    logger.info("=" * 60)

    logger.info("1. Extracting term metadata...")
    base_lexicon_dict = build_term_metadata()
    logger.info("Term metadata extracted successfully")

    logger.info("2. Grouping terms by prefixes...")
    base_lexicon_dict = build_grouped_by_prefix_list(base_lexicon_dict)
    logger.info("Terms by prefix lists built successfully")

    logger.info("3. Adding timestamp...")
    current_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    base_lexicon_dict["timestamp"] = current_timestamp
    logger.info("Timestamp added successfully")

    logger.info("4. Writing to disk...")

    # Convert the artifact to JSON and collapse contained arrays (usually multiline)
    # into single lines for better readability.
    text = json.dumps(base_lexicon_dict, indent=4, ensure_ascii=False)

    # 1) Collapse "bigrams": [ ... ]
    text = re.sub(
        r'("bigrams"\s*:\s*)\[(.*?)\]',
        lambda m: m.group(1) + "[" + " ".join(m.group(2).split()) + "]",
        text,
        flags=re.S,
    )

    def _collapse_group_block(match: re.Match[str]) -> str:
        """Collapse all JSON arrays inside a matched prefix-group block into one line."""
        block = match.group(0)
        return re.sub(
            r'(:\s*)\[(.*?)\]',
            lambda m: m.group(1) + "[" + " ".join(m.group(2).split()) + "]",
            block,
            flags=re.S,
        )
    
    # 2) Collapse lists inside terms_by_prefix1 / terms_by_prefix2 blocks
    terms_by_prefix_lists = ["terms_by_prefix1", "terms_by_prefix2"]
    for terms_by_prefix_list in terms_by_prefix_lists:
        text = re.sub(
            rf'"{terms_by_prefix_list}"\s*:\s*\{{.*?\}}\s*,?',
            _collapse_group_block,
            text,
            flags=re.S,
        )

    base_lexicon_out_file_path = Path(BASE_LEXICON_OUT_FILE)
    base_lexicon_out_file_path.parent.mkdir(parents=True, exist_ok=True)
    with base_lexicon_out_file_path.open("w") as f:
        f.write(text)

    logger.info("Base Lexicon Dict wrote to disk successfully.")

    logger.info("=" * 60)
    logger.info("Base Lexicon Generation Script Execution Completed")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
    
