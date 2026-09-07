"""evals/dataset/test_specs.py — structural checks on specs.jsonl (T3.1)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PATH = Path(__file__).parent / "specs.jsonl"


def _entries() -> list[dict[str, Any]]:
    with PATH.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_has_150_entries() -> None:
    assert len(_entries()) == 150


def test_every_entry_has_required_keys() -> None:
    for entry in _entries():
        assert set(entry) == {"id", "category", "question", "answer", "source_ids"}


def test_ids_are_unique() -> None:
    ids = [e["id"] for e in _entries()]
    assert len(ids) == len(set(ids))


def test_covers_every_category() -> None:
    categories = {e["category"] for e in _entries()}
    assert categories == {
        "spec",
        "feature",
        "safety",
        "price",
        "service_coverage",
        "comparison",
    }


def test_covers_volvo_and_all_three_competitors() -> None:
    all_text = " ".join(e["question"] for e in _entries()).lower()
    for brand in ("volvo", "bmw", "mercedes", "audi"):
        assert brand in all_text


def test_price_entries_never_fabricate_a_figure() -> None:
    for entry in _entries():
        if entry["category"] == "price":
            assert "not sourced" in entry["answer"].lower()
