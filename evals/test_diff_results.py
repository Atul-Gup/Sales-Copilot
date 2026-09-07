from evals.diff_results import diff_metrics, format_diff_markdown

BEFORE = {
    "metrics": {
        "hallucinated_spec_rate": {"value": 0.0, "n_claims": 80},
        "tco_accuracy": {"value": None, "blocked_on": "T4.5 (services/tco.py)"},
        "latency_ms": {
            "by_path": {
                "spec": {"p50": 1.0, "p95": 2.0},
                "comparison": {"p50": 1.5, "p95": 2.5},
            }
        },
    }
}

AFTER = {
    "metrics": {
        "hallucinated_spec_rate": {"value": 0.05, "n_claims": 85},
        "tco_accuracy": {"value": None, "blocked_on": "T4.5 (services/tco.py)"},
        "latency_ms": {
            "by_path": {
                "spec": {"p50": 1.2, "p95": 2.1},
                "comparison": {"p50": 1.5, "p95": 2.5},
            }
        },
    }
}


def test_diff_metrics_reports_scalar_change() -> None:
    rows = diff_metrics(BEFORE, AFTER)
    row = next(r for r in rows if r["metric"] == "hallucinated_spec_rate")
    assert row["before"] == 0.0
    assert row["after"] == 0.05
    assert row["blocked_on"] is None


def test_diff_metrics_carries_blocked_on() -> None:
    rows = diff_metrics(BEFORE, AFTER)
    row = next(r for r in rows if r["metric"] == "tco_accuracy")
    assert row["before"] is None
    assert row["after"] is None
    assert row["blocked_on"] == "T4.5 (services/tco.py)"


def test_diff_metrics_expands_latency_by_path_and_percentile() -> None:
    rows = diff_metrics(BEFORE, AFTER)
    names = {r["metric"] for r in rows}
    assert "latency_ms.spec.p50" in names
    assert "latency_ms.spec.p95" in names
    assert "latency_ms.comparison.p50" in names
    assert "latency_ms.comparison.p95" in names
    changed = next(r for r in rows if r["metric"] == "latency_ms.spec.p50")
    assert changed["before"] == 1.0
    assert changed["after"] == 1.2
    unchanged = next(r for r in rows if r["metric"] == "latency_ms.comparison.p50")
    assert unchanged["before"] == unchanged["after"] == 1.5


def test_diff_metrics_handles_metric_missing_from_one_side() -> None:
    before = {"metrics": {"refusal_accuracy": {"value": 0.9}}}
    after: dict[str, dict[str, dict[str, float]]] = {"metrics": {}}
    rows = diff_metrics(before, after)
    row = next(r for r in rows if r["metric"] == "refusal_accuracy")
    assert row["before"] == 0.9
    assert row["after"] is None


def test_format_diff_markdown_renders_a_table_with_delta() -> None:
    rows = diff_metrics(BEFORE, AFTER)
    markdown = format_diff_markdown(rows)
    assert markdown.startswith("| Metric | Before | After | Δ |")
    assert "hallucinated_spec_rate" in markdown
    assert "+0.0500" in markdown
    assert "no change" in markdown
    assert "*(blocked on T4.5 (services/tco.py))*" in markdown
