# Servicio IA (FastAPI) en dos etapas con uv.
# 1) builder: instala las dependencias exactas de uv.lock en /app/.venv.
# 2) runtime: copia el .venv, app/, scripts/, las migraciones de Alembic, los
#    presupuestos de ejemplo y query_examples.py, sin uv ni cachés, y corre sin root.

FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.13 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Primero solo las dependencias: esta capa se reutiliza mientras no cambie uv.lock.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project

COPY app ./app
RUN uv sync --frozen


FROM python:3.13-slim

RUN useradd --create-home --uid 1000 estimator
WORKDIR /app

COPY --from=builder --chown=estimator:estimator /app/.venv /app/.venv
COPY --chown=estimator:estimator app ./app
COPY --chown=estimator:estimator alembic ./alembic
COPY --chown=estimator:estimator alembic.ini ./
COPY --chown=estimator:estimator scripts ./scripts
COPY --chown=estimator:estimator data ./data
COPY --chown=estimator:estimator query_examples.py ./

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    TIKTOKEN_CACHE_DIR=/app/.tiktoken_cache

# tiktoken descarga su tabla de codificación en el primer uso; se baja al construir
# para que el contenedor no dependa de la red al arrancar.
RUN python -c "import tiktoken; tiktoken.encoding_for_model('text-embedding-3-small')" \
    && chown -R estimator:estimator /app/.tiktoken_cache

USER estimator
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=3)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
