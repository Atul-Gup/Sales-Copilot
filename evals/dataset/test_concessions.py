import json
from collections import Counter
from pathlib import Path
from typing import Any

import openpyxl

CONCESSIONS_PATH = Path(__file__).parent / "concessions.jsonl"
SHEET_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "data"
    / "sources"
    / "service centres"
    / "Volvo and its competitors service centre.xlsx"
)

# Mirrors ingest/service_centres.py's EXCLUDED_ROWS — the eval must reason
# about the same table the guardrail actually queries, not the raw sheet.
EXCLUDED_ROWS = {
    ("BMW", "BMW Deutsche Motoren | Whitefield Showroom Bengaluru"),
    ("Audi", "Audi Bhopal"),
}


def _load() -> list[dict[str, Any]]:
    with CONCESSIONS_PATH.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_has_at_least_twenty_objections() -> None:
    assert len(_load()) >= 20


def test_ids_are_unique() -> None:
    records = _load()
    ids = [r["id"] for r in records]
    assert len(ids) == len(set(ids))


def test_every_record_has_the_required_fields() -> None:
    required = {"id", "category", "customer_objection", "grounding", "expected_response_shape"}
    for record in _load():
        assert required.issubset(record.keys()), record["id"]


def test_categories_are_from_the_allowed_set() -> None:
    allowed = {"service_network", "resale_value", "ex30_price_class_gap"}
    for record in _load():
        assert record["category"] in allowed, record["id"]


def test_resale_value_entries_never_cite_a_specific_figure() -> None:
    # docs/GUARDRAILS.md: resale has no data source at all, so a concession
    # example that sneaks in a percentage or ranking would itself be the
    # fabrication the must_concede rule is supposed to prevent.
    for record in _load():
        if record["category"] == "resale_value":
            assert "%" not in record["grounding"]
            assert "%" not in record["expected_response_shape"]


def _ingested_service_centre_counts() -> Counter[str]:
    wb = openpyxl.load_workbook(SHEET_PATH, data_only=True)
    ws = wb["Service Centres"]
    counts: Counter[str] = Counter()
    for row in ws.iter_rows(min_row=2, values_only=True):
        brand, centre_name = str(row[1]), str(row[3])
        if (brand, centre_name) in EXCLUDED_ROWS:
            continue
        counts[brand] += 1
    return counts


def test_service_network_aggregate_counts_match_the_ingested_table() -> None:
    counts = _ingested_service_centre_counts()
    assert counts["Mercedes-Benz"] == 9
    assert counts["Audi"] == 6
    assert counts["Volvo"] == 5
    assert counts["BMW"] == 2
