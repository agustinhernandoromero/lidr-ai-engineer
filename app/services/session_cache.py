"""Caché del turno 1 del endpoint de sesiones: exacta + semántica.

Solo el turno 1 es cacheable: sin historial, anclas, resumen ni metadata, su
respuesta depende únicamente del formulario, el tier, el mensaje y los
adjuntos, igual que ``/estimate``. A partir del turno 2 la respuesta depende de
toda la conversación y dos mensajes iguales en sesiones distintas NO son la
misma llamada (mismo criterio que el código de referencia del curso).

- Exacta: clave = hash de modelo + versión de prompt + system + user renderizados.
- Semántica: embedding del transcript (Gemini) comparado por coseno con las
  entradas del mismo *bucket* (formulario + tier + hash de adjuntos), guardadas
  en Redis normal. A esta escala la fuerza bruta en Python basta; Redis Stack
  sería el paso siguiente con miles de entradas.

Cualquier fallo de Redis o de los embeddings se registra y se trata como miss:
la caché nunca rompe un turno.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Callable, Optional

import structlog

logger = structlog.get_logger(__name__)

_PREFIX = "session_turn1"
MAX_SEMANTIC_ENTRIES = 200


@dataclass
class CacheHit:
    kind: str  # "exact" | "semantic"
    payload: dict
    similarity: Optional[float] = None


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


class SessionTurnCache:
    def __init__(
        self,
        client,
        *,
        embedder: Optional[Callable[[str], list[float]]],
        threshold: float,
        log_only: bool,
        ttl: int,
    ) -> None:
        self._client = client
        self._embedder = embedder
        self._threshold = threshold
        self._log_only = log_only
        self._ttl = ttl

    @staticmethod
    def exact_key(model: str, prompt_version: str, system: str, user: str) -> str:
        return _sha(json.dumps([model, prompt_version, system, user]))

    @staticmethod
    def bucket(
        prompt_version: str,
        project_type: str,
        detail_level: str,
        output_format: str,
        tier: str,
        attachments_text: str,
    ) -> str:
        return ":".join(
            [prompt_version, project_type, detail_level, output_format, tier,
             _sha(attachments_text)[:16]]
        )

    def _embed(self, transcript: str) -> Optional[list[float]]:
        if self._embedder is None:
            return None
        try:
            return self._embedder(transcript)
        except Exception as exc:  # noqa: BLE001
            logger.warning("session_cache_embedding_failed", error=str(exc))
            return None

    def lookup(self, *, key: str, bucket: str, transcript: str) -> Optional[CacheHit]:
        try:
            raw = self._client.get(f"{_PREFIX}:exact:{key}")
            if raw is not None:
                payload = json.loads(raw)
                logger.info("session_cache_hit", kind="exact")
                return CacheHit(kind="exact", payload=payload)

            vector = self._embed(transcript)
            if vector is None:
                return None
            best_score, best_payload = 0.0, None
            for item in self._client.lrange(f"{_PREFIX}:sem:{bucket}", 0, -1):
                entry = json.loads(item)
                score = _cosine(vector, entry["vector"])
                if score > best_score:
                    best_score, best_payload = score, entry["payload"]
        except Exception as exc:  # noqa: BLE001 — Redis caído o payload corrupto
            logger.warning("session_cache_unavailable", operation="lookup", error=str(exc))
            return None

        logger.info(
            "session_cache_semantic_score",
            similarity=round(best_score, 4),
            threshold=self._threshold,
            log_only=self._log_only,
        )
        if best_payload is None or best_score < self._threshold or self._log_only:
            return None
        logger.info("session_cache_hit", kind="semantic", similarity=round(best_score, 4))
        return CacheHit(kind="semantic", payload=best_payload, similarity=best_score)

    def store(self, *, key: str, bucket: str, transcript: str, payload: dict) -> None:
        try:
            self._client.set(f"{_PREFIX}:exact:{key}", json.dumps(payload), ex=self._ttl)
            vector = self._embed(transcript)
            if vector is None:
                return
            list_key = f"{_PREFIX}:sem:{bucket}"
            self._client.lpush(list_key, json.dumps({"vector": vector, "payload": payload}))
            self._client.ltrim(list_key, 0, MAX_SEMANTIC_ENTRIES - 1)
            self._client.expire(list_key, self._ttl)
        except Exception as exc:  # noqa: BLE001
            logger.warning("session_cache_unavailable", operation="store", error=str(exc))
