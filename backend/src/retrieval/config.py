from pathlib import Path
from typing import Optional

from pydantic import ConfigDict
from pydantic_settings import BaseSettings

ENV_FILE_PATH = Path(__file__).resolve().parent / ".env.local"


class Settings(BaseSettings):

    # Retrieval model settings (optional until wired)
    RETRIEVAL_MODEL_ID: Optional[str] = None

    # BM25 snapshot polling setting
    BM25_POLL_INTERVAL_SECONDS: int = 5

    model_config = ConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
    )


# Local dev requires .env.local; Lambda/runtime can inject env vars.
if not ENV_FILE_PATH.is_file():
    raise FileNotFoundError(f"Missing required env file: {ENV_FILE_PATH}")

settings = Settings(_env_file=ENV_FILE_PATH)
