"""Ingest the BMW X3 from data/sources/competitors/bmw-x3-specs.pdf.

Per docs/CORPUS.md, X3 is one of the XC60's three competitors. The other
file in this directory, bmw-ix1-specs.pdf, is skipped entirely this
session: it turned out on inspection to be the BMW X1 Long Wheelbase (a
petrol ICE model), not the iX1 electric SUV that CORPUS.md names as the
EX30's sole competitor. Ingesting it under the "iX1" label would have
paired an ICE competitor against the EX30 EV — flagged and held rather
than guessed at.

The brochure gives no ex-showroom price and no priced options grid, so
every Variant here has ex_showroom_paise=None and no Feature rows.
"""

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from api.db import SessionLocal
from api.models import Brand, CarModel
from ingest.common import add_variant_with_specs, insert_source

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "sources" / "competitors"
INGESTED_AT = datetime(2026, 9, 4, tzinfo=UTC)

# Technical Information table, p.10 — body dimensions are shared across
# both engine variants; power/torque/performance differ per variant.
PAGE = 10
SHARED_DIMENSIONS: list[tuple[str, float, str]] = [
    ("overall_length_mm", 4755, "mm"),
    ("wheelbase_mm", 2865, "mm"),
]
SHARED_TEXT_SPECS: list[tuple[str, str]] = [
    ("transmission", "8-Speed Automatic"),
    ("drivetrain", "xDrive All-Wheel Drive"),
    ("has_48v_mild_hybrid_system", "yes"),
]
VARIANTS: list[tuple[str, str, list[tuple[str, float, str]]]] = [
    (
        "X3 xDrive20",
        "petrol",
        [
            ("power_kw", 140, "kW"),
            ("power_hp", 188, "hp"),
            ("torque_nm", 310, "Nm"),
            ("acceleration_0_100_kmph_s", 7.8, "s"),
            ("top_speed_kmph", 215, "km/h"),
        ],
    ),
    (
        "X3 xDrive20d",
        "diesel",
        [
            ("power_kw", 145, "kW"),
            ("power_hp", 197, "hp"),
            ("torque_nm", 400, "Nm"),
            ("acceleration_0_100_kmph_s", 7.7, "s"),
            ("top_speed_kmph", 215, "km/h"),
        ],
    ),
]


def run(session: Session) -> None:
    source = insert_source(
        session,
        kind="oem_site",
        publisher="BMW India",
        url="https://www.bmw.in/en/all-models/x-series/x3/bmw-x3.html",
        document_title="The BMW X3 Brochure",
        document_path=DATA_DIR / "bmw-x3-specs.pdf",
        retrieved_at=INGESTED_AT,
        verified_at=INGESTED_AT,
    )

    brand = Brand(name="BMW", segment="luxury")
    session.add(brand)
    session.flush()

    model = CarModel(brand_id=brand.id, name="X3", body_type="suv", status="active")
    session.add(model)
    session.flush()

    for name, powertrain, numeric_specs in VARIANTS:
        add_variant_with_specs(
            session,
            model,
            source,
            name=name,
            powertrain=powertrain,
            page=PAGE,
            numeric_specs=SHARED_DIMENSIONS + numeric_specs,
            text_specs=SHARED_TEXT_SPECS,
        )


def main() -> None:
    with SessionLocal() as session:
        run(session)
        session.commit()


if __name__ == "__main__":
    main()
