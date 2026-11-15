"""Configuration settings for the FlameSight BFF Gateway."""

from typing import List, Optional, Union
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with environment variable overrides."""

    APP_NAME: str = "FlameSight BFF Gateway"
    APP_VERSION: str = "v0.1-hackathon"
    DISCLAIMER: str = "v0.1, unverified"
    ENVIRONMENT: str = "development"
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # AI Microservice URL (e.g. flamesight RAG service).
    # If empty or unreachable, backend gracefully falls back to grounded stub answers.
    AI_SERVICE_URL: Optional[str] = None

    # SQLite Database location. If file/tables are not found, falls back to rich seed data.
    DB_PATH: str = "data/flamesight.db"

    # Query response caching TTL (in seconds)
    CACHE_TTL_SECONDS: int = 300

    # Upstream AI proxy timeout in seconds. Claude-written answers take 6-8 s warm and the hosted AI service's
    # first request after idle about 45 s, so keep the Frontend's NEXT_PUBLIC_API_TIMEOUT_MS above this (50000).
    AI_PROXY_TIMEOUT_SECONDS: float = 30.0

    # CORS origins
    ALLOWED_ORIGINS: Union[str, List[str]] = ["*"]

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            if v.strip() == "*":
                return ["*"]
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )


settings = Settings()
