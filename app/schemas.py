"""Contrato tipado entre el cliente y el servicio IA (Pydantic v2)."""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


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
# Sesión 05 (directo): estimación estructurada
# --------------------------------------------------------------------------- #

OUT_OF_SCOPE_PREFIX = "Fuera de alcance:"
LOW_CONFIDENCE_THRESHOLD = 30
SUMMARY_MAX_CHARS = 1500


class Phase(BaseModel):
    """Una fase del desglose, en horas."""

    name: str = Field(min_length=1, max_length=100)
    hours_min: int = Field(ge=1, le=20_000)
    hours_max: int = Field(ge=1, le=20_000)
    confidence_pct: int = Field(ge=0, le=100)
    summary: str = Field(min_length=10, max_length=900)

    @model_validator(mode="after")
    def _min_not_above_max(self) -> "Phase":
        if self.hours_min > self.hours_max:
            raise ValueError(
                f"en la fase '{self.name}' hours_min ({self.hours_min}) es mayor que "
                f"hours_max ({self.hours_max})"
            )
        return self


class EstimationResult(BaseModel):
    """Estimación estructurada. El LLM estima horas; los euros los calcula el código.

    ``phases`` va ANTES que los totales a propósito: el modelo genera de
    izquierda a derecha, así que primero se compromete con cada fase y luego
    solo tiene que sumar. Con los totales primero tiende a elegir una cifra
    redonda y a cuadrar las fases a la fuerza.
    """

    summary: str = Field(min_length=10, max_length=SUMMARY_MAX_CHARS)
    confidence_pct: int = Field(ge=0, le=100)
    phases: list[Phase] = Field(min_length=1, max_length=10)
    total_hours_min: int = Field(ge=1, le=200_000)
    total_hours_max: int = Field(ge=1, le=200_000)
    total_duration_weeks: int = Field(ge=1, le=104)
    assumptions: list[str] = Field(default_factory=list, max_length=15)
    out_of_scope: list[str] = Field(default_factory=list, max_length=15)

    @model_validator(mode="after")
    def _totals_match_phases(self) -> "EstimationResult":
        sum_min = sum(p.hours_min for p in self.phases)
        sum_max = sum(p.hours_max for p in self.phases)
        if sum_min != self.total_hours_min:
            raise ValueError(
                f"las fases suman {sum_min} h de mínimo pero total_hours_min dice "
                f"{self.total_hours_min}; corrige las fases o el total"
            )
        if sum_max != self.total_hours_max:
            raise ValueError(
                f"las fases suman {sum_max} h de máximo pero total_hours_max dice "
                f"{self.total_hours_max}; corrige las fases o el total"
            )
        return self

    @model_validator(mode="after")
    def _low_confidence_is_declared(self) -> "EstimationResult":
        if (
            self.confidence_pct < LOW_CONFIDENCE_THRESHOLD
            and not self.summary.startswith(OUT_OF_SCOPE_PREFIX)
        ):
            raise ValueError(
                f"con confidence_pct < {LOW_CONFIDENCE_THRESHOLD} el summary debe empezar "
                f"por '{OUT_OF_SCOPE_PREFIX}'"
            )
        return self


def cost_range_eur(result: EstimationResult, rate: int) -> tuple[int, int]:
    """Euros = horas × tarifa. Lo calcula el código, nunca el LLM."""
    return result.total_hours_min * rate, result.total_hours_max * rate


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
    message_count: int = 0
    summary: Optional[str] = None
    summary_chars: int = 0
    anchors: list[dict[str, str]] = Field(default_factory=list)
    anchors_count: int = 0
    last_resolved_tier: str = "default"
    last_tier_rule: str = "default"
    last_turn_observed: Optional[dict] = None


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
    result: EstimationResult
    cost_min_eur: int
    cost_max_eur: int
    tier: str
    tier_rule: str
    anchors_count: int = 0
    summary_chars: int = 0
    structured_attempts: int = 1
    cache_hit_kind: str = "none"
    cache_similarity: Optional[float] = None
    observation: dict = Field(default_factory=dict)
