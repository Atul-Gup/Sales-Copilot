"""evals/test_run_specs_eval.py — T5.5."""

from __future__ import annotations

from evals.run_specs_eval import OVER_REFUSAL_THRESHOLD, run_specs_eval


def test_covers_every_specs_entry() -> None:
    results = run_specs_eval()
    assert results["n_legitimate_questions"] == 150


def test_over_refusal_rate_is_under_threshold() -> None:
    results = run_specs_eval()
    assert results["over_refusal_rate"] <= OVER_REFUSAL_THRESHOLD
    assert results["under_threshold"] is True


def test_zero_legitimate_questions_are_incorrectly_refused() -> None:
    results = run_specs_eval()
    assert results["n_incorrectly_refused"] == 0
    assert results["refused"] == []
