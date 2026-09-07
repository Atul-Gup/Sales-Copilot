"""Unit tests for evals/metrics.py (T3.5).

Most metrics here score a real pipeline (objection generation, guardrails)
that doesn't exist yet (T4.x/T5.x). These tests use synthetic fixtures to
verify each metric's arithmetic is correct in isolation; a few also load the
real T3.2-T3.4 datasets to prove the functions actually accept that shape of
data, since that's what run_eval.py (T3.6) will hand them.
"""

import json
from pathlib import Path
from typing import Any

from evals.metrics import (
    Claim,
    ConcessionJudgment,
    GroundTruthFact,
    GuardrailOutcome,
    LatencySample,
    citation_validity,
    hallucinated_spec_rate,
    honest_concession_rate,
    judge_agreement_rate,
    latency_percentiles,
    over_refusal_rate,
    refusal_accuracy,
    tco_accuracy,
)

DATASET_DIR = Path(__file__).parent / "dataset"


def _load_jsonl(name: str) -> list[dict[str, Any]]:
    with (DATASET_DIR / name).open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


# ---------------------------------------------------------------------------
# hallucinated_spec_rate / citation_validity
# ---------------------------------------------------------------------------

FACTS = [
    GroundTruthFact("XC60 Mild Hybrid", "overall_length_mm", "4708", source_id=1),
    GroundTruthFact("EX30 Pure Electric", "battery_capacity_kwh", "69", source_id=2),
]


def test_hallucinated_spec_rate_no_claims_is_zero() -> None:
    assert hallucinated_spec_rate([], FACTS) == 0.0


def test_hallucinated_spec_rate_all_grounded() -> None:
    claims = [Claim("XC60 Mild Hybrid", "overall_length_mm", "4708", cited_source_id=1)]
    assert hallucinated_spec_rate(claims, FACTS) == 0.0


def test_hallucinated_spec_rate_counts_unknown_claims() -> None:
    claims = [
        Claim("XC60 Mild Hybrid", "overall_length_mm", "4708", cited_source_id=1),
        Claim("XC60 Mild Hybrid", "boot_capacity_l", "999", cited_source_id=None),
    ]
    assert hallucinated_spec_rate(claims, FACTS) == 0.5


def test_citation_validity_ignores_uncited_claims() -> None:
    claims = [Claim("XC60 Mild Hybrid", "boot_capacity_l", "999", cited_source_id=None)]
    assert citation_validity(claims, FACTS) == 0.0


def test_citation_validity_correct_source() -> None:
    claims = [Claim("XC60 Mild Hybrid", "overall_length_mm", "4708", cited_source_id=1)]
    assert citation_validity(claims, FACTS) == 1.0


def test_citation_validity_wrong_source_id() -> None:
    claims = [Claim("XC60 Mild Hybrid", "overall_length_mm", "4708", cited_source_id=99)]
    assert citation_validity(claims, FACTS) == 0.0


# ---------------------------------------------------------------------------
# honest_concession_rate / judge_agreement_rate
# ---------------------------------------------------------------------------


def test_honest_concession_rate_full_marks() -> None:
    entries = _load_jsonl("concessions.jsonl")
    judgments = []
    for entry in entries:
        shape = entry["expected_response_shape"]
        judgments.append(
            ConcessionJudgment(
                entry_id=entry["id"],
                acknowledged=shape["must_acknowledge"],
                stated_figure=shape["must_state_figure"],
                included_mitigating_fact=shape["must_include_mitigating_fact"],
                ended_on_deflection=False,
            )
        )
    assert honest_concession_rate(entries, judgments) == 1.0


def test_honest_concession_rate_penalises_deflection() -> None:
    entries = [
        {
            "id": "x1",
            "expected_response_shape": {
                "must_acknowledge": True,
                "must_state_figure": True,
                "must_include_mitigating_fact": True,
                "must_not_deflect": True,
            },
        }
    ]
    judgments = [
        ConcessionJudgment(
            entry_id="x1",
            acknowledged=True,
            stated_figure=True,
            included_mitigating_fact=True,
            ended_on_deflection=True,
        )
    ]
    assert honest_concession_rate(entries, judgments) == 0.0


