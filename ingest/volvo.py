"""Ingest the Volvo India lineup (XC60, EX30) from data/sources/volvo/.

Manual entry from the official brochure PDFs, per docs/CORPUS.md and T1.4.
Only XC60.pdf and EX30.pdf are read here — Volvo Warranty.pdf is Corpus B
(document RAG, Phase 4) and Euro NCAP is out of scope for this ingest.

Neither brochure publishes an ex-showroom price, so every Variant here has
ex_showroom_paise=None and price_source_id=None. Both brochures are pure
marketing collateral with no options/pricing grid, so no Feature rows are
recorded from XC60 — see the module docstring on _ingest_xc60 for why. Where
the source itself is internally inconsistent (EX30's DC-charging figures),
the spec is still recorded, but verified=False with the conflict spelled
out in value_text rather than picking one number to present as fact.
"""

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from api.db import SessionLocal
from api.models import Brand, CarModel, Feature, Source, Spec, Variant
from ingest.common import insert_source

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "sources" / "volvo"
INGESTED_AT = datetime(2026, 9, 4, tzinfo=UTC)


def _ingest_xc60(session: Session, brand: Brand) -> None:
    """XC60.pdf (37 pages) is a lifestyle brochure, not a spec sheet.

    Its own disclaimer (p.36) states equipment shown "may now only be
    available at extra cost" without saying which — so no item in it can be
    confidently marked standard or optional. No Feature rows are ingested
    for this model as a result. No trim/grade name is given anywhere in the
    document either, so the single Variant below is named after the
    brochure's own cover title rather than an invented grade name.
    """
    source = insert_source(
        session,
        kind="oem_site",
        publisher="Volvo Auto India Pvt. Ltd.",
        url="https://www.volvocars.com/in/cars/xc60/",
        document_title="Volvo XC60 Mild Hybrid Brochure",
        document_path=DATA_DIR / "XC60.pdf",
        retrieved_at=INGESTED_AT,
        verified_at=INGESTED_AT,
    )

    model = CarModel(brand_id=brand.id, name="XC60", body_type="suv", status="active")
    session.add(model)
    session.flush()

    variant = Variant(
        model_id=model.id,
        name="XC60 Mild Hybrid",
        powertrain="mild_hybrid_petrol",
        ex_showroom_paise=None,
        price_source_id=None,
    )
    session.add(variant)
    session.flush()

    _add_specs(
        session,
        variant,
        source,
        verified=True,
        rows=[
            ("overall_length_mm", None, 4708, "mm", 36),
            ("wheelbase_mm", None, 2865, "mm", 36),
            ("overall_height_mm", None, 1653, "mm", 36),
            ("overall_width_mm", None, 1902, "mm", 36),
            ("overall_width_with_mirrors_mm", None, 2117, "mm", 36),
            ("ground_clearance_mm", None, 211, "mm", 36),
            ("centre_display_in", None, 11.2, "in", 4),
            ("driver_display_in", None, 12.3, "in", 4),
            ("transmission", "8-speed automatic (Geartronic)", None, None, 21),
            ("drivetrain", "all_wheel_drive", None, None, 22),
            ("audio_speaker_count", None, 15, "speakers", 13),
            ("audio_output_watts", None, 1410, "W", 13),
        ],
    )


def _ingest_ex30(session: Session, brand: Brand) -> None:
    """EX30.pdf (30 pages) is a photo-led brochure with a text layer too
    thin for pypdf to extract cleanly, so every page was rendered to an
    image and read visually. It explicitly states "single variant" (p.15),
    which is why only one Variant row exists here.
    """
    source = insert_source(
        session,
        kind="oem_site",
        publisher="Volvo Auto India Pvt. Ltd.",
        url="https://www.volvocars.com/in/cars/ex30-electric/",
        document_title="Volvo EX30 Pure Electric Brochure",
        document_path=DATA_DIR / "EX30.pdf",
        retrieved_at=INGESTED_AT,
        verified_at=INGESTED_AT,
    )

    model = CarModel(brand_id=brand.id, name="EX30", body_type="suv", status="active")
    session.add(model)
    session.flush()

    variant = Variant(
        model_id=model.id,
        name="EX30 Pure Electric",
        powertrain="battery_electric",
        ex_showroom_paise=None,
        price_source_id=None,
    )
    session.add(variant)
    session.flush()

    _add_specs(
        session,
        variant,
        source,
        verified=True,
        rows=[
            ("battery_capacity_kwh", None, 69, "kWh", 15),
            ("range_km", "up to 480 km", 480, "km", 14),
            ("acceleration_0_100_kmph_s", None, 5.3, "s", 14),
            ("power_kw", None, 200, "kW", 23),
            ("power_hp", None, 272, "hp", 23),
            ("torque_nm", None, 343, "Nm", 23),
            ("boot_capacity_l", None, 318, "L", 16),
            ("boot_capacity_folded_l", None, 904, "L", 16),
            ("frunk_capacity_l", None, 7, "L", 16),
            ("audio_speaker_count", None, 9, "speakers", 25),
            ("audio_output_watts", None, 1040, "W", 25),
            ("driver_display_in", None, 12.3, "in", 24),
        ],
    )
    # The brochure gives two different figures for DC fast-charging power and
    # time in two different places (p.15: "up to 153kW", "~26-28 minutes";
    # p.19: "150 kW", "just 25 minutes"). Recorded, not resolved — see
    # AGENTS.md rule on missing/uncertain data.
    _add_specs(
        session,
        variant,
        source,
        verified=False,
        rows=[
            (
                "dc_fast_charge_peak_kw",
                "p.15 says 'up to 153kW'; p.19 says '150 kW' — brochure is inconsistent",
                None,
                "kW",
                15,
            ),
            (
                "dc_fast_charge_10_80_time_min",
                "p.15 says '~26-28 minutes'; p.19 says 'just 25 minutes' — brochure is "
                "inconsistent",
                None,
                "min",
                19,
            ),
        ],
    )

    # p.27: "Two front USB-C ports (standard) + two rear USB-C ports (higher
    # trims)" — explicitly labelled, and the only feature in either Volvo
    # brochure with an unambiguous availability marker.
    session.add(
        Feature(
            variant_id=variant.id,
            feature_key="front_usb_c_ports",
            availability="standard",
            source_id=source.id,
            source_page=27,
        )
    )


def _add_specs(
    session: Session,
    variant: Variant,
    source: Source,
    *,
    verified: bool,
    rows: list[tuple[str, str | None, float | int | None, str | None, int]],
) -> None:
    for attribute, value_text, value_num, unit, page in rows:
        session.add(
            Spec(
                variant_id=variant.id,
                attribute=attribute,
                value_text=value_text,
                value_num=value_num,
                unit=unit,
                source_id=source.id,
                source_page=page,
                verified=verified,
            )
        )


def run(session: Session) -> None:
    brand = Brand(name="Volvo", segment="luxury")
    session.add(brand)
    session.flush()

    _ingest_xc60(session, brand)
    _ingest_ex30(session, brand)


def main() -> None:
    with SessionLocal() as session:
        run(session)
        session.commit()


if __name__ == "__main__":
    main()
