"""Modelos Pydantic del pipeline de embeddings.

Entrada: presupuestos históricos ya normalizados (sesión 06).
Salida: chunks con su texto, metadata filtrable y vector.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# Universo cerrado: sector será un filtro en la búsqueda (sesión 08); un valor
# mal escrito dejaría el presupuesto fuera de cualquier filtro sin avisar.
Sector = Literal["finance", "ecommerce", "healthcare", "industrial"]
Complexity = Literal["low", "medium", "high"]


class ClientMetadata(BaseModel):
    """Datos del cliente del presupuesto."""

    name: str = Field(..., min_length=1)
    sector: Sector
    country: str = Field(..., pattern=r"^[A-Z]{2}$", description="Código ISO 3166-1 alfa-2.")


class BudgetComponent(BaseModel):
    """Un componente del presupuesto; cada uno se convierte en un chunk."""

    component_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    tech_stack: list[str] = Field(default_factory=list)
    estimated_hours: int = Field(..., gt=0)
    complexity: Complexity
    dependencies: list[str] = Field(default_factory=list)


class Budget(BaseModel):
    """Presupuesto histórico completo.

    No se exige que total_estimated_hours sea la suma de los componentes: en
    presupuestos reales suele incluir gestión o contingencia fuera de ellos.
    """

    budget_id: str = Field(..., min_length=1)
    client_metadata: ClientMetadata
    project_summary: str = Field(..., min_length=1)
    main_technology: str = Field(..., min_length=1)
    year: int = Field(..., ge=2000)
    total_estimated_hours: int = Field(..., gt=0)
    components: list[BudgetComponent] = Field(..., min_length=1)

    @field_validator("year")
    @classmethod
    def _year_not_in_future(cls, value: int) -> int:
        if value > date.today().year:
            raise ValueError("year no puede ser posterior al año actual")
        return value

    @field_validator("components")
    @classmethod
    def _unique_component_ids(cls, value: list[BudgetComponent]) -> list[BudgetComponent]:
        # chunk_id = budget_id::component_id; un id repetido daría dos chunks iguales.
        ids = [component.component_id for component in value]
        duplicates = sorted({cid for cid in ids if ids.count(cid) > 1})
        if duplicates:
            raise ValueError(f"component_id repetido en el presupuesto: {duplicates}")
        return value


class Chunk(BaseModel):
    """Fragmento listo para embeber."""

    chunk_id: str = Field(..., description="{budget_id}::{component_id}")
    text: str = Field(..., description="Texto que se embebe (cabecera del presupuesto + componente).")
    metadata: dict[str, str | int] = Field(
        ..., description="Campos filtrables que viajan con el chunk pero no se embeben."
    )
    token_count: int = Field(..., ge=0)


class EmbeddedChunk(Chunk):
    """Chunk con su vector."""

    embedding: list[float]


class IngestRequest(BaseModel):
    """Payload de POST /embeddings/ingest."""

    budgets: list[Budget] = Field(..., min_length=1)

    # Ejemplo pequeño para "Try it out" en /docs (el sample completo pesa ~3,5 MB de respuesta).
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "budgets": [
                        {
                            "budget_id": "BUD-2024-014",
                            "client_metadata": {"name": "FintechCorp", "sector": "finance", "country": "ES"},
                            "project_summary": "Mobile banking API with OAuth 2.0 authentication and PSD2 compliance",
                            "main_technology": "ruby_on_rails",
                            "year": 2024,
                            "total_estimated_hours": 260,
                            "components": [
                                {
                                    "component_id": "AUTH-001",
                                    "name": "OAuth 2.0 authentication backend",
                                    "description": (
                                        "Implementation of OAuth 2.0 flows (authorization code, refresh token) "
                                        "with JWT-based session management, multi-tenant token isolation, and "
                                        "rate limiting per client."
                                    ),
                                    "tech_stack": ["ruby_on_rails", "postgresql", "redis"],
                                    "estimated_hours": 120,
                                    "complexity": "high",
                                    "dependencies": [],
                                },
                                {
                                    "component_id": "ACC-001",
                                    "name": "Accounts and transactions API",
                                    "description": (
                                        "REST endpoints to list accounts, balances and paginated transaction "
                                        "history, with filtering by date range and category."
                                    ),
                                    "tech_stack": ["ruby_on_rails", "postgresql"],
                                    "estimated_hours": 140,
                                    "complexity": "medium",
                                    "dependencies": ["AUTH-001"],
                                },
                            ],
                        }
                    ]
                }
            ]
        }
    }

    @field_validator("budgets")
    @classmethod
    def _unique_budget_ids(cls, value: list[Budget]) -> list[Budget]:
        ids = [budget.budget_id for budget in value]
        duplicates = sorted({bid for bid in ids if ids.count(bid) > 1})
        if duplicates:
            raise ValueError(f"budget_id repetido en la petición: {duplicates}")
        return value


class IngestStats(BaseModel):
    """Estadísticas agregadas de una ingesta."""

    total_budgets: int
    total_chunks: int
    total_tokens: int
    estimated_cost_usd: float
    embedding_model: str = Field(
        ..., description="Modelo que generó los vectores; vectores de modelos distintos no son comparables."
    )


class IngestResponse(BaseModel):
    """Respuesta de POST /embeddings/ingest."""

    chunks: list[EmbeddedChunk]
    stats: IngestStats
