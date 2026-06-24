from pathlib import Path
from typing import Optional

from pydantic import ConfigDict
from pydantic_settings import BaseSettings

ENV_FILE_PATH = Path(__file__).resolve().parent / ".env.local"


class Settings(BaseSettings):

    # Retrieval model settings
    RETRIEVAL_MODEL_ID: str

    # BM25 snapshot polling setting
    BM25_POLL_INTERVAL_SECONDS: int = 5

    # Feature flag for retrieval-time spell correction
    ENABLE_SPELL_CORRECTION: bool = False

    # Minimum cosine similarity score threshold for semantic search candidate filtering
    MIN_COSINE_THRESHOLD: float = 0.30

    BASE_ENGLISH_LEXICON_PATH: str = "src/retrieval/data/base_english_lexicon.json"

    RERANKER_BASE_URL: str = "http://localhost:8080/"

    model_config = ConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
    )

settings = Settings(_env_file=ENV_FILE_PATH if ENV_FILE_PATH.is_file() else None)
