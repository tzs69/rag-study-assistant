import os
from pathlib import Path
from pydantic import ConfigDict
from pydantic_settings import BaseSettings

ENV_FILE_PATH = Path(__file__).resolve().parent / ".env.local"
IS_LAMBDA_RUNTIME = bool(os.getenv("AWS_LAMBDA_FUNCTION_NAME"))

class Settings(BaseSettings):
    AWS_SSO_PROFILE: str = None
    AWS_SSO_REGION: str = None

    S3_GP_BUCKET_NAME: str = None
    S3_GP_RAW_PREFIX: str = None
    S3_GP_CHUNK_PREFIX: str = None

    S3_VECTOR_BUCKET_NAME: str = None
    S3_VECTOR_INDEX_NAME: str = None

    DYNAMODB_CORPUS_CHANGE_TABLE_NAME: str = None
    DYNAMODB_COLLECTION_TERM_STATS_TABLE_NAME: str = None
    DYNAMODB_DOC_TERM_STATS_TABLE_NAME: str = None

    SQS_BM25_UPDATE_QUEUE_URL: str = None
    
    EMBEDDING_MODEL_ID: str = None

    BM25_POINTER_KEY: str = None
    BM25_SNAPSHOT_KEY: str = None

    model_config = ConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
    )

settings = Settings(_env_file=ENV_FILE_PATH if not IS_LAMBDA_RUNTIME and ENV_FILE_PATH.is_file() else None)
