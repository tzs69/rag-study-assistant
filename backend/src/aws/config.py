from pathlib import Path

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
    AWS_PROFILE: str
    AWS_REGION: str
    S3_GP_BUCKET_NAME: str
    S3_GP_RAW_PREFIX: str = "raws"
    S3_GP_CHUNK_PREFIC: str = "chunks"

    model_config = ConfigDict(
        env_file=ENV_FILE_PATH,
        env_file_encoding="utf-8",
        extra="ignore"
    )


if not dotenv_exists():
    raise FileNotFoundError(f"Missing required env file: {ENV_FILE_PATH}")

settings = Settings()
