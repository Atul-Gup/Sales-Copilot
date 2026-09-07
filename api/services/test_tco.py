import json
from pathlib import Path
from typing import Any

import pytest

from api.services.tco import ASSUMPTIONS_DISCLAIMER, TCOAssumptions, compute_five_year_tco

TCO_DATASET_PATH = Path(__file__).parents[2] / "evals" / "dataset" / "tco.jsonl"


def _load_dataset() -> list[dict[str, Any]]:
    with TCO_DATASET_PATH.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _assumptions_from_entry(entry: dict[str, Any]) -> TCOAssumptions:
    a = entry["assumptions"]
    return TCOAssumptions(
        on_road_price_inr=a["on_road_price_inr"],
        annual_km=a["annual_km"],
        annual_maintenance_inr=a["annual_maintenance_inr"],
        annual_insurance_inr=a["annual_insurance_inr"],
        five_year_retained_value_pct=a["five_year_retained_value_pct"],
        fuel_efficiency_kmpl=a.get("fuel_efficiency_kmpl"),
        fuel_price_per_litre_inr=a.get("fuel_price_per_litre_inr"),
        consumption_kwh_per_100km=a.get("consumption_kwh_per_100km"),
        electricity_price_per_kwh_inr=a.get("electricity_price_per_kwh_inr"),
    )


@pytest.mark.parametrize("entry", _load_dataset(), ids=lambda e: e["id"])
def test_compute_five_year_tco_matches_hand_computed_dataset(entry: dict[str, Any]) -> None:
    breakdown = compute_five_year_tco(_assumptions_from_entry(entry))
    expected = entry["five_year_tco_inr"]
    assert abs(breakdown.five_year_tco_inr - expected) / expected <= 0.02


def test_dataset_has_30_hand_computed_cases() -> None:
    assert len(_load_dataset()) == 30


def test_fuel_powertrain_arithmetic() -> None:
    assumptions = TCOAssumptions(
        on_road_price_inr=1_000_000,
        annual_km=10_000,
        annual_maintenance_inr=20_000,
        annual_insurance_inr=22_000,
        five_year_retained_value_pct=0.5,
        fuel_efficiency_kmpl=10.0,
        fuel_price_per_litre_inr=100.0,
    )
    breakdown = compute_five_year_tco(assumptions)
    assert breakdown.annual_fuel_or_energy_inr == 100_000
    assert breakdown.five_year_fuel_or_energy_inr == 500_000
    assert breakdown.five_year_maintenance_inr == 100_000
    assert breakdown.five_year_insurance_inr == 110_000
    assert breakdown.five_year_resale_value_inr == 500_000
    assert breakdown.five_year_tco_inr == 1_210_000


def test_electric_powertrain_arithmetic() -> None:
    assumptions = TCOAssumptions(
        on_road_price_inr=1_000_000,
        annual_km=10_000,
        annual_maintenance_inr=20_000,
        annual_insurance_inr=22_000,
        five_year_retained_value_pct=0.5,
        consumption_kwh_per_100km=20.0,
        electricity_price_per_kwh_inr=8.0,
    )
    breakdown = compute_five_year_tco(assumptions)
    assert breakdown.annual_fuel_or_energy_inr == 16_000
    assert breakdown.five_year_fuel_or_energy_inr == 80_000


def test_rejects_neither_fuel_nor_energy_pair_set() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        TCOAssumptions(
            on_road_price_inr=1_000_000,
            annual_km=10_000,
            annual_maintenance_inr=20_000,
            annual_insurance_inr=22_000,
            five_year_retained_value_pct=0.5,
        )


def test_rejects_both_fuel_and_energy_pair_set() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        TCOAssumptions(
            on_road_price_inr=1_000_000,
            annual_km=10_000,
            annual_maintenance_inr=20_000,
            annual_insurance_inr=22_000,
            five_year_retained_value_pct=0.5,
            fuel_efficiency_kmpl=10.0,
            fuel_price_per_litre_inr=100.0,
            consumption_kwh_per_100km=20.0,
            electricity_price_per_kwh_inr=8.0,
        )


def test_breakdown_carries_assumptions_and_disclaimer_for_the_panel() -> None:
    assumptions = TCOAssumptions(
        on_road_price_inr=1_000_000,
        annual_km=10_000,
        annual_maintenance_inr=20_000,
        annual_insurance_inr=22_000,
        five_year_retained_value_pct=0.5,
        fuel_efficiency_kmpl=10.0,
        fuel_price_per_litre_inr=100.0,
    )
    breakdown = compute_five_year_tco(assumptions)
    assert breakdown.assumptions is assumptions
    assert breakdown.disclaimer == ASSUMPTIONS_DISCLAIMER
    assert "guaranteed" in breakdown.disclaimer
    assert len(breakdown.working) == 7
