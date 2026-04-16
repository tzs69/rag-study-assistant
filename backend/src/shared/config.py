import os
from pathlib import Path
from typing import Optional
from pydantic import ConfigDict
from pydantic_settings import BaseSettings

ENV_FILE_PATH = Path(__file__).resolve().parent / ".env.local"
IS_LAMBDA_RUNTIME = bool(os.getenv("AWS_LAMBDA_FUNCTION_NAME"))

class Settings(BaseSettings):
    AWS_SSO_PROFILE: Optional[str] = None
    AWS_SSO_REGION: Optional[str] = None

    S3_GP_BUCKET_NAME: Optional[str] = None
    S3_GP_RAW_PREFIX: Optional[str] = None
    S3_GP_CHUNK_PREFIX: Optional[str] = None

    DYNAMODB_CORPUS_CHANGE_TABLE_NAME: Optional[str] = None
    DYNAMODB_COLLECTION_TERM_STATS_TABLE_NAME: Optional[str] = None
    DYNAMODB_DOC_TERM_STATS_TABLE_NAME: Optional[str] = None

    SQS_BM25_UPDATE_QUEUE_URL: Optional[str] = None

    DOMAIN_LEXICON_DB_PATH: Optional[str] = None
    DOMAIN_LEXICON_SCHEMA_PATH: Optional[str] = None
    
    EMBEDDING_MODEL_ID: Optional[str] = None

    BM25_POINTER_KEY: Optional[str] = None
    BM25_SNAPSHOT_KEY: Optional[str] = None

    model_config = ConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
    )

# Local dev requires .env.local; Lambda runtime uses injected env vars
if not IS_LAMBDA_RUNTIME and not ENV_FILE_PATH.is_file():
    raise FileNotFoundError(f"Missing required env file: {ENV_FILE_PATH}")

settings = Settings(_env_file=ENV_FILE_PATH if not IS_LAMBDA_RUNTIME else None)
