from typing import Dict
from collections import Counter
from .document_reader_service import DocumentText
from ...shared.utils.clean_and_tokenize_text import clean_and_tokenize_text


def build_term_frequency_dict(doc_text: DocumentText) -> Dict[str, int]:
    """
    Takes in a document text (DocumentText object) and extracts terms and respective term frequencies.
    Returns a term - tf dictionary for the given document, where:
        - term: str
        - tf: int         
    """
    text_raw = doc_text.text
    text_filtered = clean_and_tokenize_text(text_raw)
    tf_dict = dict(Counter(text_filtered))
    return tf_dict
