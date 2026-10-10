"""Caché del turno 1: exacta y semántica, sin romper nunca el turno."""

import fakeredis
import redis

from app.services.session_cache import SessionTurnCache

PAYLOAD = {"result": {"summary": "x"}, "metadata": {}, "model": "m", "provider": "anthropic"}


def vectors(mapping):
    """Embedder falso: devuelve el vector asignado a cada texto."""
    return lambda text: mapping[text]


def make_cache(embedder=None, threshold=0.92, log_only=False, client=None):
    client = client or fakeredis.FakeRedis(decode_responses=True)
    return SessionTurnCache(client, embedder=embedder, threshold=threshold, log_only=log_only, ttl=60)


def test_exact_hit_after_store():
    cache = make_cache()
    key = SessionTurnCache.exact_key("m", "v2", "sys", "user")
    cache.store(key=key, bucket="b", transcript="t", payload=PAYLOAD)
    hit = cache.lookup(key=key, bucket="b", transcript="t")
    assert hit.kind == "exact" and hit.payload == PAYLOAD


def test_semantic_hit_above_threshold_and_miss_below():
    emb = vectors({"portal reservas": [1.0, 0.0], "portal de reservas": [0.99, 0.05],
                   "app de fitness": [0.0, 1.0]})
    cache = make_cache(embedder=emb)
    cache.store(key="k1", bucket="b", transcript="portal reservas", payload=PAYLOAD)

    hit = cache.lookup(key="otra", bucket="b", transcript="portal de reservas")
    assert hit.kind == "semantic" and hit.similarity > 0.92
    assert cache.lookup(key="otra", bucket="b", transcript="app de fitness") is None


def test_different_bucket_never_shares():
    emb = vectors({"t": [1.0, 0.0]})
    cache = make_cache(embedder=emb)
    cache.store(key="k1", bucket="adjuntoA", transcript="t", payload=PAYLOAD)
    assert cache.lookup(key="k2", bucket="adjuntoB", transcript="t") is None


def test_bucket_depends_on_attachments_and_tier():
    a = SessionTurnCache.bucket("v2", "web_saas", "medium", "phases_table", "default", "PDF A")
    b = SessionTurnCache.bucket("v2", "web_saas", "medium", "phases_table", "default", "PDF B")
    c = SessionTurnCache.bucket("v2", "web_saas", "medium", "phases_table", "pm", "PDF A")
    assert len({a, b, c}) == 3


def test_log_only_never_serves_semantic_hits():
    emb = vectors({"t": [1.0, 0.0], "t2": [1.0, 0.0]})
    cache = make_cache(embedder=emb, log_only=True)
    cache.store(key="k1", bucket="b", transcript="t", payload=PAYLOAD)
    assert cache.lookup(key="k2", bucket="b", transcript="t2") is None


def test_broken_redis_and_embedder_degrade_to_miss():
    class Down:
        def __getattr__(self, name):
            def fail(*a, **k):
                raise redis.ConnectionError("Redis caído")
            return fail

    def broken_embedder(text):
        raise RuntimeError("Gemini caído")

    cache = make_cache(embedder=broken_embedder, client=Down())
    cache.store(key="k", bucket="b", transcript="t", payload=PAYLOAD)
    assert cache.lookup(key="k", bucket="b", transcript="t") is None


def test_corrupt_payload_is_a_miss():
    client = fakeredis.FakeRedis(decode_responses=True)
    cache = make_cache(client=client)
    client.set("session_turn1:exact:k", "{no es json")
    assert cache.lookup(key="k", bucket="b", transcript="t") is None
