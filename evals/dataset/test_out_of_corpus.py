import json
from pathlib import Path
from typing import Any

OOC_PATH = Path(__file__).parent / "out_of_corpus.jsonl"


def _load() -> list[dict[str, Any]]:
    with OOC_PATH.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_has_at_least_thirty_questions() -> None:
    assert len(_load()) >= 30


def test_ids_are_unique() -> None:
    records = _load()
    ids = [r["id"] for r in records]
    assert len(ids) == len(set(ids))


def test_every_record_has_the_required_fields() -> None:
    required = {"id", "category", "question", "missing_reason", "expected_behaviour"}
    for record in _load():
        assert required.issubset(record.keys()), record["id"]


def test_categories_are_from_the_allowed_set() -> None:
    allowed = {
        "safety_ratings",
        "warranty",
        "service_plan",
        "on_road_pricing",
        "ex30_competitor",
        "glc_not_sourced",
        "out_of_scope_brand",
    }
    for record in _load():
        assert record["category"] in allowed, record["id"]


def test_ex30_safety_award_question_is_flagged_as_partially_in_corpus() -> None:
    # The EX30 document itself states "Euro NCAP 5-star rating & IIHS Top
    # Safety Pick" as a brochure line, so a safety-rating question about the
    # EX30 specifically is NOT the same clean refusal case as every other
    # model — this must not be treated as a plain out-of-corpus question.
    records = {r["id"]: r for r in _load()}
    ex30_safety = [
        r
        for r in records.values()
        if r["category"] == "safety_ratings" and r.get("model") == "Volvo EX30"
    ]
    assert len(ex30_safety) == 1
    assert (
        "in-corpus" in ex30_safety[0]["missing_reason"]
        or "in-corpus" in ex30_safety[0]["expected_behaviour"]
    )
