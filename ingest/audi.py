"""Ingest the Audi Q5 from data/sources/competitors/audi-q5-specs.pdf.

Per docs/CORPUS.md, Q5 is one of the XC60's three competitors.

This is the one document in the corpus with an explicit availability
signal: every feature marked with a trailing "*" is captioned "*All
features marked (*) are only available in the Technology Variant" —
everything else is described as base equipment. That is used directly for
Feature.availability below. The document never names the base trim itself
(only "Technology Variant" is named), so this ingests a single generic Q5
Variant rather than inventing a base-trim name that isn't in the source.

No ex-showroom price and no cost figure for the Technology Variant package
or any individual optional feature appears anywhere in the document, so
ex_showroom_paise/price_source_id and every Feature.cost_paise are None.
"""

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from api.db import SessionLocal
from api.models import Brand, CarModel, Feature, Spec
from ingest.common import add_variant_with_specs, insert_source

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "sources" / "competitors"
INGESTED_AT = datetime(2026, 9, 4, tzinfo=UTC)

# "Technical Details" table, p.1 (single page PDF).
TECHNICAL_DATA_PAGE = 1
NUMERIC_SPECS: list[tuple[str, float, str]] = [
    ("displacement_cc", 1984, "cc"),
    ("power_kw", 195, "kW"),
    ("power_hp", 265, "hp"),
    ("torque_nm", 370, "Nm"),
    ("acceleration_0_100_kmph_s", 6.1, "s"),
    ("top_speed_kmph", 240, "km/h"),
    ("overall_length_mm", 4682, "mm"),
    ("overall_width_mm", 1893, "mm"),
    ("overall_height_mm", 1655, "mm"),
    ("wheelbase_mm", 2827, "mm"),
]
TEXT_SPECS: list[tuple[str, str]] = [
    ("engine_type", "2.0 L TFSI"),
    ("drivetrain", "quattro all-wheel drive"),
]

# Features explicitly marked "*" in the brochure — "only available in the
# Technology Variant" per its own footnote.
OPTIONAL_FEATURES = [
    "sensor_controlled_boot_lid_operation",
    "comfort_key_keyless_entry",
    "piano_black_decorative_inlays",
    "damper_control_suspension",
    "park_assist_360_camera",
    "power_front_seats_driver_memory",
    "bang_olufsen_3d_sound_system",
    "phone_box_wireless_charging",
    "mmi_navigation_plus_touch",
]
# Described without the "*" marker — base equipment per the document's own
# convention. quattro AWD and LED headlights are additionally called out in
# text as "a standard feature".
STANDARD_FEATURES = [
    "led_headlights",
    "quattro_all_wheel_drive",
    "panoramic_glass_sunroof",
    "audi_virtual_cockpit_plus",
    "leather_leatherette_upholstery",
]


def run(session: Session) -> None:
    source = insert_source(
        session,
        kind="oem_site",
        publisher="Audi India (a division of ŠKODA AUTO Volkswagen India Private Limited)",
        url="https://www.audi.in/en/models/q5/",
        document_title="Audi Q5 Brochure",
        document_path=DATA_DIR / "audi-q5-specs.pdf",
        retrieved_at=INGESTED_AT,
        verified_at=INGESTED_AT,
    )

    brand = Brand(name="Audi", segment="luxury")
    session.add(brand)
    session.flush()

    model = CarModel(brand_id=brand.id, name="Q5", body_type="suv", status="active")
    session.add(model)
    session.flush()

    variant = add_variant_with_specs(
        session,
        model,
        source,
        name="Q5",
        powertrain="petrol",
        page=TECHNICAL_DATA_PAGE,
        numeric_specs=NUMERIC_SPECS,
        text_specs=TEXT_SPECS,
    )
    session.add(
        Spec(
            variant_id=variant.id,
            attribute="airbag_count",
            value_num=8,
            source_id=source.id,
            source_page=TECHNICAL_DATA_PAGE,
            verified=True,
        )
    )

    for feature_key in OPTIONAL_FEATURES:
        session.add(
            Feature(
                variant_id=variant.id,
                feature_key=feature_key,
                availability="optional",
                source_id=source.id,
                source_page=1,
            )
        )
    for feature_key in STANDARD_FEATURES:
        session.add(
            Feature(
                variant_id=variant.id,
                feature_key=feature_key,
                availability="standard",
                source_id=source.id,
                source_page=1,
            )
        )


def main() -> None:
    with SessionLocal() as session:
        run(session)
        session.commit()


if __name__ == "__main__":
    main()
