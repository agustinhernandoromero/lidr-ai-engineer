"""Tests de EstimationCache.

Dos escenarios, cada uno con una herramienta distinta:

- "Redis funciona": usamos ``fakeredis`` (una implementación en memoria que
  respeta la misma interfaz que ``redis.Redis``), así probamos la lógica real
  de serialización/TTL sin depender de un Redis levantado en Docker.
- "Redis está caído": usamos un ``Mock`` cuyo ``get``/``set`` lanzan
  ``redis.RedisError`` a propósito, para comprobar que la caché degrada a
  "cache miss" en vez de tumbar la petición.
"""

from unittest.mock import Mock

import fakeredis
import pytest
import redis

from app.services.cache import EstimationCache

TTL = 60


@pytest.fixture
def cache() -> EstimationCache:
    """EstimationCache respaldada por un Redis falso, vacío en cada test."""
    client = fakeredis.FakeRedis(decode_responses=True)
    return EstimationCache(client, ttl=TTL)


# --------------------------------------------------------------------------- #
# make_key
# --------------------------------------------------------------------------- #


def test_make_key_is_deterministic():
    key_a = EstimationCache.make_key("system", "user", "gpt-4o-mini", "openai")
    key_b = EstimationCache.make_key("system", "user", "gpt-4o-mini", "openai")
    assert key_a == key_b


@pytest.mark.parametrize(
    "field,value",
    [
        ("system", "otro system"),
        ("user", "otro user"),
        ("model", "claude-haiku-4-5"),
        ("provider", "anthropic"),
    ],
)
def test_make_key_differs_when_any_input_changes(field, value):
    base = dict(system="system", user="user", model="gpt-4o-mini", provider="openai")
    changed = {**base, field: value}

    key_base = EstimationCache.make_key(**base)
    key_changed = EstimationCache.make_key(**changed)

    assert key_base != key_changed


# --------------------------------------------------------------------------- #
# Camino feliz: Redis disponible (fakeredis)
# --------------------------------------------------------------------------- #


def test_get_returns_none_when_key_absent(cache: EstimationCache):
    assert cache.get("no-existe") is None


def test_set_then_get_returns_stored_value(cache: EstimationCache):
    key = EstimationCache.make_key("system", "user", "gpt-4o-mini", "openai")
    value = {"text": "Estimación de prueba", "model": "gpt-4o-mini", "provider": "openai"}

    cache.set(key, value)

    assert cache.get(key) == value


def test_set_applies_configured_ttl(cache: EstimationCache):
    key = EstimationCache.make_key("system", "user", "gpt-4o-mini", "openai")
    cache.set(key, {"text": "x", "model": "gpt-4o-mini", "provider": "openai"})

    ttl = cache._client.ttl(key)

    assert 0 < ttl <= TTL


# --------------------------------------------------------------------------- #
# Camino de fallo: Redis no disponible
# --------------------------------------------------------------------------- #


def test_get_degrades_to_none_when_redis_unavailable():
    broken_client = Mock()
    broken_client.get.side_effect = redis.ConnectionError("no se pudo conectar")
    cache = EstimationCache(broken_client, ttl=TTL)

    result = cache.get("cualquier-clave")

    assert result is None


def test_set_swallows_error_when_redis_unavailable():
    broken_client = Mock()
    broken_client.set.side_effect = redis.ConnectionError("no se pudo conectar")
    cache = EstimationCache(broken_client, ttl=TTL)

    # No debe lanzar excepción: una escritura fallida nunca debe tumbar la petición.
    cache.set("cualquier-clave", {"text": "x"})
