"""evals/calibrate_threshold.py — T3.6: calibrate the `in_corpus?` gate's
threshold by sweeping it against `qa.jsonl` (should clear the bar) and
`out_of_corpus.jsonl` (should not), per docs/RETRIEVAL.md.

Makes real OpenAI embedding calls (one per corpus chunk, one per eval
question) — this is a deliberate one-off calibration run, not a unit test,
so it is not collected by pytest and is never run in CI. The threshold this
produces gets hand-copied into docs/RETRIEVAL.md once chosen; T4.5 is what
actually wires a gate function to it.

docs/RETRIEVAL.md originally called for sweeping "the reranker-score
threshold," but T2.2 dropped the cross-encoder reranker — there is no
reranker score to sweep. This calibrates against `hybrid_search_scored`'s
fused RRF score instead, which is the only per-query relevance signal this
pipeline actually produces without one.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from api.models import Base
from api.services.retrieve import hybrid_search_scored
from evals.metrics import in_corpus_recall, out_of_corpus_refusal_rate
from ingest.product_docs import run as ingest_product_docs

DATASET_DIR = Path(__file__).parent / "dataset"
RESULTS_DIR = Path(__file__).parent / "results"

# ooc_006 is deliberately excluded from calibration: it's the one
# out_of_corpus.jsonl entry docs/CORPUS.md flags as a mixed case (the EX30's
# safety-award line IS in-corpus) rather than a clean negative — including
# it would penalise a correctly-calibrated threshold for scoring it high.
EXCLUDED_OOC_IDS = {"ooc_006"}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _build_session() -> Session:
    engine = create_engine("sqlite:///:memory:")

    def _enable_fk(dbapi_connection: object, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    event.listen(engine, "connect", _enable_fk)
    Base.metadata.create_all(engine)
    return Session(engine)


def _top_score(question: str, session: Session) -> float:
    scored = hybrid_search_scored(question, session)
    return scored[0].score if scored else 0.0


def main() -> None:
    session = _build_session()
    reports = ingest_product_docs(session)
    for report in reports:
        if report.error is not None:
            print(f"ingest warning: {report.document_title}: {report.error}")
    session.flush()

    qa = _load_jsonl(DATASET_DIR / "qa.jsonl")
    ooc_all = _load_jsonl(DATASET_DIR / "out_of_corpus.jsonl")
    ooc = [r for r in ooc_all if r["id"] not in EXCLUDED_OOC_IDS]

    print(f"scoring {len(qa)} qa.jsonl and {len(ooc)} out_of_corpus.jsonl questions...")
    qa_scores = [(r["id"], _top_score(r["question"], session)) for r in qa]
    ooc_scores = [(r["id"], _top_score(r["question"], session)) for r in ooc]

    all_scores = sorted({s for _, s in qa_scores} | {s for _, s in ooc_scores})
    candidate_thresholds = sorted({round(s, 6) for s in all_scores} | {0.0})

    curve: list[dict[str, float]] = []
    for threshold in candidate_thresholds:
        recall = in_corpus_recall([score >= threshold for _, score in qa_scores])
        refusal = out_of_corpus_refusal_rate([score < threshold for _, score in ooc_scores])
        curve.append(
            {
                "threshold": threshold,
                "in_corpus_recall": recall,
                "out_of_corpus_refusal_rate": refusal,
            }
        )

    # Pick the threshold that clears both PRD targets (recall > 0.90,
    # refusal > 0.95) with the largest margin on whichever target is
    # tighter; if none clears both, report the best balanced-accuracy point
    # instead and say so plainly rather than picking a number that looks
    # chosen but isn't justified.
    both_targets_met = [
        row
        for row in curve
        if row["in_corpus_recall"] > 0.90 and row["out_of_corpus_refusal_rate"] > 0.95
    ]
    if both_targets_met:
        chosen = max(
            both_targets_met,
            key=lambda row: min(
                row["in_corpus_recall"] - 0.90, row["out_of_corpus_refusal_rate"] - 0.95
            ),
        )
        justification = "clears both docs/PRD.md §6 targets (recall > 90%, refusal > 95%)"
    else:
        chosen = max(
            curve, key=lambda row: row["in_corpus_recall"] + row["out_of_corpus_refusal_rate"]
        )
        justification = (
            "does NOT clear both docs/PRD.md §6 targets simultaneously at this corpus size — "
            "best balanced point available; retrieval/corpus work is needed before generation, "
            "not a threshold tweak"
        )

    RESULTS_DIR.mkdir(exist_ok=True)
    lines = [
        "# in_corpus? threshold calibration (T3.6)",
        "",
        f"Scored against {len(qa)} qa.jsonl questions and {len(ooc)} out_of_corpus.jsonl "
        f"questions (excluding {sorted(EXCLUDED_OOC_IDS)}, the documented mixed case).",
        "",
        "Signal: `hybrid_search_scored`'s fused RRF score (no reranker score exists post-T2.2).",
        "",
        "| threshold | in_corpus_recall | out_of_corpus_refusal_rate |",
        "|---|---|---|",
    ]
    for row in curve:
        lines.append(
            f"| {row['threshold']:.6f} | {row['in_corpus_recall']:.2%} | "
            f"{row['out_of_corpus_refusal_rate']:.2%} |"
        )
    lines += [
        "",
        f"**Chosen threshold: {chosen['threshold']:.6f}** — {justification}.",
        f"At this threshold: in_corpus_recall = {chosen['in_corpus_recall']:.2%}, "
        f"out_of_corpus_refusal_rate = {chosen['out_of_corpus_refusal_rate']:.2%}.",
    ]
    (RESULTS_DIR / "threshold_calibration.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nchosen threshold: {chosen['threshold']:.6f} ({justification})")
    print(f"wrote {RESULTS_DIR / 'threshold_calibration.md'}")


if __name__ == "__main__":
    main()
