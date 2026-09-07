"""Tests for evals/run_eval.py (T3.6).

Doesn't call main() / hit the filesystem for the results file — that's
exercised manually to produce the committed baseline. This checks that
build_results() runs the real spec/comparison path end-to-end against the
real ingested corpus and produces a well-formed results structure, including
the honest "not yet runnable" markers for metrics whose pipeline doesn't
exist.
"""

from evals.run_eval import (
    build_corpus_session,
    build_results,
    run_comparison_path,
    run_objection_path,
    run_spec_path,
)


def test_build_corpus_session_has_all_four_brands() -> None:
    db = build_corpus_session()
    try:
        from api.models import Brand

        names = {b.name for b in db.query(Brand).all()}
        assert names == {"Volvo", "BMW", "Mercedes-Benz", "Audi"}
    finally:
        db.close()


def test_run_spec_path_produces_claims_matching_facts() -> None:
    db = build_corpus_session()
    try:
        claims, facts, samples = run_spec_path(db)
        assert claims
        assert len(claims) == len(facts)
        for claim, fact in zip(claims, facts, strict=True):
            assert claim.variant_name == fact.variant_name
            assert claim.attribute == fact.attribute
            assert claim.value == fact.value
            assert claim.cited_source_id == fact.source_id
        assert all(s.path == "spec" for s in samples)
        assert len(samples) > 0
    finally:
        db.close()


def test_run_comparison_path_produces_latency_samples() -> None:
    db = build_corpus_session()
    try:
        samples = run_comparison_path(db)
        assert samples
        assert all(s.path == "comparison" for s in samples)
    finally:
        db.close()


def test_run_objection_path_produces_latency_samples() -> None:
    db = build_corpus_session()
    try:
        samples = run_objection_path(db, n_runs=3)
        assert len(samples) == 3
        assert all(s.path == "objection" for s in samples)
    finally:
        db.close()


def test_build_results_has_expected_shape() -> None:
    results = build_results()
    metrics = results["metrics"]

    assert metrics["hallucinated_spec_rate"]["value"] == 0.0
    assert metrics["hallucinated_spec_rate"]["n_claims"] > 0
    assert metrics["citation_validity"]["value"] == 1.0

    for blocked in (
        "honest_concession_rate",
        "judge_agreement_rate",
        "refusal_accuracy",
    ):
        assert metrics[blocked]["value"] is None
        assert "blocked_on" in metrics[blocked]

    assert metrics["tco_accuracy"]["value"] == 1.0
    assert metrics["tco_accuracy"]["n_dataset_entries"] == 30

    assert metrics["over_refusal_rate"]["value"] == 0.0
    assert metrics["over_refusal_rate"]["n_dataset_entries"] == 150
    assert metrics["over_refusal_rate"]["n_incorrectly_refused"] == 0

    latency = metrics["latency_ms"]["by_path"]
    assert set(latency.keys()) == {"spec", "comparison", "objection"}
    for path_stats in latency.values():
        assert path_stats["p50"] <= path_stats["p95"]
    assert metrics["latency_ms"]["n_objection_samples"] == 10
