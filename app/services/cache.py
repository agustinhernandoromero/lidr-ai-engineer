"""Caché de coincidencia exacta para respuestas del LLM.

Deliberadamente simple: un diccionario en memoria del proceso. No sobrevive a un
reinicio ni se comparte entre workers. El cacheo semántico llega en la sesión 04.
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)

MAX_ENTRIES = 128

_store: "OrderedDict[str, dict[str, Any]]" = OrderedDict()


def make_key(system: str, user: str, model: str, provider: str) -> str:
    """Clave determinista a partir de todo lo que influye en la respuesta."""
    raw = "\x00".join((provider, model, system, user))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get(key: str) -> Optional[dict[str, Any]]:
    """Devuelve la entrada cacheada y la marca como usada recientemente."""
    hit = _store.get(key)
    if hit is not None:
        _store.move_to_end(key)
        logger.info("cache_hit", key=key[:12])
        return hit
    logger.info("cache_miss", key=key[:12])
    return None


def set(key: str, value: dict[str, Any]) -> None:
    """Guarda una entrada, desalojando la menos usada si se supera el límite."""
    _store[key] = value
    _store.move_to_end(key)
    while len(_store) > MAX_ENTRIES:
        evicted, _ = _store.popitem(last=False)
        logger.info("cache_evicted", key=evicted[:12])


def clear() -> None:
    """Vacía la caché. Usado por los tests."""
    _store.clear()


def size() -> int:
    return len(_store)
