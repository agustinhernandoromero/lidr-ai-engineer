"""Golden dataset: casos fijos con lo que se espera de un buen estimador.

Las expectativas son rangos anchos, no cifras exactas: un LLM tiene margen
legítimo para estimar 640 h o 720 h. Lo que se busca son fallos claros
(un CRM sencillo en 5.000 h, un resumen que no menciona el CRM, un tier
equivocado), y comparar actor y Actor-Critic-Boss sobre los mismos casos.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

Range = tuple[int, int]
DEFAULT_PATH = Path(__file__).resolve().parent / "golden_dataset.json"
_RANGES = ("expected_phase_count_range", "expected_hours_range", "expected_duration_weeks_range")


class GoldenCase(BaseModel):
    id: str = Field(min_length=3, max_length=64)
    transcript: str = Field(min_length=20, max_length=20_000)
    project_type: Literal["mobile_app", "web_saas", "internal_tool", "data_pipeline"]
    detail_level: Literal["summary", "medium", "detailed"] = "medium"
    output_format: Literal["phases_table", "line_items", "narrative"] = "phases_table"

    expected_out_of_scope: bool = False
    expected_in_summary: list[str] = Field(default_factory=list)
    expected_technologies_any_of: list[str] = Field(default_factory=list)
    expected_phase_count_range: Optional[Range] = None
    expected_hours_range: Optional[Range] = None
    expected_duration_weeks_range: Optional[Range] = None
    expected_tier: Optional[Literal["executive", "pm", "developer", "default"]] = None

    @model_validator(mode="after")
    def _consistent(self) -> "GoldenCase":
        for name in _RANGES:
            rng = getattr(self, name)
            if rng is not None and rng[0] > rng[1]:
                raise ValueError(f"{name}: el mínimo es mayor que el máximo")
        has_expectations = (
            self.expected_in_summary or self.expected_technologies_any_of
            or self.expected_tier or any(getattr(self, n) for n in _RANGES)
        )
        if self.expected_out_of_scope and has_expectations:
            raise ValueError("un caso fuera de alcance no lleva contenido, rangos ni tier esperados")
        return self


def load_dataset(path: Path | str | None = None) -> list[GoldenCase]:
    raw = json.loads(Path(path or DEFAULT_PATH).read_text(encoding="utf-8"))
    cases = [GoldenCase.model_validate(entry) for entry in raw]
    ids = [c.id for c in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("hay ids repetidos en el golden dataset")
    return cases
