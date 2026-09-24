from functools import lru_cache
from typing import Literal, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration settings loaded from environment variables or .env file."""

    APP_NAME: str = "CAG Software Estimator API"
    APP_ENV: str = "development"
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # URL base del servicio IA, usada por el cliente Streamlit
    API_BASE_URL: str = "http://localhost:8000/api/v1"

    # LLM Provider Configuration ('openai' | 'anthropic')
    LLM_PROVIDER: Literal["openai", "anthropic"] = "openai"

    # OpenAI Configuration
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4o-mini"

    # Anthropic Configuration
    ANTHROPIC_API_KEY: Optional[str] = None
    ANTHROPIC_MODEL: str = "claude-haiku-4-5-20251001"

    # Versión de prompt por defecto
    PROMPT_VERSION: str = "v1"

    # Caché de respuestas del LLM (Redis)
    REDIS_URL: str = "redis://localhost:6379/0"
    CACHE_TTL: int = 86_400  # 24h

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache()
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()
