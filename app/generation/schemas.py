"""Output schema of the grounded estimator: every line carries the sources it comes from.

A chunk of the corpus is one component of one historical budget, so a line can cite
the exact component it was derived from: `chunk_id` is "<budget_id>::<component_id>"
and `document_id` is the budget id.
"""

from pydantic import BaseModel, Field, model_validator

CHUNK_ID_SEPARATOR = "::"


class SourceReference(BaseModel):
    """One retrieved chunk backing an estimate line."""

    chunk_id: str = Field(
        min_length=1,
        max_length=120,
        description="Id of the retrieved source backing this line, copied exactly as given.",
    )
    document_id: str = Field(
        min_length=1,
        max_length=60,
        description="Historical budget the source belongs to: the part of chunk_id before '::'.",
    )
    evidence: str = Field(
        min_length=1,
        max_length=400,
        description="Verbatim span or figure copied from the source, not a paraphrase.",
    )


class EstimateLineItem(BaseModel):
    """One component of the estimate.

    Integrity rule: a grounded line cites at least one source and carries hours; a
    line without sufficient source data carries neither hours nor sources, so no
    figure can be invented to fill the gap.
    """

    component: str = Field(min_length=1, max_length=120)
    # hours and sources have no default: the model must take a position on both in
    # every line instead of leaving them out.
    hours: float | None = Field(
        ge=1,
        le=20_000,
        description="Estimated hours. null when grounded is false.",
    )
    rationale: str = Field(min_length=5, max_length=800)
    grounded: bool = Field(description="false when the sources give no sufficient data.")
    sources: list[SourceReference] = Field(
        max_length=6,
        description="Non-empty if and only if grounded is true.",
    )

    @model_validator(mode="after")
    def _grounding_is_consistent(self) -> "EstimateLineItem":
        if self.grounded:
            if not self.sources:
                raise ValueError("a grounded line must cite at least one source")
            if self.hours is None:
                raise ValueError("a grounded line must carry hours")
        else:
            if self.hours is not None:
                raise ValueError("a line without sufficient data must have hours = null")
            if self.sources:
                raise ValueError("a line without sufficient data must have no sources")
        return self


class GroundedEstimate(BaseModel):
    """An estimate whose every figure points to the historical budget it comes from."""

    summary: str = Field(min_length=10, max_length=1500)
    line_items: list[EstimateLineItem] = Field(min_length=1, max_length=15)

    @property
    def total_hours(self) -> float:
        """Sum of the grounded lines. Computed here, never asked to the model."""
        return sum(line.hours for line in self.line_items if line.grounded and line.hours)

    @property
    def cited_chunk_ids(self) -> list[str]:
        return [source.chunk_id for line in self.line_items for source in line.sources]
