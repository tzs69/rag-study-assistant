import os
from pathlib import Path
from typing import Optional

from pydantic import ConfigDict
from pydantic_settings import BaseSettings

ENV_FILE_PATH = Path(__file__).resolve().parent / ".env.local"
IS_LAMBDA_RUNTIME = bool(os.getenv("AWS_LAMBDA_FUNCTION_NAME"))


class Settings(BaseSettings):
    # Local dev can use SSO profile; Lambda runtime should omit it and rely on IAM role.
    AWS_SSO_PROFILE: Optional[str] = None
    AWS_SSO_REGION: Optional[str] = None
    AWS_REGION: Optional[str] = None

    S3_GP_BUCKET_NAME: str
    S3_GP_RAW_PREFIX: str = "raws"
    S3_GP_CHUNK_PREFIX: str = "chunks"
    S3_VECTOR_BUCKET_NAME: Optional[str] = None

    DYNAMODB_MANIFEST_TABLE_NAME: Optional[str] = None

    CHUNKING_MODEL_ID: Optional[str] = None
    EMBEDDING_MODEL_ID: Optional[str] = None
    S3_VECTOR_INDEX_NAME: Optional[str] = None

    model_config = ConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def aws_region_resolved(self) -> str:
        region = self.AWS_REGION or self.AWS_SSO_REGION
        if not region:
            raise ValueError("AWS region is required (AWS_REGION or AWS_SSO_REGION)")
        return region


# Local dev requires .env.local; Lambda runtime uses injected env vars
if not IS_LAMBDA_RUNTIME and not ENV_FILE_PATH.is_file():
    raise FileNotFoundError(f"Missing required env file: {ENV_FILE_PATH}")

settings = Settings(_env_file=ENV_FILE_PATH if not IS_LAMBDA_RUNTIME else None)
