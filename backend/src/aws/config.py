import os
from pathlib import Path
from typing import Optional

from pydantic import ConfigDict
from pydantic_settings import BaseSettings

ENV_FILE_PATH = Path(__file__).resolve().parent / ".env.local"


def dotenv_exists(env_filename: str = ".env.local") -> bool:
    """
    Verify that a local env file exists in the same folder as this config file.
    """
    env_path = Path(__file__).resolve().parent / env_filename
    return env_path.is_file()


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
        env_file=ENV_FILE_PATH,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def aws_region_resolved(self) -> str:
        region = self.AWS_REGION or self.AWS_SSO_REGION
        if not region:
            raise ValueError("AWS region is required (AWS_REGION or AWS_SSO_REGION)")
        return region


# Local development expects .env.local, but Lambda runtime should rely on injected env vars.
if not dotenv_exists() and not any(
    os.getenv(name)
    for name in ("AWS_REGION", "AWS_SSO_REGION", "AWS_LAMBDA_FUNCTION_NAME")
):
    raise FileNotFoundError(f"Missing required env file: {ENV_FILE_PATH}")

settings = Settings()
