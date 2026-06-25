import os
from pathlib import Path
from pydantic import ConfigDict
from pydantic_settings import BaseSettings
from typing import Optional

ENV_FILE_PATH = Path(__file__).resolve().parent / ".env.local"
IS_LAMBDA_RUNTIME = bool(os.getenv("AWS_LAMBDA_FUNCTION_NAME"))

class Settings(BaseSettings):
    AWS_SSO_PROFILE: Optional[str] = None
    AWS_SSO_REGION: Optional[str] = None

    S3_GP_BUCKET_NAME: str 
    S3_GP_RAW_PREFIX: str  = "raws"
    S3_GP_CHUNK_PREFIX: str = "chunks"

    S3_VECTOR_BUCKET_NAME: str 
    S3_VECTOR_INDEX_NAME: str 

    DYNAMODB_MANIFEST_TABLE_NAME: str
    DYNAMODB_CORPUS_CHANGE_TABLE_NAME: str 
    DYNAMODB_COLLECTION_TERM_STATS_TABLE_NAME: str 
    DYNAMODB_DOC_TERM_STATS_TABLE_NAME: str 
    
    EMBEDDING_MODEL_ID: str 

    BM25_POINTER_KEY: str = "bm25/pointer.json"
    BM25_SNAPSHOT_KEY: str = "bm25/snapshot.json"

    model_config = ConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
    )

settings = Settings(_env_file=ENV_FILE_PATH if not IS_LAMBDA_RUNTIME and ENV_FILE_PATH.is_file() else None)
