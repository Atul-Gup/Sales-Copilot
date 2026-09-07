"""evals/run_ragas_eval.py — the RAGAS-style harness (T4.6).

Runs `ragas_metrics.py`'s four metrics against every entry in
`evals/dataset/ragas.jsonl` (T4.6's 30-example hand-labelled set, split
across the objection and document tracks per docs/RETRIEVAL.md) and reports:

- Each metric's mean, overall and per track.
- **Judge agreement**: docs/RETRIEVAL.md's explicit caveat — "RAGAS scores
  are LLM-judged and noisy. Hand-label 30 examples, compute agreement with
  the RAGAS judge, and report that agreement." An entry/metric pair "agrees"
  if the computed score and the hand label are within `AGREEMENT_TOLERANCE`
  (0.15) of each other; the reported rate is agreements over the full
  30-entries x 4-metrics grid.

See `ragas_metrics.py`'s module docstring for why "the RAGAS judge" here is
a deterministic lexical-overlap implementation of the same four metric
definitions rather than the `ragas` PyPI package's LLM-judged ones — no
`OPENAI_API_KEY` is available in this sandbox (same gap as T4.2c/T4.4),
and this is the harness that becomes meaningful the moment a real LLM judge
(RAGAS proper, or a hand-rolled prompt) is dropped in behind the same
function signatures.

Usage: `python -m evals.run_ragas_eval` (writes `evals/results/ragas_baseline.json`).
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

from evals.ragas_metrics import answer_relevancy, context_precision, context_recall, faithfulness

DATASET_PATH = Path(__file__).parent / "dataset" / "ragas.jsonl"
RESULTS_DIR = Path(__file__).parent / "results"

AGREEMENT_TOLERANCE = 0.15

METRIC_FUNCS: dict[str, Callable[[dict[str, Any]], float]] = {
    "faithfulness": lambda e: faithfulness(e["answer"], e["contexts"]),
    "answer_relevancy": lambda e: answer_relevancy(e["answer"], e["question"]),
    "context_precision": lambda e: context_precision(e["contexts"], e["ground_truth"]),
    "context_recall": lambda e: context_recall(e["contexts"], e["ground_truth"]),
}


def _load_dataset() -> list[dict[str, Any]]:
    with DATASET_PATH.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def score_entry(entry: dict[str, Any]) -> dict[str, float]:
    return {name: fn(entry) for name, fn in METRIC_FUNCS.items()}


def run_ragas_eval() -> dict[str, Any]:
    entries = _load_dataset()

    per_metric_scores: dict[str, list[float]] = defaultdict(list)
    per_track_metric_scores: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    agreements = 0
    total_comparisons = 0
    disagreements: list[dict[str, Any]] = []

    for entry in entries:
        computed = score_entry(entry)
        track = entry["track"]
        for metric, value in computed.items():
            per_metric_scores[metric].append(value)
            per_track_metric_scores[track][metric].append(value)

            hand_label = entry["hand_labels"][metric]
            total_comparisons += 1
            if abs(value - hand_label) <= AGREEMENT_TOLERANCE:
                agreements += 1
            else:
                disagreements.append(
                    {
                        "id": entry["id"],
                        "metric": metric,
                        "computed": round(value, 3),
                        "hand_label": hand_label,
                    }
                )

    return {
        "n_entries": len(entries),
        "n_document_track": sum(1 for e in entries if e["track"] == "document"),
        "n_objection_track": sum(1 for e in entries if e["track"] == "objection"),
        "judge": "deterministic-lexical-overlap-proxy (see ragas_metrics.py module "
        "docstring — NOT the ragas PyPI package's LLM-judged scores)",
        "judge_agreement_rate": agreements / total_comparisons,
        "agreement_tolerance": AGREEMENT_TOLERANCE,
        "metrics_overall": {m: sum(v) / len(v) for m, v in per_metric_scores.items()},
        "metrics_by_track": {
            track: {m: sum(v) / len(v) for m, v in metrics.items()}
            for track, metrics in per_track_metric_scores.items()
        },
        "disagreements": disagreements,
    }


def main() -> None:
    results = run_ragas_eval()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / "ragas_baseline.json"
    out_path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
