from pathlib import Path
from typing import Optional

from pydantic import ConfigDict
from pydantic_settings import BaseSettings

ENV_FILE_PATH = Path(__file__).resolve().parent / ".env.local"

class Settings(BaseSettings):
    S3_GP_BUCKET_NAME: str
    S3_GP_RAW_PREFIX: str = "raws"
    S3_GP_CHUNK_PREFIX: str = "chunks"
    S3_VECTOR_BUCKET_NAME: Optional[str] = None

    DYNAMODB_MANIFEST_TABLE_NAME: Optional[str] = None
    DYNAMODB_CORPUS_CHANGE_TABLE_NAME: Optional[str] = None

    CHUNKING_MODEL_ID: Optional[str] = None
    EMBEDDING_MODEL_ID: Optional[str] = None
    S3_VECTOR_INDEX_NAME: Optional[str] = None

    SQS_BM25_UPDATE_QUEUE_URL: Optional[str] = None

    DYNAMODB_COLLECTION_TERM_STATS_TABLE_NAME: Optional[str] = None
    DYNAMODB_DOC_TERM_STATS_TABLE_NAME: Optional[str] = None

    model_config = ConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
    )

# Local dev requires .env.local; Lambda runtime uses injected env vars
if not ENV_FILE_PATH.is_file():
    raise FileNotFoundError(f"Missing required env file: {ENV_FILE_PATH}")

settings = Settings(_env_file=ENV_FILE_PATH)
