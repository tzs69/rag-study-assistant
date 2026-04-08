import json
from typing import Any, Dict

from botocore.exceptions import ClientError
from .s3_base_store import BaseStore


def load_latest_pointer(
    *,
    base_store: BaseStore,
    pointer_key: str,
) -> Dict[str, Any]:
    """Load the BM25 pointer JSON object; fallback and return empty dict if missing."""
    try:
        response = base_store.s3.client.get_object(
            Bucket=base_store.bucket, 
            Key=pointer_key,
        )
        raw_bytes_payload = response["Body"].read()
        latest_pointer = json.loads(raw_bytes_payload.decode("utf-8"))

        if not isinstance(latest_pointer, dict):
            return {}
        
        return latest_pointer
    
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code")
        if code in ("NoSuchKey", "404"):
            return {}
        raise