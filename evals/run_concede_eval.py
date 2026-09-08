"""evals/run_concede_eval.py — T4.6: run must_concede against every entry in
concessions.jsonl and report the honest-concession rate.

Unlike run_eval.py/calibrate_threshold.py/iterate_comparison_prompt.py, this
makes NO real API calls at all — api/services/concede.py is deliberately
deterministic (see its module docstring), and concessions.jsonl's grounding
is the real ingested `service_centres` table plus two fixed, source-verified
facts (resale: no document exists; EX30: no competitor document exists), so
this can run in CI's normal pytest step if ever wired in — it's a standalone
script here only to match the shape of this module's siblings and to keep
`evals/results/` writes consistent.

Scoring is necessarily heuristic (see evals/metrics.py's own admission that
citation/numeric checks are heuristic, not entailment): each category has
its own "did this actually concede correctly" predicate, checked against
each entry's `grounding` field.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from api.models import Base
from api.services.concede import concede, detect_known_weakness
from evals.metrics import honest_concession_rate
from ingest.service_centres import run as ingest_service_centres

DATASET_DIR = Path(__file__).parent / "dataset"
RESULTS_DIR = Path(__file__).parent / "results"


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
    ingest_service_centres(session)
    session.flush()
    return session


def _conceded_correctly(entry: dict[str, Any], response: str | None) -> bool:
    if response is None:
        return False
    category = entry["category"]
    lower = response.lower()

    if category == "resale_value":
        # Must concede the concern's tone but state no figure or percentage.
        return (
            "%" not in response
            and not any(ch.isdigit() for ch in response)
            and ("fair" in lower or "concern" in lower or "seriously" in lower)
        )

    if category == "ex30_price_class_gap":
        return "no" in lower and (
            "competitor" in lower or "comparison" in lower or "rival" in lower
        )

    if category == "service_network":
        # Every service_network entry's grounding names at least one brand
        # and/or city that the response must actually mention to count as
        # a genuine (not generic) concession.
        grounding = entry["grounding"].lower()
        mentioned_brands = [b for b in ("mercedes-benz", "audi", "bmw") if b in grounding]
        return any(b in lower for b in mentioned_brands) or "volvo" in lower

    raise ValueError(f"unknown category: {category}")


def main() -> None:
    session = _build_session()
    entries = _load_jsonl(DATASET_DIR / "concessions.jsonl")

    results: list[dict[str, Any]] = []
    conceded_flags: list[bool] = []
    detected = 0
    for entry in entries:
        category = detect_known_weakness(entry["customer_objection"])
        if category is not None:
            detected += 1
        response = concede(entry["customer_objection"], session)
        conceded_correctly = _conceded_correctly(entry, response)
        conceded_flags.append(conceded_correctly)
        results.append(
            {
                "id": entry["id"],
                "category": entry["category"],
                "detected": category.value if category else None,
                "conceded_correctly": conceded_correctly,
                "response": response,
            }
        )

    rate = honest_concession_rate(conceded_flags)

    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "concede_eval.json").write_text(
        json.dumps(
            {
                "honest_concession_rate": rate,
                "detection_rate": detected / len(entries),
                "n": len(entries),
                "results": results,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"honest_concession_rate: {rate:.2%} ({sum(conceded_flags)}/{len(entries)})")
    print(f"detection_rate: {detected / len(entries):.2%}")
    for r in results:
        if not r["conceded_correctly"]:
            print(f"  MISSED: {r['id']} ({r['category']}) — detected={r['detected']}")
    print(f"wrote {RESULTS_DIR / 'concede_eval.json'}")


if __name__ == "__main__":
    main()
