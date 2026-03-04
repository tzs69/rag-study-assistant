import logging
from functools import lru_cache
from typing import Any, Dict, List

from ..session import get_aws_session


@lru_cache(maxsize=1)
def _get_bedrock_client():
    """Return a cached bedrock client using cached boto3 session"""
    session = get_aws_session()
    return session.client("bedrock-runtime")

class BedrockClient:
    """
    Reusable BedrockClient for  
    - Embeddings
    - Conversational Querys
    """
    def __init__(self, model_id):
        self.model_id = model_id
        self.client = _get_bedrock_client()
        