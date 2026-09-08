import json
from pathlib import Path
from typing import Any

QA_PATH = Path(__file__).parent / "qa.jsonl"


def _load() -> list[dict[str, Any]]:
    with QA_PATH.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_has_at_least_thirty_questions() -> None:
    assert len(_load()) >= 30


def test_ids_are_unique() -> None:
    records = _load()
    ids = [r["id"] for r in records]
    assert len(ids) == len(set(ids))


def test_every_record_has_the_required_fields() -> None:
    required = {
        "id",
        "model",
        "category",
        "question",
        "expected_answer",
        "expected_values",
        "source_section",
    }
    for record in _load():
        assert required.issubset(record.keys()), record["id"]


def test_categories_are_from_the_allowed_set() -> None:
    allowed = {"dimensions", "powertrain", "features"}
    for record in _load():
        assert record["category"] in allowed, record["id"]


def test_no_pricing_category_present() -> None:
    # docs/CORPUS.md: no product document contains pricing data, so a
    # "pricing" category here would mean an unanswerable question snuck in.
    for record in _load():
        assert record["category"] != "pricing", record["id"]


def test_every_numeric_expected_value_has_a_unit_and_label() -> None:
    for record in _load():
        for value in record["expected_values"]:
            assert {"value", "unit", "label"}.issubset(value.keys()), record["id"]


def test_models_are_limited_to_the_four_available_documents() -> None:
    # Mercedes GLC has no PDF sourced yet (see docs/CORPUS.md) so it cannot
    # appear here without fabricating unanswerable questions.
    allowed_models = {"Volvo XC60", "Volvo EX30", "BMW X3", "Audi Q5"}
    for record in _load():
        assert record["model"] in allowed_models, record["id"]
