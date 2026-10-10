from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration settings loaded from environment variables or .env file."""

    APP_NAME: str = "CAG Software Estimator API"
    APP_ENV: str = "development"
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # URL base del servicio IA, usada por el cliente Streamlit
    API_BASE_URL: str = "http://localhost:8000/api/v1"

    # Anthropic: proveedor principal (único; no hay switch de proveedor)
    ANTHROPIC_API_KEY: Optional[str] = None
    ANTHROPIC_MODEL: str = "claude-haiku-4-5-20251001"
    # Precio por millón de tokens del modelo anterior (Haiku 4.5), para estimar
    # el coste de cada llamada en los logs. Ajustar si se cambia de modelo.
    ANTHROPIC_INPUT_USD_PER_MTOK: float = 1.0
    ANTHROPIC_OUTPUT_USD_PER_MTOK: float = 5.0

    # Gemini: proveedor de respaldo gratuito si el proveedor principal falla
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-flash-latest"

    # Versión de prompt por defecto
    PROMPT_VERSION: str = "v1"

    # Caché de respuestas del LLM (Redis)
    REDIS_URL: str = "redis://localhost:6379/0"
    CACHE_TTL: int = 86_400  # 24h

    # Memoria conversacional (sesión 05)
    MAX_TURNS: int = 6  # pares user+assistant que conserva la ventana deslizante
    SESSION_PROMPT_VERSION: str = "v1"  # versión de app/prompts/session5/

    # Adjuntos (camino B: extracción local de texto)
    MAX_ATTACHMENT_BYTES: int = 3_000_000
    MAX_ATTACHMENT_CHARS: int = 20_000

    # Sesión 05 (directo): salida estructurada, memoria comprimida y caché del turno 1
    HOURLY_RATE_EUR: int = 50  # el LLM estima horas; los euros los calcula el código
    STRUCTURED_MAX_RETRIES: int = 2  # reintentos si el JSON no cumple las reglas
    SUMMARY_MAX_TOKENS: int = 600  # tope del resumen acumulativo
    SESSION_CACHE_ENABLED: bool = True  # caché exacta + semántica del turno 1
    GEMINI_EMBEDDING_MODEL: str = "gemini-embedding-001"
    EMBEDDING_DIMS: int = 768
    SEMANTIC_CACHE_THRESHOLD: float = 0.92  # similitud coseno mínima para servir
    SEMANTIC_CACHE_LOG_ONLY: bool = False  # True: mide similitudes sin servir hits

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache()
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()
