"""api/services/tco.py — five-year total cost of ownership (T4.5).

`docs/GUARDRAILS.md`'s `no_clinical_certainty` rule: "Never present resale or
TCO projections as guaranteed. They're estimates with assumptions." Nothing
here is looked up from the database — `ex_showroom_paise` is null for every
ingested variant (T1.4) and no fuel-efficiency, insurance, or resale data is
ingested anywhere in the corpus (docs/CORPUS.md). Every number that goes into
this calculation is therefore a caller-supplied assumption, not a sourced
fact, and `TCOBreakdown` carries the assumptions it was computed from back
out alongside the result specifically so a caller can render them as an
editable panel next to the figure — never the figure alone.

Arithmetic matches `evals/dataset/tco.jsonl`'s 30 hand-computed cases exactly
(`evals/test_tco.py` checks every one within `evals/metrics.py::tco_accuracy`'s
2% tolerance): on-road price + 5 years of fuel/energy + 5 years of
maintenance + 5 years of insurance - resale value at year 5.
"""

from __future__ import annotations

from dataclasses import dataclass

YEARS = 5

ASSUMPTIONS_DISCLAIMER = (
    "This is an estimate built from the assumptions shown, not a guaranteed "
    "figure — on-road price, fuel/energy cost, maintenance, insurance, and "
    "resale value are all illustrative inputs a consultant can and should "
    "adjust for the actual customer."
)


@dataclass(frozen=True)
class TCOAssumptions:
    """Every input is an assumption, per the module docstring — none of
    these fields are read from `models.py`. Exactly one of the fuel pair
    (`fuel_efficiency_kmpl` + `fuel_price_per_litre_inr`) or the energy pair
    (`consumption_kwh_per_100km` + `electricity_price_per_kwh_inr`) must be
    set, matching whether the vehicle burns fuel or charges.
    """

    on_road_price_inr: float
    annual_km: float
    annual_maintenance_inr: float
    annual_insurance_inr: float
    five_year_retained_value_pct: float
    fuel_efficiency_kmpl: float | None = None
    fuel_price_per_litre_inr: float | None = None
    consumption_kwh_per_100km: float | None = None
    electricity_price_per_kwh_inr: float | None = None

    def __post_init__(self) -> None:
        has_fuel = (
            self.fuel_efficiency_kmpl is not None and self.fuel_price_per_litre_inr is not None
        )
        has_energy = (
            self.consumption_kwh_per_100km is not None
            and self.electricity_price_per_kwh_inr is not None
        )
        if has_fuel == has_energy:
            raise ValueError(
                "TCOAssumptions needs exactly one of the fuel pair "
                "(fuel_efficiency_kmpl, fuel_price_per_litre_inr) or the energy "
                "pair (consumption_kwh_per_100km, electricity_price_per_kwh_inr) set"
            )


@dataclass(frozen=True)
class TCOBreakdown:
    """The computed figure plus everything needed to render the assumptions
    panel and working next to it — never the headline number alone.
    """

    assumptions: TCOAssumptions
    annual_fuel_or_energy_inr: float
    five_year_fuel_or_energy_inr: float
    five_year_maintenance_inr: float
    five_year_insurance_inr: float
    five_year_resale_value_inr: float
    five_year_tco_inr: float
    working: list[str]
    disclaimer: str = ASSUMPTIONS_DISCLAIMER


def _rupees(value: float) -> str:
    return f"Rs{value:,.0f}"


def compute_five_year_tco(assumptions: TCOAssumptions) -> TCOBreakdown:
    a = assumptions

    if a.fuel_efficiency_kmpl is not None:
        fuel_price = a.fuel_price_per_litre_inr or 0.0
        annual_fuel_or_energy = a.annual_km / a.fuel_efficiency_kmpl * fuel_price
        energy_line = (
            f"Annual fuel cost = {a.annual_km:,.0f} km / {a.fuel_efficiency_kmpl} kmpl * "
            f"{_rupees(fuel_price)}/litre = {_rupees(annual_fuel_or_energy)}"
        )
    else:
        consumption = a.consumption_kwh_per_100km or 0.0
        electricity_price = a.electricity_price_per_kwh_inr or 0.0
        annual_fuel_or_energy = a.annual_km / 100 * consumption * electricity_price
        energy_line = (
            f"Annual energy cost = {a.annual_km:,.0f} km / 100 * {consumption} "
            f"kWh/100km * {_rupees(electricity_price)}/kWh = {_rupees(annual_fuel_or_energy)}"
        )

    five_year_fuel_or_energy = annual_fuel_or_energy * YEARS
    five_year_maintenance = a.annual_maintenance_inr * YEARS
    five_year_insurance = a.annual_insurance_inr * YEARS
    resale_value = a.on_road_price_inr * a.five_year_retained_value_pct
    tco = (
        a.on_road_price_inr
        + five_year_fuel_or_energy
        + five_year_maintenance
        + five_year_insurance
        - resale_value
    )

    fuel_line = (
        f"5-year fuel/energy cost = {_rupees(annual_fuel_or_energy)} * 5 = "
        f"{_rupees(five_year_fuel_or_energy)}"
    )
    maintenance_line = (
        f"5-year maintenance = {_rupees(a.annual_maintenance_inr)}/yr * 5 = "
        f"{_rupees(five_year_maintenance)}"
    )
    insurance_line = (
        f"5-year insurance = {_rupees(a.annual_insurance_inr)}/yr * 5 = "
        f"{_rupees(five_year_insurance)}"
    )
    resale_line = (
        f"Resale value at year 5 (assumption) = {_rupees(a.on_road_price_inr)} * "
        f"{a.five_year_retained_value_pct} = {_rupees(resale_value)}"
    )
    total_line = (
        "5-year TCO = on-road price + fuel/energy + maintenance + insurance - "
        f"resale value = {_rupees(a.on_road_price_inr)} + "
        f"{_rupees(five_year_fuel_or_energy)} + {_rupees(five_year_maintenance)} + "
        f"{_rupees(five_year_insurance)} - {_rupees(resale_value)} = {_rupees(tco)}"
    )
    working = [
        f"On-road price (assumption) = {_rupees(a.on_road_price_inr)}",
        energy_line,
        fuel_line,
        maintenance_line,
        insurance_line,
        resale_line,
        total_line,
    ]

    return TCOBreakdown(
        assumptions=a,
        annual_fuel_or_energy_inr=annual_fuel_or_energy,
        five_year_fuel_or_energy_inr=five_year_fuel_or_energy,
        five_year_maintenance_inr=five_year_maintenance,
        five_year_insurance_inr=five_year_insurance,
        five_year_resale_value_inr=resale_value,
        five_year_tco_inr=tco,
        working=working,
    )
