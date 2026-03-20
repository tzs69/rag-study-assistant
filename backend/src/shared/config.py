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

    model_config = ConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
    )

# Local dev requires .env.local; Lambda runtime uses injected env vars
if not IS_LAMBDA_RUNTIME and not ENV_FILE_PATH.is_file():
    raise FileNotFoundError(f"Missing required env file: {ENV_FILE_PATH}")

settings = Settings(_env_file=ENV_FILE_PATH if not IS_LAMBDA_RUNTIME else None)
