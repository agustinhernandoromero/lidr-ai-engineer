"""Estimations API router."""

import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.services.llm_service import generate_estimation

router = APIRouter(prefix="", tags=["Estimations"])


class EstimationRequest(BaseModel):
    """Request payload containing meeting transcription."""

    transcription: str = Field(
        ...,
        min_length=10,
        description="Texto completo o notas detalladas de la transcripción de la reunión con el cliente.",
        examples=[
            "En la reunión con el cliente se discutió la necesidad de crear un e-commerce para venta de café artesanal con pasarela de pago Stripe, panel de administración para pedidos e integración con empresa de envíos."
        ],
    )


class EstimationResponse(BaseModel):
    """Response payload containing generated software estimation."""

    estimation: str = Field(
        ...,
        description="Estimación detallada generada por el LLM en formato Markdown con desglose de tareas, horas y equipo.",
    )
    model: str = Field(..., description="Nombre del modelo LLM utilizado.")
    provider: str = Field(..., description="Proveedor del LLM ('openai' o 'anthropic').")
    created_at: str = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat(),
        description="Marca de tiempo UTC de la estimación.",
    )


@router.post(
    "/estimate",
    response_model=EstimationResponse,
    status_code=status.HTTP_200_OK,
    summary="Generar estimación de software (CAG)",
    description=(
        "Recibe la transcripción de una reunión de requerimientos, inyecta ejemplos históricos "
        "de estimaciones como contexto estático (CAG) y solicita a un LLM la generación "
        "de una estimación técnica completa."
    ),
)
async def create_estimation(payload: EstimationRequest) -> EstimationResponse:
    """Generate software estimation endpoint."""
    try:
        result = await generate_estimation(transcription=payload.transcription)
        return EstimationResponse(
            estimation=result["estimation"],
            model=result["model"],
            provider=result["provider"],
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno durante la generación de la estimación: {str(e)}",
        )