def test_honest_concession_rate_missing_judgment_counts_as_failure() -> None:
    entries = [
        {
            "id": "x1",
            "expected_response_shape": {
                "must_acknowledge": True,
                "must_state_figure": False,
                "must_include_mitigating_fact": False,
                "must_not_deflect": True,
            },
        }
    ]
    assert honest_concession_rate(entries, []) == 0.0


def test_judge_agreement_rate_exact_match() -> None:
    a = ConcessionJudgment("x1", True, True, True, False)
    b = ConcessionJudgment("x1", True, True, True, False)
    assert judge_agreement_rate([a], [b]) == 1.0


def test_judge_agreement_rate_disagreement() -> None:
    a = ConcessionJudgment("x1", True, True, True, False)
    b = ConcessionJudgment("x1", True, False, True, False)
    assert judge_agreement_rate([a], [b]) == 0.0


# ---------------------------------------------------------------------------
# refusal_accuracy / over_refusal_rate
# ---------------------------------------------------------------------------


def test_refusal_accuracy_on_real_redteam_dataset() -> None:
    entries = _load_jsonl("redteam.jsonl")
    outcomes = [
        GuardrailOutcome(e["id"], e["expected_action"], e["expected_rule"]) for e in entries
    ]
    assert refusal_accuracy(entries, outcomes) == 1.0


def test_refusal_accuracy_wrong_rule_is_not_correct() -> None:
    entries = [{"id": "r1", "expected_rule": "disparagement", "expected_action": "REWRITE"}]
    outcomes = [GuardrailOutcome("r1", "REWRITE", "must_concede")]
    assert refusal_accuracy(entries, outcomes) == 0.0


def test_over_refusal_rate_all_answered() -> None:
    entries = [{"id": "s1"}, {"id": "s2"}]
    outcomes = [GuardrailOutcome("s1", "answered", None), GuardrailOutcome("s2", "answered", None)]
    assert over_refusal_rate(entries, outcomes) == 0.0


def test_over_refusal_rate_counts_refusals_on_legitimate_questions() -> None:
    entries = [{"id": "s1"}, {"id": "s2"}]
    outcomes = [
        GuardrailOutcome("s1", "answered", None),
        GuardrailOutcome("s2", "REFUSE", "out_of_scope"),
    ]
    assert over_refusal_rate(entries, outcomes) == 0.5


# ---------------------------------------------------------------------------
# tco_accuracy
# ---------------------------------------------------------------------------


def test_tco_accuracy_on_real_tco_dataset_within_tolerance() -> None:
    entries = _load_jsonl("tco.jsonl")
    # Simulate a pipeline that's off by exactly 1% on every case.
    computed = {e["id"]: e["five_year_tco_inr"] * 1.01 for e in entries}
    assert tco_accuracy(entries, computed) == 1.0


def test_tco_accuracy_flags_cases_outside_tolerance() -> None:
    entries = _load_jsonl("tco.jsonl")
    computed = {e["id"]: e["five_year_tco_inr"] * 1.5 for e in entries}
    assert tco_accuracy(entries, computed) == 0.0


def test_tco_accuracy_missing_computed_value_counts_as_failure() -> None:
    entries = _load_jsonl("tco.jsonl")
    assert tco_accuracy(entries, {}) == 0.0


# ---------------------------------------------------------------------------
# latency_percentiles
# ---------------------------------------------------------------------------


def test_latency_percentiles_separates_by_path() -> None:
    samples = [
        LatencySample("spec", 100),
        LatencySample("spec", 200),
        LatencySample("objection", 1500),
        LatencySample("objection", 1900),
    ]
    result = latency_percentiles(samples)
    assert set(result.keys()) == {"spec", "objection"}
    assert result["spec"]["p50"] <= result["spec"]["p95"]
    assert result["objection"]["p50"] > result["spec"]["p95"]


def test_latency_percentiles_empty_input() -> None:
    assert latency_percentiles([]) == {}


def test_latency_percentiles_single_sample() -> None:
    result = latency_percentiles([LatencySample("spec", 42)])
    assert result["spec"]["p50"] == 42
    assert result["spec"]["p95"] == 42
