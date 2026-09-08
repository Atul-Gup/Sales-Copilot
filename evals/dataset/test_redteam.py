import json
from pathlib import Path
from typing import Any

from api.guardrails.rules import RULES_BY_ID

REDTEAM_PATH = Path(__file__).parent / "redteam.jsonl"


def _load() -> list[dict[str, Any]]:
    with REDTEAM_PATH.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_has_at_least_forty_prompts() -> None:
    assert len(_load()) >= 40


def test_ids_are_unique() -> None:
    records = _load()
    ids = [r["id"] for r in records]
    assert len(ids) == len(set(ids))


def test_every_record_has_the_required_fields() -> None:
    required = {"id", "category", "prompt", "expected_rule", "expected_action", "notes"}
    for record in _load():
        assert required.issubset(record.keys()), record["id"]


def test_every_expected_rule_exists_in_the_rule_table() -> None:
    for record in _load():
        assert record["expected_rule"] in RULES_BY_ID, record["id"]


def test_every_rule_has_at_least_one_redteam_entry() -> None:
    # docs/GUARDRAILS.md: the red-team set should exercise every rule it
    # documents, not just the ones that were easy to phrase as a prompt.
    covered = {r["expected_rule"] for r in _load()}
    missing = set(RULES_BY_ID) - covered
    assert not missing, f"rules with no red-team coverage: {missing}"
