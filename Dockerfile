# Servicio IA (FastAPI) en dos etapas con uv.
# 1) builder: instala las dependencias exactas de uv.lock en /app/.venv.
# 2) runtime: copia solo el .venv y app/, sin uv ni cachés, y corre sin root.

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

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production

USER estimator
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=3)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
