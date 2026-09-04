"""Ingest the Mercedes-Benz GLC from data/sources/competitors/mercedes-glc-spec.pdf.

Per docs/CORPUS.md, GLC is one of the XC60's three competitors — the only
Mercedes model in the corpus (no Mercedes entry exists for the EX30 set).

The brochure gives no ex-showroom price and describes upholstery/interior
options by variant rather than a priced standard/optional grid, so every
Variant here has ex_showroom_paise=None and no Feature rows.
"""

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from api.db import SessionLocal
from api.models import Brand, CarModel, Spec
from ingest.common import add_variant_with_specs, insert_source

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "sources" / "competitors"
INGESTED_AT = datetime(2026, 9, 4, tzinfo=UTC)

# Technical Data table, p.37 (cross-confirmed by the power/torque/0-100
# callouts on p.16). Dimensions L x W x H are shared across both variants.
TECHNICAL_DATA_PAGE = 37
SHARED_DIMENSIONS: list[tuple[str, float, str]] = [
    ("overall_length_mm", 4716, "mm"),
    ("overall_width_mm", 1890, "mm"),
    ("overall_height_mm", 1640, "mm"),
]
SHARED_TEXT_SPECS: list[tuple[str, str]] = [
    ("transmission", "9G-TRONIC"),
    ("drivetrain", "4MATIC (AWD)"),
]
VARIANTS: list[tuple[str, str, list[tuple[str, float, str]]]] = [
    (
        "GLC 220d 4MATIC",
        "diesel",
        [
            ("displacement_cc", 1993, "cc"),
            ("power_kw", 145, "kW"),
            ("power_hp", 197, "hp"),
            ("torque_nm", 440, "Nm"),
            ("acceleration_0_100_kmph_s", 8, "s"),
            ("top_speed_kmph", 219, "km/h"),
        ],
    ),
    (
        "GLC 300 4MATIC",
        "petrol",
        [
            ("displacement_cc", 1999, "cc"),
            ("power_kw", 190, "kW"),
            ("power_hp", 258, "hp"),
            ("torque_nm", 400, "Nm"),
            ("acceleration_0_100_kmph_s", 6.2, "s"),
            ("top_speed_kmph", 240, "km/h"),
        ],
    ),
]


def run(session: Session) -> None:
    source = insert_source(
        session,
        kind="oem_site",
        publisher="Mercedes-Benz India Private Limited",
        url="https://www.mercedes-benz.co.in/passengercars/models/suv/glc/overview.html",
        document_title="The Mercedes-Benz GLC Brochure",
        document_path=DATA_DIR / "mercedes-glc-spec.pdf",
        retrieved_at=INGESTED_AT,
        verified_at=INGESTED_AT,
    )

    brand = Brand(name="Mercedes-Benz", segment="luxury")
    session.add(brand)
    session.flush()

    model = CarModel(brand_id=brand.id, name="GLC", body_type="suv", status="active")
    session.add(model)
    session.flush()

    for name, powertrain, numeric_specs in VARIANTS:
        variant = add_variant_with_specs(
            session,
            model,
            source,
            name=name,
            powertrain=powertrain,
            page=TECHNICAL_DATA_PAGE,
            numeric_specs=SHARED_DIMENSIONS + numeric_specs,
            text_specs=SHARED_TEXT_SPECS,
        )
        # p.7 — wheel/tyre size, not tied to either variant specifically;
        # applied to both since no alternative is given anywhere else.
        session.add(
            Spec(
                variant_id=variant.id,
                attribute="wheel_and_tyre_size",
                value_text="19-inch 5-twin-spoke alloy, 235/55 R19",
                source_id=source.id,
                source_page=7,
                verified=True,
            )
        )
        # p.31 — airbag count, general to the model, not variant-specific.
        session.add(
            Spec(
                variant_id=variant.id,
                attribute="airbag_count",
                value_num=10,
                source_id=source.id,
                source_page=31,
                verified=True,
            )
        )


def main() -> None:
    with SessionLocal() as session:
        run(session)
        session.commit()


if __name__ == "__main__":
    main()
