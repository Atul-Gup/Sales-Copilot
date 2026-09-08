"""evals/run_eval.py — T3.7: run whatever of the pipeline actually exists
today against the eval datasets, and write `evals/results/baseline.json` in
the shape `evals/diff_results.py` and `.github/workflows/eval.yml` expect:
`{"metrics": {name: {"value": float | None, "blocked_on": str | None, ...}}}`,
plus a `latency_ms` entry shaped `{"by_path": {path: {"p50": ..., "p95": ...}}}`.

This is deliberately NOT the full v1 improvement-narrative table docs/TASKS.md
describes — that needs generation (Phase 4: llm/client.py wired into a
retrieve -> generate -> verify_grounding loop), which doesn't exist yet.
Reporting fabricated numbers for hallucinated_fact_rate, citation_validity,
numeric_fidelity_rate, or honest_concession_rate — all of which require
scoring *generated text* this pipeline cannot yet produce — would be exactly
the kind of measured-vs-assumed dishonesty this project's guardrail design
argues against. Metrics that can't be computed yet get `"value": None` and a
`"blocked_on"` reason instead of a fabricated number; `diff_results.py`
renders that as "blocked on ..." next to the metric name rather than
silently showing a zero or a dash indistinguishable from a real result.

Makes real OpenAI embedding calls (retrieval) — a deliberate one-off run,
same as evals/calibrate_threshold.py, not collected by pytest or run in CI's
test step (CI's own eval step runs it deliberately, once, per PR).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from api.guardrails.input import run_input_guardrails, strip_prompt_injection
from api.models import Base
from api.services.retrieve import IN_CORPUS_THRESHOLD, hybrid_search_scored
from api.services.router import classify
from evals.metrics import in_corpus_recall, out_of_corpus_refusal_rate, refusal_accuracy
from ingest.product_docs import run as ingest_product_docs

DATASET_DIR = Path(__file__).parent / "dataset"
RESULTS_DIR = Path(__file__).parent / "results"

EXCLUDED_OOC_IDS = {"ooc_006"}  # documented EX30 mixed case, see calibrate_threshold.py

# Only these three rules check the raw incoming request rather than
# generated text (api/guardrails/input.py) — the other 10 rules in
# api/guardrails/rules.py are output-side checks with nothing to check yet.
INPUT_SIDE_RULE_IDS = {"prompt_injection", "out_of_scope", "customer_facing"}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _build_session_with_corpus() -> Session:
    engine = create_engine("sqlite:///:memory:")

    def _enable_fk(dbapi_connection: object, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    event.listen(engine, "connect", _enable_fk)
    Base.metadata.create_all(engine)
    session = Session(engine)
    for report in ingest_product_docs(session):
        if report.error is not None:
            print(f"ingest warning: {report.document_title}: {report.error}")
    session.flush()
    return session


def eval_retrieval_gate(session: Session) -> tuple[dict[str, Any], dict[str, list[float]]]:
    """Returns (gate metrics, per-intent-class retrieval latency samples in
    ms) — the latter is a retrieval-only proxy for docs/RETRIEVAL.md's
    per-intent-class latency requirement, not end-to-end (no generation
    exists yet to time)."""
    qa = _load_jsonl(DATASET_DIR / "qa.jsonl")
    ooc = [
        r
        for r in _load_jsonl(DATASET_DIR / "out_of_corpus.jsonl")
        if r["id"] not in EXCLUDED_OOC_IDS
    ]

    latency_by_intent: dict[str, list[float]] = {}

    def top_score(question: str) -> float:
        start = time.perf_counter()
        scored = hybrid_search_scored(question, session)
        elapsed_ms = (time.perf_counter() - start) * 1000
        intent = classify(question).value.lower()
        latency_by_intent.setdefault(intent, []).append(elapsed_ms)
        return scored[0].score if scored else 0.0

    qa_hits = [top_score(r["question"]) >= IN_CORPUS_THRESHOLD for r in qa]
    ooc_hits = [top_score(r["question"]) < IN_CORPUS_THRESHOLD for r in ooc]

    metrics = {
        "in_corpus_recall": {"value": in_corpus_recall(qa_hits), "n": len(qa)},
        "out_of_corpus_refusal_rate": {
            "value": out_of_corpus_refusal_rate(ooc_hits),
            "n": len(ooc),
        },
        # Same underlying check as in_corpus_recall, inverted — a genuine
        # proxy for over-refusal on qa.jsonl via the retrieval gate alone,
        # not the full refuse_gracefully pipeline (T4.5 doesn't exist yet).
        "over_refusal_rate": {
            "value": 1.0 - in_corpus_recall(qa_hits),
            "blocked_on": "proxy via retrieval gate only (T4.5 not wired) — see run_eval.py",
        },
    }
    return metrics, latency_by_intent


def eval_input_guardrails() -> dict[str, Any]:
    redteam = _load_jsonl(DATASET_DIR / "redteam.jsonl")
    entries = [r for r in redteam if r["expected_rule"] in INPUT_SIDE_RULE_IDS]

    matches = []
    for entry in entries:
        if entry["expected_rule"] == "prompt_injection":
            # prompt_injection never blocks by itself (strip_and_log), so it
            # never surfaces as run_input_guardrails' blocking result.
            result = strip_prompt_injection(entry["prompt"])
            matched = result is not None and result.action == entry["expected_action"]
        else:
            blocking, _sanitized = run_input_guardrails(entry["prompt"])
            matched = (
                blocking is not None
                and blocking.rule_id == entry["expected_rule"]
                and blocking.action == entry["expected_action"]
            )
        matches.append(matched)

    return {
        "value": refusal_accuracy(matches),
        "n": len(entries),
        "blocked_on": (
            f"partial: only {len(entries)} of 58 redteam.jsonl entries "
            "(prompt_injection/out_of_scope/customer_facing) are checkable "
            "without generation"
        ),
    }


NOT_YET_MEASURABLE: dict[str, str] = {
    "hallucinated_fact_rate": "requires generated text (T4.2)",
    "numeric_fidelity_rate": "requires generated text (T4.2, T4.4)",
    "citation_validity_rate": "requires generated text with citations (T4.2-T4.4)",
    "honest_concession_rate": "requires generated objection responses (T4.6)",
}


def main() -> None:
    session = _build_session_with_corpus()
    gate_metrics, latency_by_intent = eval_retrieval_gate(session)
    input_guardrail_metrics = eval_input_guardrails()

    metrics: dict[str, Any] = dict(gate_metrics)
    metrics["refusal_accuracy"] = input_guardrail_metrics
    for name, reason in NOT_YET_MEASURABLE.items():
        metrics[name] = {"value": None, "blocked_on": reason}

    metrics["latency_ms"] = {
        "by_path": {
            intent: {
                "p50": sorted(samples)[len(samples) // 2],
                "p95": sorted(samples)[min(int(len(samples) * 0.95), len(samples) - 1)],
            }
            for intent, samples in latency_by_intent.items()
            if samples
        }
    }

    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "baseline.json").write_text(
        json.dumps({"metrics": metrics}, indent=2) + "\n", encoding="utf-8"
    )

    for name, data in metrics.items():
        if name == "latency_ms":
            continue
        value = data.get("value")
        shown = f"{value:.2%}" if isinstance(value, float) else "N/A"
        blocked = f" (blocked on: {data['blocked_on']})" if data.get("blocked_on") else ""
        print(f"{name}: {shown}{blocked}")
    print(f"wrote {RESULTS_DIR / 'baseline.json'}")


if __name__ == "__main__":
    main()
