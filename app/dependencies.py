"""Fábricas de singletons compartidos (caché, wrapper de LLM).

Igual que ``get_settings()`` en ``app/config.py``, ``@lru_cache`` hace que la
primera llamada construya el objeto y las siguientes devuelvan la misma
instancia.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from app.config import get_settings
from app.services.cache import EstimationCache
from app.services.sessions import SessionStore

if TYPE_CHECKING:
    from app.services.llm_service import LLMWrapper


@lru_cache
def get_cache() -> EstimationCache:
    settings = get_settings()
    return EstimationCache.from_url(settings.REDIS_URL, ttl=settings.CACHE_TTL)


@lru_cache
def get_llm_wrapper() -> "LLMWrapper":
    # Import diferido: llm_service.py importa get_llm_wrapper de este módulo,
    # así que importar LLMWrapper aquí arriba crearía un import circular.
    from app.services.llm_service import LLMWrapper

    return LLMWrapper()


@lru_cache
def get_session_store() -> SessionStore:
    return SessionStore(max_turns=get_settings().MAX_TURNS)
