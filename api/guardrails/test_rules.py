"""api/guardrails/test_rules.py — one test per rule (T5.1).

docs/GUARDRAILS.md: "Each rule gets a test... A rule without a test is not
implemented." Each test below checks the rule's own data (id/action/category
match docs/GUARDRAILS.md exactly) and, where `evals/dataset/redteam.jsonl`
(T3.3) has entries tagged with that rule id, that every one of them expects
the same action this table declares — catching drift between the red-team
dataset and this rule table before it becomes a silent scoring bug in T5.4's
red-team run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from api.guardrails.rules import INPUT_RULES, OUTPUT_RULES, RULES, RULES_BY_ID, get_rule

REDTEAM_PATH = Path(__file__).parents[2] / "evals" / "dataset" / "redteam.jsonl"


def _redteam_entries() -> list[dict[str, Any]]:
    with REDTEAM_PATH.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _assert_action_matches_redteam(rule_id: str, expected_action: str) -> None:
    entries = [e for e in _redteam_entries() if e["expected_rule"] == rule_id]
    for entry in entries:
        assert entry["expected_action"] == expected_action, entry["id"]


def test_uncited_claim() -> None:
    rule = get_rule("uncited_claim")
    assert rule.action == "REWRITE"
    assert rule.category == "output"
    _assert_action_matches_redteam("uncited_claim", "REWRITE")


def test_cross_protocol_safety() -> None:
    rule = get_rule("cross_protocol_safety")
    assert rule.action == "REFUSE"
    assert rule.category == "output"
    _assert_action_matches_redteam("cross_protocol_safety", "REFUSE")


def test_disparagement() -> None:
    rule = get_rule("disparagement")
    assert rule.action == "REWRITE"
    assert rule.category == "output"
    _assert_action_matches_redteam("disparagement", "REWRITE")


def test_service_overstatement() -> None:
    rule = get_rule("service_overstatement")
    assert rule.action == "REFUSE"
    assert rule.category == "output"
    _assert_action_matches_redteam("service_overstatement", "REFUSE")


def test_on_road_price() -> None:
    rule = get_rule("on_road_price")
    assert rule.action == "ANNOTATE"
    assert rule.category == "output"
    _assert_action_matches_redteam("on_road_price", "ANNOTATE")


def test_delivery_promise() -> None:
    rule = get_rule("delivery_promise")
    assert rule.action == "REFUSE"
    assert rule.category == "output"
    _assert_action_matches_redteam("delivery_promise", "REFUSE")


def test_discount_promise() -> None:
    rule = get_rule("discount_promise")
    assert rule.action == "REFUSE"
    assert rule.category == "output"
    _assert_action_matches_redteam("discount_promise", "REFUSE")


def test_stale_data() -> None:
    rule = get_rule("stale_data")
    assert rule.action == "REFUSE"
    assert rule.category == "output"
    _assert_action_matches_redteam("stale_data", "REFUSE")


def test_must_concede() -> None:
    rule = get_rule("must_concede")
    assert rule.action == "REWRITE"
    assert rule.category == "output"
    _assert_action_matches_redteam("must_concede", "REWRITE")


def test_no_clinical_certainty() -> None:
    rule = get_rule("no_clinical_certainty")
    assert rule.action == "ANNOTATE"
    assert rule.category == "output"
    _assert_action_matches_redteam("no_clinical_certainty", "ANNOTATE")


def test_prompt_injection() -> None:
    rule = get_rule("prompt_injection")
    assert rule.action == "strip_and_log"
    assert rule.category == "input"
    _assert_action_matches_redteam("prompt_injection", "strip_and_log")


def test_out_of_scope() -> None:
    rule = get_rule("out_of_scope")
    assert rule.action == "REFUSE politely"
    assert rule.category == "input"
    _assert_action_matches_redteam("out_of_scope", "REFUSE politely")


def test_customer_facing() -> None:
    rule = get_rule("customer_facing")
    assert rule.action == "REFUSE"
    assert rule.category == "input"
    _assert_action_matches_redteam("customer_facing", "REFUSE")


def test_get_rule_raises_key_error_for_unknown_id() -> None:
    with pytest.raises(KeyError):
        get_rule("not_a_real_rule")


def test_output_rules_and_input_rules_partition_all_rules() -> None:
    assert set(OUTPUT_RULES) | set(INPUT_RULES) == set(RULES)
    assert set(OUTPUT_RULES).isdisjoint(INPUT_RULES)


def test_rules_by_id_is_keyed_correctly_and_has_no_duplicate_ids() -> None:
    assert len(RULES_BY_ID) == len(RULES)
    for rule_id, rule in RULES_BY_ID.items():
        assert rule.id == rule_id


def test_every_rule_id_from_guardrails_md_is_present() -> None:
    expected_ids = {
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
    assert {rule.id for rule in RULES} == expected_ids


def test_every_redteam_expected_rule_exists_in_the_rule_table() -> None:
    for entry in _redteam_entries():
        assert entry["expected_rule"] in RULES_BY_ID, entry["id"]
