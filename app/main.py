"""FastAPI Application Entrypoint."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app.config import get_settings
from app.routers.estimations import router as estimations_router

settings = get_settings()

app = FastAPI(
    title=settings.APP_NAME,
    description=(
        "API de estimación de proyectos de software basada en arquitectura CAG "
        "(Context-Augmented Generation). Inyecta ejemplos históricos estáticos en la ventana "
        "de contexto del LLM para generar desgloses técnicos precisos a partir de transcripciones de reuniones."
    ),
    version="0.1.0",
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
    """Redirect root path to interactive Swagger documentationn."""
    return RedirectResponse(url="/docs")
