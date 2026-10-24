"""Embedders: texto → vector, con lotes, reintentos y log por lote.

Dos proveedores con la misma interfaz (embed_one / embed_many):
- OpenAIEmbedder: text-embedding-3-small, el modelo que pide el enunciado.
- GeminiEmbedder: gemini-embedding-001, por defecto (nivel gratuito).
Se elige con EMBEDDING_PROVIDER. Vectores de modelos distintos no son
comparables entre sí: nunca mezclar los de uno y otro.

Los dos devuelven EMBEDDING_DIMENSION (1536) dimensiones con norma 1, que es
lo que espera la columna vector(1536) de la tabla chunks.
"""

import math
import time
from abc import ABC, abstractmethod
from typing import Literal

import structlog

from app.config import get_settings
from app.db.models import EMBEDDING_DIMENSION
from app.embedding_pipeline.schemas import Chunk, EmbeddedChunk

logger = structlog.get_logger(__name__)

# Precios por millón de tokens de entrada. Cambian con el tiempo: revisar
# antes de fiarse del coste estimado.
OPENAI_EMBEDDING_USD_PER_MTOK = 0.02  # text-embedding-3-small
# Tarifa de pago de gemini-embedding-001 (sin confirmar en la página de precios
# actual). En el nivel gratuito el coste real es 0; se informa lo que costaría
# en producción.
GEMINI_EMBEDDING_USD_PER_MTOK = 0.15

BATCH_SIZE = 100  # chunks por llamada; también es el máximo de Gemini
RETRY_DELAYS_S = (1, 2, 4)  # 3 reintentos con espera exponencial

# "document" al ingerir, "query" al buscar. Gemini optimiza el vector para cada
# lado de la búsqueda; OpenAI no distingue y lo ignora.
EmbeddingTask = Literal["document", "query"]


class BaseEmbedder(ABC):
    """Lotes, reintentos, log y coste; cada proveedor implementa la llamada."""

    provider: str
    model: str
    usd_per_mtok: float

    def embed_one(self, text: str, task: EmbeddingTask = "document") -> list[float]:
        """Vector de un único texto."""
        return self._embed_with_retry([text], task)[0]

    def embed_many(self, chunks: list[Chunk], task: EmbeddingTask = "document") -> list[EmbeddedChunk]:
        """Vectores de todos los chunks, en lotes de BATCH_SIZE y en el mismo orden."""
        embedded: list[EmbeddedChunk] = []
        for start in range(0, len(chunks), BATCH_SIZE):
            batch = chunks[start : start + BATCH_SIZE]
            started = time.perf_counter()
            vectors = self._embed_with_retry([chunk.text for chunk in batch], task)
            logger.info(
                "embedding_batch",
                provider=self.provider,
                model=self.model,
                batch_index=start // BATCH_SIZE,
                chunks=len(batch),
                tokens=sum(chunk.token_count for chunk in batch),
                latency_ms=round((time.perf_counter() - started) * 1000, 1),
            )
            embedded.extend(
                EmbeddedChunk(**chunk.model_dump(), embedding=vector)
                for chunk, vector in zip(batch, vectors, strict=True)
            )
        return embedded

    def estimate_cost_usd(self, total_tokens: int) -> float:
        """Coste estimado de embeber total_tokens con este modelo."""
        return round(total_tokens / 1_000_000 * self.usd_per_mtok, 8)

    def _embed_with_retry(self, texts: list[str], task: EmbeddingTask) -> list[list[float]]:
        for attempt, delay in enumerate((*RETRY_DELAYS_S, None)):
            try:
                vectors = self._embed_batch(texts, task)
                break
            except Exception as exc:
                if delay is None or not self._is_retryable(exc):
                    raise
                logger.warning(
                    "embedding_retry",
                    provider=self.provider,
                    attempt=attempt + 1,
                    wait_s=delay,
                    error=type(exc).__name__,
                )
                time.sleep(delay)
        # Un vector de otra dimensión fallaría al insertar en vector(1536);
        # mejor un error claro aquí que uno de la base de datos.
        for vector in vectors:
            if len(vector) != EMBEDDING_DIMENSION:
                raise ValueError(
                    f"{self.model} devolvió {len(vector)} dimensiones; se esperaban {EMBEDDING_DIMENSION}"
                )
        return vectors

    @abstractmethod
    def _embed_batch(self, texts: list[str], task: EmbeddingTask) -> list[list[float]]:
        """Una llamada a la API con varios textos; devuelve los vectores en orden."""

    @abstractmethod
    def _is_retryable(self, exc: Exception) -> bool:
        """True si el error es de límite de peticiones y merece reintento."""


