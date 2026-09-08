"""evals/run_over_refusal_eval.py — T5.5: over-refusal check against
qa.jsonl, reported alongside in_corpus_recall per evals/metrics.py's own
docstring ("must be reported beside refusal_accuracy always — over-cautious
guardrails are a broken product, not a safe one").

Every qa.jsonl question is genuinely answerable from the ingested corpus
(T3.1) — a refusal here is always wrong, whether it comes from the
`in_corpus?` gate, the T5.4 framing-pressure override, or an output
guardrail refusing after two failed generation attempts. Runs the REAL
pipeline end to end (not just the retrieval gate, unlike T3.7's
`eval_retrieval_gate`) so a guardrail-caused over-refusal is caught too, not
just a retrieval-caused one.

If over_refusal_rate exceeds 5% (docs/TASKS.md's T5.5 threshold), the
threshold or a guardrail is too tight and both need retuning together — see
this script's `main()` for what it does in that case.

Makes real OpenAI calls (embeddings + generation for all 32 qa.jsonl
questions) — a deliberate one-off run, same as its `evals/` siblings. Not
collected by pytest or run in CI.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from api.llm.client import LLMClient
from api.models import Base
from api.services.pipeline import answer
from evals.metrics import in_corpus_recall, over_refusal_rate
from ingest.product_docs import run as ingest_product_docs
from ingest.service_centres import run as ingest_service_centres

DATASET_DIR = Path(__file__).parent / "dataset"
RESULTS_DIR = Path(__file__).parent / "results"

OVER_REFUSAL_CEILING = 0.05


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
    session = Session(engine)
    for report in ingest_product_docs(session):
        if report.error is not None:
            print(f"ingest warning: {report.document_title}: {report.error}")
    ingest_service_centres(session)
    session.flush()
    return session


def main() -> None:
    session = _build_session()
    llm = LLMClient()
    qa = _load_jsonl(DATASET_DIR / "qa.jsonl")

    results: list[dict[str, Any]] = []
    incorrectly_refused: list[bool] = []
    answered_correctly: list[bool] = []
    for entry in qa:
        result = answer(entry["question"], session, llm=llm)
        incorrectly_refused.append(result.refused)
        answered_correctly.append(not result.refused)
        results.append(
            {
                "id": entry["id"],
                "question": entry["question"],
                "refused": result.refused,
                "blocked_by_input_guardrail": result.blocked_by_input_guardrail,
                "top_score": result.top_score,
            }
        )

    over_rate = over_refusal_rate(incorrectly_refused)
    recall = in_corpus_recall(answered_correctly)

    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "over_refusal_eval.json").write_text(
        json.dumps(
            {
                "over_refusal_rate": over_rate,
                "in_corpus_recall": recall,
                "n": len(qa),
                "ceiling": OVER_REFUSAL_CEILING,
                "over_ceiling": over_rate > OVER_REFUSAL_CEILING,
                "results": results,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"over_refusal_rate: {over_rate:.2%} (ceiling: {OVER_REFUSAL_CEILING:.0%})")
    print(f"in_corpus_recall: {recall:.2%}  (must be reported together, per evals/metrics.py)")
    for r in results:
        if r["refused"]:
            reason = (
                r["blocked_by_input_guardrail"] or f"gate/guardrail, top_score={r['top_score']}"
            )
            print(f"  WRONGLY REFUSED: {r['id']} ({reason}) — {r['question']}")
    if over_rate > OVER_REFUSAL_CEILING:
        print("\nOVER CEILING — threshold and/or guardrails need retuning.")
    else:
        print("\nWithin the 5% ceiling — no retuning needed.")
    print(f"wrote {RESULTS_DIR / 'over_refusal_eval.json'}")


if __name__ == "__main__":
    main()
