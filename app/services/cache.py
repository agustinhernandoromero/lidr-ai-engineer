"""Caché de coincidencia exacta para respuestas del LLM, respaldada por Redis.

Sigue siendo "exact-match": la clave depende de todo lo que influye en la
respuesta (proveedor, modelo, system y user prompt). A diferencia de la
versión anterior (un diccionario en memoria del proceso), este almacén vive
en Redis: sobrevive a reinicios del servicio y se comparte entre workers.

Si Redis no está disponible, la caché degrada a "siempre cache miss" en vez
de tumbar la petición: el LLM se sigue llamando con normalidad, solo que sin
aprovechar la caché.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

import redis
import structlog

logger = structlog.get_logger(__name__)

DEFAULT_TTL = 86_400  # 24h


class EstimationCache:
    """Wrapper fino sobre un cliente Redis."""

    def __init__(self, client: "redis.Redis", ttl: int = DEFAULT_TTL) -> None:
        self._client = client
        self._ttl = ttl

    @classmethod
    def from_url(cls, url: str, ttl: int = DEFAULT_TTL) -> "EstimationCache":
        """Factory a partir de una REDIS_URL (``redis://host:port/db``)."""
        client = redis.Redis.from_url(url, decode_responses=True)
        return cls(client, ttl=ttl)

    @staticmethod
    def make_key(system: str, user: str, model: str, provider: str) -> str:
        """Clave determinista a partir de todo lo que influye en la respuesta."""
        payload = {
            "provider": provider,
            "model": model,
            "system_prompt": system,
            "user_message": user,
        }
        raw = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, key: str) -> Optional[dict[str, Any]]:
        """Lee de Redis. Si Redis falla, se trata como cache miss."""
        try:
            raw = self._client.get(key)
        except redis.RedisError as exc:
            logger.warning("cache_unavailable", operation="get", error=str(exc))
            return None

        if raw is None:
            logger.info("cache_miss", key=key[:12])
            return None

        logger.info("cache_hit", key=key[:12])
        return json.loads(raw)

    def set(self, key: str, value: dict[str, Any]) -> None:
        """Escribe en Redis con TTL. Si Redis falla, la escritura se ignora."""
        try:
            self._client.set(key, json.dumps(value), ex=self._ttl)
        except redis.RedisError as exc:
            logger.warning("cache_unavailable", operation="set", error=str(exc))