class OpenAIEmbedder(BaseEmbedder):
    """text-embedding-3-small con su dimensión por defecto (1536)."""

    provider = "openai"
    usd_per_mtok = OPENAI_EMBEDDING_USD_PER_MTOK

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        from openai import OpenAI

        settings = get_settings()
        api_key = api_key or settings.OPENAI_API_KEY
        if not api_key:
            raise RuntimeError("Falta OPENAI_API_KEY para EMBEDDING_PROVIDER=openai")
        self.model = model or settings.OPENAI_EMBEDDING_MODEL
        # max_retries=0: los reintentos los hace _embed_with_retry; si no, el SDK
        # sumaría los suyos a los nuestros.
        self._client = OpenAI(api_key=api_key, max_retries=0)

    def _embed_batch(self, texts: list[str], task: EmbeddingTask) -> list[list[float]]:
        # 1536 es la dimensión por defecto de text-embedding-3-small y ya viene
        # normalizada; task no tiene equivalente en la API de OpenAI.
        response = self._client.embeddings.create(model=self.model, input=texts)
        return [item.embedding for item in sorted(response.data, key=lambda item: item.index)]

    def _is_retryable(self, exc: Exception) -> bool:
        from openai import RateLimitError

        return isinstance(exc, RateLimitError)


class GeminiEmbedder(BaseEmbedder):
    """gemini-embedding-001 recortado a 1536 dimensiones (su nativa es 3072)."""

    provider = "gemini"
    usd_per_mtok = GEMINI_EMBEDDING_USD_PER_MTOK

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        from google import genai

        settings = get_settings()
        api_key = api_key or settings.GEMINI_API_KEY
        if not api_key:
            raise RuntimeError("Falta GEMINI_API_KEY para EMBEDDING_PROVIDER=gemini")
        self.model = model or settings.GEMINI_EMBEDDING_MODEL
        self._client = genai.Client(api_key=api_key)

    def _embed_batch(self, texts: list[str], task: EmbeddingTask) -> list[list[float]]:
        from google.genai import types

        response = self._client.models.embed_content(
            model=self.model,
            contents=texts,
            config=types.EmbedContentConfig(
                output_dimensionality=EMBEDDING_DIMENSION,
                task_type=GEMINI_TASK_TYPES[task],
            ),
        )
        # Gemini solo entrega norma 1 a 3072 dimensiones; recortado hay que
        # renormalizar para que coseno y producto escalar coincidan.
        return [_normalize(list(embedding.values)) for embedding in response.embeddings]

    def _is_retryable(self, exc: Exception) -> bool:
        from google.genai import errors

        # 429 = límite de peticiones; 503 = saturado, frecuente en el nivel gratuito.
        return isinstance(exc, errors.APIError) and exc.code in (429, 503)


GEMINI_TASK_TYPES: dict[EmbeddingTask, str] = {
    "document": "RETRIEVAL_DOCUMENT",
    "query": "RETRIEVAL_QUERY",
}


def _normalize(vector: list[float]) -> list[float]:
    """Escala el vector a norma 1."""
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        raise ValueError("Vector de norma 0: no se puede normalizar")
    return [value / norm for value in vector]


def get_embedder() -> BaseEmbedder:
    """Embedder del proveedor configurado en EMBEDDING_PROVIDER."""
    if get_settings().EMBEDDING_PROVIDER == "openai":
        return OpenAIEmbedder()
    return GeminiEmbedder()
