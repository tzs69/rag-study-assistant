"""
Shared text normalization and token filtering utilities.

Given the context of a dynamically changing knowledge base and spell-correction use case,
filtering cannot be too strict and must accommodate a wide variety of terms and abbreviations.

Shared filtering policy used across domain lexicon build, base lexicon build, and query preprocessing:
    - Filter layer 1:
        - Keep all terms that contain at least one alphanumeric character
        - Terms with special chars '-' / '_' / '.' / '/' are allowed as long as the special chars
          are not leading or trailing characters:
            - Allowed: "D.O.B", "9.9"
            - Not allowed: "lol.", ".10"
    - Filter layer 2:
        - Filter out all terms that do not contain >=1 alphabet character ([a-zA-Z])
"""
import re
from typing import List


MATCHING_PATTERN = r"[a-z0-9]+(?:[._'/-][a-z0-9]+)*"

def clean_and_tokenize_text(text: str) -> List[str]:
    """
    Text cleaning and tokenization function to filter out irrelevant noise and retain useful terms.

    This function applies the shared filtering policy at text level:
        - lowercases full input text
        - extracts candidate tokens from free-form text using regex find-all
        - keeps only tokens that contain >=1 alphabet character

    Arg:
     - text: input text, can be multi-word text

    Returns:
     - list of normalized tokens
    """

    text = text.lower()
    text = re.findall(MATCHING_PATTERN, text)  
    text_filtered = [term for term in text if re.search(r'[a-z]', term)]
    return text_filtered


def normalize_query_token(query_token: str) -> str | None:
    """
    Normalize a single query token for spell-correction lookup.

    This function enforces the same shared filtering policy used for building both
    domain and base lexicons, but applies it at single-token level:
        - lowercases one query token
        - requires full-token regex match (no partial extraction)
        - requires >=1 alphabet character

    Arg: 
     - query_token: single word text only
    Returns:
     str | None:
     - normalized token when token passes full-match regex and alphabet gate
     - None otherwise.
    """
    candidate = query_token.lower()
    if not re.fullmatch(MATCHING_PATTERN, candidate):
        return None
    if not re.search(r"[a-z]", candidate):
        return None
    return candidate
