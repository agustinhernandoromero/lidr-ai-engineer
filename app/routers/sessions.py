"""Sesiones conversacionales: memoria entre turnos y adjuntos PDF/Word."""

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.concurrency import run_in_threadpool

from app.config import get_settings
from app.dependencies import get_llm_wrapper, get_session_store
from app.schemas import (
    DetailLevel,
    OutputFormat,
    ProjectType,
    SessionCreatedResponse,
    SessionEstimationResponse,
    SessionStateResponse,
)
from app.services.attachments import AttachmentError, extract_attachment
from app.services.conversation import run_turn
from app.services.sessions import Session, SessionStore

router = APIRouter(prefix="/sessions", tags=["Sessions"])


def _get_session_or_404(store: SessionStore, session_id: str) -> Session:
    session = store.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"La sesión '{session_id}' no existe o ha expirado (el servicio se reinició).",
        )
    return session


@router.post(
    "",
    response_model=SessionCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear una sesión conversacional vacía",
)
async def create_session(store: SessionStore = Depends(get_session_store)) -> SessionCreatedResponse:
    return SessionCreatedResponse(session_id=store.create().session_id)


@router.get(
    "/{session_id}",
    response_model=SessionStateResponse,
    summary="Estado de la sesión: project_metadata e historial",
)
async def get_session(
    session_id: str, store: SessionStore = Depends(get_session_store)
) -> SessionStateResponse:
    session = _get_session_or_404(store, session_id)
    return SessionStateResponse(
        session_id=session.session_id,
        turn_count=session.turn_count,
        history_turns=len(session.history),
        max_turns=session.history.max_turns,
        project_metadata=session.metadata,
        history=session.history.as_dicts(),
    )


@router.post(
    "/{session_id}/estimate",
    response_model=SessionEstimationResponse,
    summary="Estimar dentro de una sesión (multipart: transcripción + adjuntos)",
    description=(
        "Acepta `multipart/form-data` con la transcripción, los parámetros tipados y "
        "adjuntos opcionales (.pdf, .docx). El texto de los adjuntos se extrae en el "
        "servicio. El historial y el `project_metadata` de la sesión se actualizan "
        "automáticamente."
    ),
)
async def estimate_in_session(
    session_id: str,
    transcript: str = Form(..., min_length=20, max_length=20_000),
    project_type: ProjectType = Form(ProjectType.WEB_SAAS),
    detail_level: DetailLevel = Form(DetailLevel.MEDIUM),
    output_format: OutputFormat = Form(OutputFormat.PHASES_TABLE),
    attachments: Optional[list[UploadFile]] = File(default=None),
    prompt_version: Optional[str] = Query(
        default=None, description="Versión de app/prompts/session5/ (por defecto la de config)."
    ),
    store: SessionStore = Depends(get_session_store),
    llm=Depends(get_llm_wrapper),
) -> SessionEstimationResponse:
    session = _get_session_or_404(store, session_id)
    settings = get_settings()

    extracted = []
    for upload in attachments or []:
        data = await upload.read()
        try:
            extracted.append(
                extract_attachment(
                    upload.filename,
                    data,
                    max_bytes=settings.MAX_ATTACHMENT_BYTES,
                    max_chars=settings.MAX_ATTACHMENT_CHARS,
                )
            )
        except AttachmentError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail)

    async with session.lock:
        try:
            # El SDK es síncrono y un turno hace dos llamadas: en el threadpool
            # no bloquean el event loop para el resto de sesiones.
            result = await run_in_threadpool(
                run_turn,
                session,
                llm,
                transcript=transcript.strip(),
                project_type=project_type.value,
                detail_level=detail_level.value,
                output_format=output_format.value,
                attachments=extracted,
                prompt_version=prompt_version or settings.SESSION_PROMPT_VERSION,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error interno durante el turno de la sesión: {exc}",
            )

    return SessionEstimationResponse(**result)
