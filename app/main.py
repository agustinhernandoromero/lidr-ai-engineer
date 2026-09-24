"""FastAPI Application Entrypoint."""

import time
import uuid

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app.config import get_settings
from app.observability import configure_logging
from app.routers.estimations import router as estimations_router

settings = get_settings()
configure_logging(settings.APP_ENV)

logger = structlog.get_logger(__name__)

app = FastAPI(
    title=settings.APP_NAME,
    description=(
        "API de estimación de proyectos de software. Recibe una petición tipada "
        "(descripción, tipo de proyecto, nivel de detalle y formato de salida), renderiza "
        "un prompt versionado con Jinja2 y solicita al LLM la estimación técnica."
    ),
    version="0.2.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS middleware for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Asocia un request_id a todos los eventos structlog de la petición."""
    request_id = str(uuid.uuid4())[:8]
    structlog.contextvars.bind_contextvars(request_id=request_id, path=request.url.path)

    started = time.perf_counter()
    try:
        response = await call_next(request)
    finally:
        elapsed = time.perf_counter() - started

    logger.info(
        "http_request",
        method=request.method,
        status_code=response.status_code,
        elapsed_ms=round(elapsed * 1000, 1),
    )
    response.headers["X-Request-ID"] = request_id
    structlog.contextvars.clear_contextvars()
    return response


# Include API Routers
app.include_router(estimations_router, prefix="/api/v1")


@app.get("/health", tags=["Health"], summary="Health check del servicio")
async def health_check():
    """Health check endpoint to verify service availability."""
    return {
        "status": "ok",
        "app_name": settings.APP_NAME,
        "environment": settings.APP_ENV,
        "provider": settings.LLM_PROVIDER,
    }


@app.get("/", include_in_schema=False)
async def root():
    """Redirect root path to interactive Swagger documentation."""
    return RedirectResponse(url="/docs")
