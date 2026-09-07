"""evals/diff_results.py — diff two `run_eval.py` results snapshots and render
the comparison as a markdown table (T3.7).

Used by `.github/workflows/eval.yml` to post the metric diff between the PR's
base branch and its head as a PR comment — "an aggregate pass/fail hides the
story; the diff is the improvement narrative T3.6 started."

Every metric in `run_eval.py`'s output is either a scalar `value` (float or
`None` when its pipeline doesn't exist yet — see run_eval.py's `blocked_on`)
or, for `latency_ms`, a `by_path` map of `{p50, p95}` per routing path. This
module treats both shapes explicitly rather than assuming every metric is a
bare number.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _format_value(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.4f}" if isinstance(value, float) and not value.is_integer() else f"{value:g}"


def _format_delta(before: float | None, after: float | None) -> str:
    if before is None or after is None:
        return "—"
    delta = after - before
    if delta == 0:
        return "no change"
    sign = "+" if delta > 0 else ""
    return f"{sign}{delta:.4f}"


def diff_metrics(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per scalar metric, plus one row per (path, percentile) in
    `latency_ms`. Rows for a metric present in only one snapshot still appear,
    with the missing side reported as `None` rather than skipped.
    """
    before_metrics = before.get("metrics", {})
    after_metrics = after.get("metrics", {})
    rows: list[dict[str, Any]] = []

    for name in sorted(set(before_metrics) | set(after_metrics)):
        if name == "latency_ms":
            continue
        b = before_metrics.get(name, {})
        a = after_metrics.get(name, {})
        rows.append(
            {
                "metric": name,
                "before": b.get("value"),
                "after": a.get("value"),
                "blocked_on": a.get("blocked_on") or b.get("blocked_on"),
            }
        )

    before_latency = before_metrics.get("latency_ms", {}).get("by_path", {})
    after_latency = after_metrics.get("latency_ms", {}).get("by_path", {})
    for path in sorted(set(before_latency) | set(after_latency)):
        for pct in ("p50", "p95"):
            rows.append(
                {
                    "metric": f"latency_ms.{path}.{pct}",
                    "before": before_latency.get(path, {}).get(pct),
                    "after": after_latency.get(path, {}).get(pct),
                    "blocked_on": None,
                }
            )

    return rows


def format_diff_markdown(rows: list[dict[str, Any]]) -> str:
    lines = [
        "| Metric | Before | After | Δ |",
        "| --- | --- | --- | --- |",
    ]
    for row in rows:
        metric = row["metric"]
        if row["blocked_on"] is not None:
            metric = f"{metric} *(blocked on {row['blocked_on']})*"
        lines.append(
            f"| {metric} | {_format_value(row['before'])} | {_format_value(row['after'])} "
            f"| {_format_delta(row['before'], row['after'])} |"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path, help="results JSON from the base branch")
    parser.add_argument("after", type=Path, help="results JSON from the PR head")
    args = parser.parse_args()

    before = json.loads(args.before.read_text(encoding="utf-8"))
    after = json.loads(args.after.read_text(encoding="utf-8"))
    print(format_diff_markdown(diff_metrics(before, after)))


if __name__ == "__main__":
    main()
