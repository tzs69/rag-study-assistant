from pathlib import Path
from typing import Optional

from pydantic import ConfigDict
from pydantic_settings import BaseSettings

ENV_FILE_PATH = Path(__file__).resolve().parent / ".env.local"


class Settings(BaseSettings):

    GENERATOR_MODEL_ID: str

    GENERATOR_MODEL_TEMPERATURE: float = 0.30

    model_config = ConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
    )

settings = Settings(_env_file=ENV_FILE_PATH if ENV_FILE_PATH.is_file() else None)
