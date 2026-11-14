"""Session 11: RAGAS evaluation script, with fake metrics (no judge calls)."""

import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("evaluate_ragas", ROOT / "scripts" / "evaluate_ragas.py")
evaluate_ragas = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(evaluate_ragas)


def sample(query_id: str) -> dict:
    return {
        "id": query_id,
        "user_input": f"question {query_id}",
        "response": f"answer {query_id}",
        "retrieved_contexts": ["ctx 1", "ctx 2"],
        "reference": f"reference {query_id}",
        "total_hours": 460.0,
        "citations": {"passed": True, "grounded": 3, "dangling": 0, "evidence_mismatch": 0, "insufficient": 0},
        "generation": {"model": "claude-haiku", "provider": "anthropic", "prompt_version": "v1"},
    }


class FakeMetric:
    """Records the keyword arguments it is scored with and returns a fixed value."""

    def __init__(self, value=None, error=None):
        self.value, self.error, self.calls = value, error, []

    async def ascore(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(value=self.value)


def test_importing_the_script_disables_ragas_analytics():
    assert os.environ["RAGAS_DO_NOT_TRACK"] == "true"


@pytest.mark.parametrize(
    ("metric", "fields"),
    [
        ("faithfulness", {"user_input", "response", "retrieved_contexts"}),
        ("answer_relevancy", {"user_input", "response"}),
        ("context_precision", {"user_input", "reference", "retrieved_contexts"}),
        ("context_recall", {"user_input", "retrieved_contexts", "reference"}),
    ],
)
def test_each_metric_gets_only_its_fields(metric, fields):
    assert set(evaluate_ragas.metric_inputs(metric, sample("q01"))) == fields


def test_unknown_metric_is_an_error():
    with pytest.raises(ValueError):
        evaluate_ragas.metric_inputs("bleu", sample("q01"))


@pytest.mark.asyncio
async def test_a_failing_metric_is_recorded_as_none_and_the_rest_still_scored():
    metrics = {
        "faithfulness": FakeMetric(0.8),
        "answer_relevancy": FakeMetric(error=RuntimeError("429 quota")),
        "context_precision": FakeMetric(1.0),
        "context_recall": FakeMetric(0.5),
    }
    scores = await evaluate_ragas.score_samples([sample("q01"), sample("q02")], metrics)
    assert scores["q01"] == {
        "faithfulness": 0.8,
        "answer_relevancy": None,
        "context_precision": 1.0,
        "context_recall": 0.5,
    }
    assert metrics["context_recall"].calls[1]["reference"] == "reference q02"


def test_average_skips_missing_scores():
    scores = {
        "q01": {"faithfulness": 0.8, "answer_relevancy": None, "context_precision": 1.0, "context_recall": 0.5},
        "q02": {"faithfulness": 0.6, "answer_relevancy": None, "context_precision": 0.5, "context_recall": 1.0},
    }
    avg = evaluate_ragas.averages(scores)
    assert avg["faithfulness"] == pytest.approx(0.7)
    assert avg["answer_relevancy"] is None
    assert avg["context_recall"] == pytest.approx(0.75)


def full_results(judge: str = "gemini-test") -> dict:
    scores = {
        "q01": {"faithfulness": 0.8, "answer_relevancy": 0.9, "context_precision": 1.0, "context_recall": 0.5},
        "q02": {"faithfulness": None, "answer_relevancy": 0.7, "context_precision": 0.5, "context_recall": 1.0},
    }
    return evaluate_ragas.merge_scores({"scores": {}, "judges": {}}, scores, judge)


def test_report_has_one_row_per_query_and_an_average_row():
    report = evaluate_ragas.render([sample("q01"), sample("q02")], full_results())
    assert "| q01 | 0.80 | 0.90 | 1.00 | 0.50 |" in report
    assert "| q02 | error | 0.70 | 0.50 | 1.00 |" in report
    assert "| **Average** | **0.80** | **0.80** | **0.75** | **0.75** |" in report
    assert "Metric calls that failed: 1" in report
    assert "Cells still pending: 0" in report
    assert "  - context_recall: gemini-test" in report


def test_merge_overwrites_only_the_scored_cells_and_records_the_judge():
    results = full_results("judge-a")
    evaluate_ragas.merge_scores(results, {"q02": {"context_precision": 0.25}}, "judge-b")
    assert results["scores"]["q02"]["context_precision"] == 0.25
    assert results["judges"]["q02"]["context_precision"] == "judge-b"
    assert results["scores"]["q01"]["context_precision"] == 1.0
    assert results["judges"]["q02"]["faithfulness"] == "judge-a"


def test_unscored_cells_are_pending_not_errors():
    results = evaluate_ragas.merge_scores(
        {"scores": {}, "judges": {}}, {"q01": {"faithfulness": 0.8}, "q02": {"faithfulness": 0.6}}, "judge-a"
    )
    report = evaluate_ragas.render([sample("q01"), sample("q02")], results)
    assert "| q01 | 0.80 | pending | pending | pending |" in report
    assert "| **Average** | **0.70** | **pending** | **pending** | **pending** |" in report
    assert "Cells still pending: 6" in report
    assert "  - context_precision: pending" in report


def test_average_waits_until_every_query_is_scored():
    results = evaluate_ragas.merge_scores({"scores": {}, "judges": {}}, {"q01": {"faithfulness": 0.8}}, "judge-a")
    report = evaluate_ragas.render([sample("q01"), sample("q02")], results)
    assert "| **Average** | **pending** |" in report


def test_a_metric_judged_by_two_models_is_flagged_as_mixed():
    results = full_results("judge-a")
    evaluate_ragas.merge_scores(results, {"q02": {"context_precision": 0.25}}, "judge-b")
    report = evaluate_ragas.render([sample("q01"), sample("q02")], results)
    assert "  - context_precision: judge-a + judge-b (mixed)" in report


def test_saved_results_round_trip(tmp_path):
    path = tmp_path / "scores.json"
    assert evaluate_ragas.load_results(path) == {"scores": {}, "judges": {}}
    path.write_text('{"scores": {"q01": {"faithfulness": 0.5}}, "judges": {"q01": {"faithfulness": "j"}}, "average": {}}')
    assert evaluate_ragas.load_results(path)["judges"] == {"q01": {"faithfulness": "j"}}
