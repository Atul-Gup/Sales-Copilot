"""Structural validation for `redteam.jsonl` (T3.3).

Not a guardrail eval — `run_eval.py` (T3.6) and the guardrail implementation
(T5.1-T5.4) do that once they exist. This guards the dataset itself: every
entry is well-formed, no id is duplicated, every `expected_rule` is a real
rule ID from `docs/GUARDRAILS.md`, and the category counts match the
breakdown GUARDRAILS.md specifies for the 40-prompt red team set.
"""

import json
from collections import Counter
from pathlib import Path
from typing import Any

DATASET_PATH = Path(__file__).parent / "redteam.jsonl"

# Rule IDs from docs/GUARDRAILS.md's output and input rule tables.
ALLOWED_RULES = {
    "uncited_claim",
    "cross_protocol_safety",
    "disparagement",
    "service_overstatement",
    "on_road_price",
    "delivery_promise",
    "discount_promise",
    "stale_data",
    "must_concede",
    "no_clinical_certainty",
    "prompt_injection",
    "out_of_scope",
    "customer_facing",
}

ALLOWED_ACTIONS = {"REFUSE", "REWRITE", "ANNOTATE", "strip_and_log", "REFUSE politely"}

REQUIRED_KEYS = {"id", "category", "prompt", "expected_rule", "expected_action", "notes"}

# docs/GUARDRAILS.md's own breakdown of the 40-prompt red team set.
EXPECTED_CATEGORY_COUNTS = {
    "disparagement": 8,
    "cross_protocol_safety": 5,
    "service_overstatement": 6,
    "on_road_price": 2,
    "delivery_promise": 2,
    "discount_promise": 3,
    "prompt_injection": 6,
    "concession_evasion": 5,
    "out_of_scope": 3,
}


def _load_entries() -> list[dict[str, Any]]:
    with DATASET_PATH.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_dataset_has_forty_entries() -> None:
    assert len(_load_entries()) == 40


def test_every_entry_has_required_keys() -> None:
    for entry in _load_entries():
        missing = REQUIRED_KEYS - entry.keys()
        assert not missing, f"{entry.get('id')} missing keys: {missing}"


def test_ids_are_unique() -> None:
    ids = [entry["id"] for entry in _load_entries()]
    assert len(ids) == len(set(ids))


def test_expected_rule_is_a_real_guardrail_id() -> None:
    for entry in _load_entries():
        assert entry["expected_rule"] in ALLOWED_RULES, entry["id"]


def test_expected_action_is_a_real_action() -> None:
    for entry in _load_entries():
        assert entry["expected_action"] in ALLOWED_ACTIONS, entry["id"]


def test_category_counts_match_guardrails_breakdown() -> None:
    counts = Counter(entry["category"] for entry in _load_entries())
    assert dict(counts) == EXPECTED_CATEGORY_COUNTS


def test_price_and_promise_categories_map_to_their_own_rule() -> None:
    """on_road_price/delivery_promise/discount_promise are three distinct
    output rules in GUARDRAILS.md, not one generic 'price_and_promises' rule
    — each entry's expected_rule must match its own category, not a sibling's."""
    for entry in _load_entries():
        if entry["category"] in {"on_road_price", "delivery_promise", "discount_promise"}:
            assert entry["expected_rule"] == entry["category"], entry["id"]


def test_concession_evasion_maps_to_must_concede() -> None:
    for entry in _load_entries():
        if entry["category"] == "concession_evasion":
            assert entry["expected_rule"] == "must_concede", entry["id"]


def test_injection_prompts_are_framed_as_customer_messages() -> None:
    """GUARDRAILS.md: the injection rule applies to instruction-like text
    inside *pasted customer messages*, not to the consultant's own direct
    requests — each entry must actually be framed that way to test the
    right thing."""
    for entry in _load_entries():
        if entry["category"] == "prompt_injection":
            assert entry["prompt"].startswith("Customer message:"), entry["id"]


def test_no_ingested_models_outside_the_real_lineup() -> None:
    """docs/GUARDRAILS.md's own illustrative prompts name XC90 and EX40,
    neither of which is actually ingested (only XC60 and EX30 are, per
    ingest/volvo.py) — copying those uncritically would build the eval on
    cars the system has no data for. This dataset sticks to the real
    ingested set: XC60, EX30, X3, GLC, Q5."""
    banned = ["XC90", "EX40", "iX1"]
    for entry in _load_entries():
        for term in banned:
            assert term not in entry["prompt"], f"{entry['id']} references un-ingested {term}"
