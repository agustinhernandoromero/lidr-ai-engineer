"""Fábricas de singletons compartidos (caché).

Igual que ``get_settings()`` en ``app/config.py``, ``@lru_cache`` hace que la
primera llamada construya el objeto y las siguientes devuelvan la misma
instancia: un único cliente Redis para todo el proceso, no uno por petición.
"""

from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.services.cache import EstimationCache


@lru_cache
def get_cache() -> EstimationCache:
    settings = get_settings()
    return EstimationCache.from_url(settings.REDIS_URL, ttl=settings.CACHE_TTL)
