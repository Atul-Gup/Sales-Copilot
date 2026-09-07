"""Structural validation for `concessions.jsonl` (T3.2).

Not a model eval — `run_eval.py` (T3.6) does that once a generation pipeline
exists. This just guards the dataset itself: every entry is well-formed, no
id is duplicated, and a `grounded_in_corpus: true` entry actually carries the
sourced facts its concession claims are supposed to rest on. A dataset entry
that fails this test is not usable as eval ground truth regardless of what
the model under test does with it.
"""

import json
from pathlib import Path
from typing import Any

DATASET_PATH = Path(__file__).parent / "concessions.jsonl"

ALLOWED_CATEGORIES = {
    "service_network",
    "price_positioning",
    "resale_value",
    "brand_prestige",
    "waiting_period",
}

REQUIRED_KEYS = {
    "id",
    "category",
    "objection",
    "context",
    "customer_is_correct",
    "grounded_in_corpus",
    "grounding_facts",
    "expected_response_shape",
    "notes",
}

REQUIRED_SHAPE_KEYS = {
    "must_acknowledge",
    "must_state_figure",
    "must_include_mitigating_fact",
    "must_not_deflect",
}


def _load_entries() -> list[dict[str, Any]]:
    with DATASET_PATH.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_dataset_has_twenty_entries() -> None:
    assert len(_load_entries()) == 20


def test_every_entry_has_required_keys() -> None:
    for entry in _load_entries():
        missing = REQUIRED_KEYS - entry.keys()
        assert not missing, f"{entry.get('id')} missing keys: {missing}"


def test_ids_are_unique() -> None:
    ids = [entry["id"] for entry in _load_entries()]
    assert len(ids) == len(set(ids))


def test_categories_are_from_the_allowed_set() -> None:
    for entry in _load_entries():
        assert entry["category"] in ALLOWED_CATEGORIES, entry["id"]


def test_all_four_required_dimensions_are_covered() -> None:
    # T3.2: "Service network, resale, brand, waiting period" — price_positioning
    # is the EX30-vs-iX1 case docs/CORPUS.md explicitly asks to add, in addition
    # to those four.
    categories = {entry["category"] for entry in _load_entries()}
    assert {"service_network", "resale_value", "brand_prestige", "waiting_period"} <= categories


def test_expected_response_shape_has_all_flags() -> None:
    for entry in _load_entries():
        missing = REQUIRED_SHAPE_KEYS - entry["expected_response_shape"].keys()
        assert not missing, f"{entry['id']} missing shape flags: {missing}"


def test_grounded_entries_carry_at_least_one_sourced_fact() -> None:
    """A `must_state_figure` concession with no grounding fact would have
    nothing to check the generated figure against — that makes the entry
    useless as ground truth, not just incomplete."""
    for entry in _load_entries():
        if entry["expected_response_shape"]["must_state_figure"]:
            assert entry["grounding_facts"], f"{entry['id']} promises a figure but cites none"
            for fact in entry["grounding_facts"]:
                assert fact["claim"] and fact["source"], entry["id"]


def test_ungrounded_entries_do_not_promise_a_figure() -> None:
    """Categories with no ingested data (resale, brand prestige, waiting
    period per docs/CORPUS.md's scope) must not demand a specific number in
    the expected response — that would be asking the model to fabricate."""
    for entry in _load_entries():
        if not entry["grounded_in_corpus"]:
            assert entry["expected_response_shape"]["must_state_figure"] is False, entry["id"]


def test_pure_negative_controls_do_not_ask_for_acknowledgement() -> None:
    """A `customer_is_correct: false` entry usually means the premise is
    simply wrong (conc_020: Volvo does have a Mumbai centre) — conceding it
    would be a fabrication in the customer's favour instead of Volvo's, so
    `must_acknowledge` should be false.

    conc_010 is the one deliberate exception: the customer's *cherry-picking*
    accusation is wrong, but the *asymmetry* they're reacting to (EX30 has
    only one ingested competitor) is real, so a genuine acknowledgement is
    still correct there — `must_concede` isn't "agree with everything the
    customer implies" and isn't "agree with nothing either," so this dataset
    needs both a pure negative control and a mixed one.
    """
    for entry in _load_entries():
        if not entry["customer_is_correct"] and entry["id"] != "conc_010":
            assert entry["expected_response_shape"]["must_acknowledge"] is False, entry["id"]
