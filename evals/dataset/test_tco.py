"""Structural + arithmetic validation for `tco.jsonl` (T3.4).

Not the eval itself — `metrics.py` (T3.5) checks `tco.py`'s output against
`five_year_tco_inr` within 2% per ARCHITECTURE.md's TCO-accuracy definition.
This just guards the dataset: every entry is well-formed, and — critically —
recomputing the formula from each entry's own `assumptions` reproduces its
own `five_year_tco_inr` exactly. A "hand-computed" case that doesn't
reproduce under its own stated formula is not usable as ground truth.
"""

import json
from pathlib import Path
from typing import Any

DATASET_PATH = Path(__file__).parent / "tco.jsonl"

REQUIRED_KEYS = {"id", "vehicle", "assumptions", "working", "five_year_tco_inr", "notes"}
REQUIRED_VEHICLE_KEYS = {"brand", "model", "variant", "powertrain"}

INSURANCE_RATE = 0.022


def _load_entries() -> list[dict[str, Any]]:
    with DATASET_PATH.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _recompute(entry: dict[str, Any]) -> int:
    a = entry["assumptions"]
    on_road = a["on_road_price_inr"]
    annual_km = a["annual_km"]

    if "consumption_kwh_per_100km" in a:
        annual_energy_cost = (
            annual_km / 100.0 * a["consumption_kwh_per_100km"] * a["electricity_price_per_kwh_inr"]
        )
    else:
        annual_energy_cost = annual_km / a["fuel_efficiency_kmpl"] * a["fuel_price_per_litre_inr"]

    fuel_5yr = annual_energy_cost * 5
    maintenance_5yr = a["annual_maintenance_inr"] * 5
    insurance_5yr = a["annual_insurance_inr"] * 5
    resale_value = round(on_road * a["five_year_retained_value_pct"])

    return int(round(on_road + fuel_5yr + maintenance_5yr + insurance_5yr - resale_value))


def test_dataset_has_thirty_entries() -> None:
    assert len(_load_entries()) == 30


def test_every_entry_has_required_keys() -> None:
    for entry in _load_entries():
        missing = REQUIRED_KEYS - entry.keys()
        assert not missing, f"{entry.get('id')} missing keys: {missing}"
        vehicle_missing = REQUIRED_VEHICLE_KEYS - entry["vehicle"].keys()
        assert not vehicle_missing, f"{entry['id']} vehicle missing: {vehicle_missing}"


def test_ids_are_unique() -> None:
    ids = [entry["id"] for entry in _load_entries()]
    assert len(ids) == len(set(ids))


def test_each_entry_has_exactly_one_fuel_model() -> None:
    """An entry is either an EV (energy consumption + electricity price) or
    an ICE (fuel efficiency + fuel price), never both and never neither —
    otherwise the arithmetic in `working` is ambiguous."""
    for entry in _load_entries():
        a = entry["assumptions"]
        is_ev = "consumption_kwh_per_100km" in a
        is_ice = "fuel_efficiency_kmpl" in a
        assert is_ev != is_ice, entry["id"]


def test_insurance_matches_stated_rate() -> None:
    for entry in _load_entries():
        a = entry["assumptions"]
        expected = round(a["on_road_price_inr"] * INSURANCE_RATE)
        assert a["annual_insurance_inr"] == expected, entry["id"]


def test_five_year_tco_reproduces_from_assumptions() -> None:
    """The core check: hand-recomputing the formula from an entry's own
    `assumptions` must land on its own `five_year_tco_inr` exactly (integer
    rupees, no tolerance) — this is what makes it usable as the ground
    truth `tco.py`'s output gets compared against within 2%."""
    for entry in _load_entries():
        assert _recompute(entry) == entry["five_year_tco_inr"], entry["id"]


def test_covers_all_seven_ingested_variants() -> None:
    """T3.4 says cover the lineup — this checks every ingested variant
    (XC60, EX30, X3 x2, GLC x2, Q5, per ingest/volvo.py, bmw.py, mercedes.py,
    audi.py) has at least one TCO case, not just a subset."""
    variants = {(e["vehicle"]["model"], e["vehicle"]["variant"]) for e in _load_entries()}
    expected = {
        ("XC60", "XC60 Mild Hybrid"),
        ("EX30", "EX30 Pure Electric"),
        ("X3", "X3 xDrive20"),
        ("X3", "X3 xDrive20d"),
        ("GLC", "GLC 220d 4MATIC"),
        ("GLC", "GLC 300 4MATIC"),
        ("Q5", "Q5"),
    }
    assert expected <= variants


def test_assumptions_are_flagged_as_illustrative() -> None:
    """Every entry's notes must say these are assumptions, not sourced
    facts — otherwise a reader could mistake a TCO figure for something as
    citation-backed as a spec row, which it structurally cannot be (no
    price, fuel-efficiency, insurance, or resale data is ingested)."""
    for entry in _load_entries():
        notes = entry["notes"].lower()
        assert "illustrative" in notes or "assumption" in notes, entry["id"]
