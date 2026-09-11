from functools import lru_cache
from typing import Literal, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration settings loaded from environment variables or .env file."""

    APP_NAME: str = "CAG Software Estimator API"
    APP_ENV: str = "development"
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # LLM Provider Configuration ('openai' | 'anthropic')
    LLM_PROVIDER: Literal["openai", "anthropic"] = "openai"

    # OpenAI Configuration
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4o-mini"

    # Anthropic Configuration
    ANTHROPIC_API_KEY: Optional[str] = None
    ANTHROPIC_MODEL: str = "claude-3-5-haiku-20241022"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache()
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()
