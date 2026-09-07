"""evals/test_run_redteam_eval.py — T5.4."""

from __future__ import annotations

from evals.run_redteam_eval import run_redteam_eval


def test_covers_every_redteam_entry() -> None:
    results = run_redteam_eval()
    assert results["n_prompts"] == 40
    assert sum(r["n"] for r in results["by_rule"].values()) == 40


def test_every_naive_response_is_flagged_as_a_before_violation() -> None:
    results = run_redteam_eval()
    for rule_id, counts in results["by_rule"].items():
        assert counts["before_violations"] == counts["n"], rule_id


def test_critical_rules_have_zero_after_violations() -> None:
    results = run_redteam_eval()
    for rule_id in ("cross_protocol_safety", "service_overstatement", "must_concede"):
        assert results["by_rule"][rule_id]["after_violations"] == 0
    assert results["critical_rules_clean"] is True


def test_every_rule_id_is_reported_even_with_zero_redteam_entries() -> None:
    results = run_redteam_eval()
    for rule_id in ("uncited_claim", "no_clinical_certainty", "stale_data", "customer_facing"):
        assert results["by_rule"][rule_id]["n"] == 0


def test_per_entry_ids_match_the_dataset() -> None:
    results = run_redteam_eval()
    assert len(results["per_entry"]) == 40
    assert all(e["id"].startswith("rt_") for e in results["per_entry"])
