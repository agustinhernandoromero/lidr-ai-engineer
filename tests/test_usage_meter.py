"""UsageMeter: suma lo que gastan todas las llamadas de un turno."""

from app.config import Settings
from app.services.usage_meter import UsageMeter
from tests.helpers import FakeLLM


class Scripted:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.seen = []

    def complete(self, messages, max_tokens=4000, json_schema=None):
        self.seen.append((max_tokens, json_schema))
        return self.outputs.pop(0)


SETTINGS = Settings(ANTHROPIC_INPUT_USD_PER_MTOK=1.0, ANTHROPIC_OUTPUT_USD_PER_MTOK=5.0)


def test_sums_tokens_cost_and_calls_across_providers():
    llm = Scripted([
        {"text": "a", "provider": "anthropic", "model": "m",
         "usage": {"input_tokens": 1000, "output_tokens": 200}},
        {"text": "b", "provider": "gemini", "model": "g",
         "usage": {"input_tokens": 500, "output_tokens": 100}},
    ])
    meter = UsageMeter(llm, SETTINGS)
    meter.complete([{"role": "user", "content": "x"}], max_tokens=500, json_schema={"a": 1})
    meter.complete([{"role": "user", "content": "y"}])

    assert (meter.tokens_in, meter.tokens_out, meter.llm_calls) == (1500, 300, 2)
    assert abs(meter.cost_usd - 0.002) < 1e-9  # Gemini cuesta 0
    assert llm.seen[0] == (500, {"a": 1})


def test_missing_usage_counts_as_zero():
    meter = UsageMeter(FakeLLM(), SETTINGS)
    meter.complete([{"role": "system", "content": "Eres un estimador"},
                    {"role": "user", "content": "Hola"}])
    assert (meter.tokens_in, meter.tokens_out, meter.cost_usd, meter.llm_calls) == (0, 0, 0.0, 1)


def test_failed_call_propagates_and_is_not_counted():
    meter = UsageMeter(FakeLLM(fail_estimator=True), SETTINGS)
    try:
        meter.complete([{"role": "system", "content": "x"}, {"role": "user", "content": "y"}])
    except RuntimeError:
        pass
    assert meter.llm_calls == 0
