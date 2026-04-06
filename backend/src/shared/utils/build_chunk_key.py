from pathlib import PurePosixPath


def build_chunks_jsonl_key(chunks_prefix, doc_id: str) -> str:
    """
    Build the S3 object key for a document's chunk JSONL artifact
    """
    doc_name = PurePosixPath(doc_id).stem
    if not doc_name:
        raise ValueError(f"Cannot derive document name from doc_id: {doc_id}")
    return f"{chunks_prefix}/{doc_name}_chunks.jsonl"