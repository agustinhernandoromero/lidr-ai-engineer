"""Medidor de uso por turno: tokens, coste y llamadas de TODAS las llamadas al LLM.

Envuelve al LLM durante un turno. El estimador (con sus reintentos), el
extractor y el resumidor llaman a ``complete`` sin saber que pasan por aquí,
así que no hace falta cambiar ninguna firma para agregar su gasto.
"""

from __future__ import annotations

from app.services.llm_service import MAX_TOKENS, estimate_cost_usd


class UsageMeter:
    def __init__(self, llm, settings) -> None:
        self._llm = llm
        self._settings = settings
        self.tokens_in = 0
        self.tokens_out = 0
        self.cost_usd = 0.0
        self.llm_calls = 0

    def complete(self, messages, max_tokens: int = MAX_TOKENS, json_schema=None) -> dict:
        out = self._llm.complete(messages, max_tokens=max_tokens, json_schema=json_schema)
        usage = out.get("usage") or {}
        tokens_in = int(usage.get("input_tokens") or 0)
        tokens_out = int(usage.get("output_tokens") or 0)
        self.tokens_in += tokens_in
        self.tokens_out += tokens_out
        self.cost_usd += estimate_cost_usd(
            out.get("provider", ""),
            {"input_tokens": tokens_in, "output_tokens": tokens_out},
            self._settings,
        )
        self.llm_calls += 1
        return out
