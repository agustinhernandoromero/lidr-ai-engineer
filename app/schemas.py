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
        max_length=2000,
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
