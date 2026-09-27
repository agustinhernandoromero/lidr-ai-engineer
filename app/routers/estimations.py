"""Estimations API router."""

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from app.prompts.loader import DEFAULT_VERSION, available_versions
from app.schemas import EstimationRequest, EstimationResponse
from app.services.llm_service import generate_estimation, stream_estimation

router = APIRouter(prefix="", tags=["Estimations"])

_VERSION_QUERY = Query(
    default=DEFAULT_VERSION,
    description="Versión de plantilla de prompt a usar (v1, v2…).",
)


@router.post(
    "/estimate",
    response_model=EstimationResponse,
    status_code=status.HTTP_200_OK,
    summary="Generar estimación de software",
    description=(
        "Recibe una petición tipada (descripción, tipo de proyecto, nivel de detalle y "
        "formato de salida), renderiza el prompt versionado correspondiente y solicita "
        "al LLM la generación de una estimación técnica. La respuesta es texto libre."
    ),
)
async def create_estimation(
    payload: EstimationRequest,
    prompt_version: str = _VERSION_QUERY,
) -> EstimationResponse:
    """Endpoint principal de estimación."""
    try:
        result = await generate_estimation(payload, prompt_version=prompt_version)
        return EstimationResponse(
            text=result["text"],
            prompt_version=result["prompt_version"],
            model=result["model"],
            provider=result["provider"],
            cached=result["cached"],
            fallback_used=result["fallback_used"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno durante la generación de la estimación: {exc}",
        )


@router.post(
    "/estimate/stream",
    status_code=status.HTTP_200_OK,
    summary="Generar estimación en streaming",
    description="Idéntico a /estimate, pero devuelve el texto token a token. No cachea.",
    response_class=StreamingResponse,
)
async def create_estimation_stream(
    payload: EstimationRequest,
    prompt_version: str = _VERSION_QUERY,
) -> StreamingResponse:
    """Streaming de la estimación como text/plain."""
    try:
        generator = stream_estimation(payload, prompt_version=prompt_version)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return StreamingResponse(
        generator,
        media_type="text/plain; charset=utf-8",
        headers={"X-Prompt-Version": prompt_version},
    )


@router.get(
    "/prompt-versions",
    summary="Listar versiones de prompt disponibles",
)
async def list_prompt_versions() -> dict:
    """Versiones presentes en app/prompts/estimation/."""
    return {"default": DEFAULT_VERSION, "available": available_versions()}
