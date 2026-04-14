import re
from typing import List


def clean_and_tokenize_text(text) -> List[str]:
    """
    text cleaning and tokenization function to filter out irrelevant noise and retain potentially terms

    Given context of my project's dynamically changing kb and purpose of building the doc-tf dict (for spell correction), 
    filtering cannot be too strict and must be able to accomodate a wide variety of terms and abbreviations.
        - Filter layer 1: 
            - Keep all terms that contain at least one alphanumeric character
            - Terms with special chars '-' / '_' / '.' / '/' are allowed as long as the special chars 
                are not leading or trailing characters:
                - Allowed: "D.O.B", "9.9"
                - Not allowed: "lol.", ".10"
        - Filter layer 2:
            - Filter out all terms that only do not contain >=1 alphabet ([a-zA-Z])
    """

    matching_pattern = r"[a-z0-9]+(?:[._'/-][a-z0-9]+)*"

    text = text.lower()
    text = re.findall(matching_pattern, text)  
    text_filtered = [term for term in text if re.search(r'[a-z]', term)]
    return text_filtered