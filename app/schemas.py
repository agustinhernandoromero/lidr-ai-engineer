"""Contrato tipado entre el cliente y el servicio IA (Pydantic v2)."""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ProjectType(str, Enum):
    MOBILE_APP = "mobile_app"
    WEB_SAAS = "web_saas"
    INTERNAL_TOOL = "internal_tool"
    DATA_PIPELINE = "data_pipeline"


class DetailLevel(str, Enum):
    SUMMARY = "summary"
    MEDIUM = "medium"
    DETAILED = "detailed"


class OutputFormat(str, Enum):
    PHASES_TABLE = "phases_table"
    LINE_ITEMS = "line_items"
    NARRATIVE = "narrative"


class ReferenceProject(BaseModel):
    """Proyecto similar aportado por el cliente como referencia (bonus)."""

    name: str = Field(min_length=2, max_length=120)
    summary: str = Field(min_length=10, max_length=600)
    total_hours: Optional[int] = Field(default=None, ge=1, le=100_000)


class EstimationRequest(BaseModel):
    """Payload tipado de entrada al endpoint de estimación."""

    description: str = Field(
        min_length=20,
        max_length=20_000,
        description="Descripción del proyecto o notas de la reunión de requerimientos.",
    )
    project_type: ProjectType
    detail_level: DetailLevel
    output_format: OutputFormat
    reference_projects: Optional[list[ReferenceProject]] = Field(
        default=None,
        description="Proyectos similares que el modelo debe usar como anclaje de escala.",
    )


class EstimationResponse(BaseModel):
    """Payload de salida. El texto sigue siendo libre en esta sesión."""

    text: str
    prompt_version: str
    model: str
    provider: str
    cached: bool = False
    fallback_used: bool = False


# --------------------------------------------------------------------------- #
# Sesión 05: conversación multiturno
# --------------------------------------------------------------------------- #

from app.services.sessions import ProjectMetadata  # noqa: E402


class SessionCreatedResponse(BaseModel):
    session_id: str


class SessionStateResponse(BaseModel):
    """Estado de una sesión: memoria (metadata) e historial, por separado."""

    session_id: str
    turn_count: int
    history_turns: int
    max_turns: int
    project_metadata: ProjectMetadata
    history: list[dict[str, str]]


class SessionEstimationResponse(BaseModel):
    """``EstimationResponse`` ampliada con el estado conversacional."""

    text: str
    prompt_version: str
    model: str
    provider: str
    fallback_used: bool = False
    session_id: str
    turn: int
    history_turns: int = Field(description="Pares de historial enviados al LLM en este turno.")
    project_metadata: ProjectMetadata
    warnings: list[str] = Field(default_factory=list)
