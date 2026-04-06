from pathlib import PurePosixPath

def extract_doc_id_from_raw_key(raw_key: str, raw_prefix: str = "raws") -> str:
    """
    Extracts doc_id from raw S3 key by:
     - Stripping the raw prefix (e.g. "raws/") from the start of the key
     - Removing file extension from the end of the key
     - Returning the cleaned key as doc_id"

    sample input/output:
    - "raws/my-file.v1.pdf" -> "my-file.v1"
    """
    key = raw_key.strip().lstrip("/")
    prefix = f"{raw_prefix}/"
    if key.startswith(prefix):
        key = key[len(prefix):]

    name = PurePosixPath(key).name
    if "." in name:
        name = name.rsplit(".", 1)[0]
    return name
