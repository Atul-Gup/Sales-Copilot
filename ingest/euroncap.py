"""Ingest Euro NCAP ratings from data/sources/euroncap/.

Per docs/CORPUS.md and T1.6. Ratings are only created for models that
already exist in the database (XC60, EX30, GLC, Q5 — from ingest/volvo.py,
ingest/mercedes.py, ingest/audi.py), and only where the source document is
actually about that model.

Two of the six files CORPUS.md asks for are skipped this session:
"Euro NCAP _ BMW 3 Series.pdf" and "Euro NCAP _ BMW iX.pdf" are not the X3
and iX1 the corpus needs — they are the 3 Series sedan (Large Family Car
class) and the (large) iX SUV, different models entirely. No X3 or iX1
SafetyRating rows are created; that needs the correct source documents,
and X3 has no Euro NCAP source in the corpus at all right now.

The XC60 rating is the documented "landmine": tested on the D4 AWD diesel
(LHD, Momentum trim) — not the petrol mild-hybrid Volvo India actually
sells — published 2017, and expired 2024-01-01. Recorded exactly as the
report states, status='expired', so guardrails/rules.py has what it needs
to never present it as current.
"""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.db import SessionLocal
from api.models import Brand, CarModel, SafetyRating
from ingest.common import insert_source

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "sources" / "euroncap"
INGESTED_AT = datetime(2026, 9, 4, tzinfo=UTC)

RATINGS: list[dict[str, str | int | Decimal]] = [
    {
        "brand": "Volvo",
        "model": "XC60",
        "file": "Euro NCAP _ Volvo XC60.pdf",
        "url": "https://www.euroncap.com/assessments/volvo/xc60/0699/",
        "year": 2017,
        "tested_variant": "Volvo XC60 D4 AWD Momentum, LHD",
        "status": "expired",
        "adult_score": Decimal(98),
        "child_score": Decimal(87),
        "vru_score": Decimal(76),
        "assist_score": Decimal(95),
    },
    {
        "brand": "Volvo",
        "model": "EX30",
        "file": "Euro NCAP _ Volvo EX30.pdf",
        "url": "https://www.euroncap.com/assessments/volvo/ex30/1098/",
        "year": 2024,
        "tested_variant": "Volvo EX30 Plus, Single Motor Extended Range",
        "status": "current",
        "adult_score": Decimal(88),
        "child_score": Decimal(85),
        "vru_score": Decimal(79),
        "assist_score": Decimal(80),
    },
    {
        "brand": "Mercedes-Benz",
        "model": "GLC",
        "file": "Euro NCAP _ Mercedes-Benz GLC.pdf",
        "url": "https://www.euroncap.com/assessments/mercedes-benz/glc/0937/",
        "year": 2022,
        "tested_variant": "Mercedes-Benz GLC 220d 4MATIC AMG-Line, LHD",
        "status": "current",
        "adult_score": Decimal(92),
        "child_score": Decimal(90),
        "vru_score": Decimal(74),
        "assist_score": Decimal(84),
    },
    {
        "brand": "Audi",
        "model": "Q5",
        "file": "Euro NCAP _ Audi Q5.pdf",
        "url": "https://www.euroncap.com/assessments/audi/q5/1106/",
        "year": 2025,
        "tested_variant": "Audi Q5 R4 2.0 TDI MHEV, 4x4, LHD",
        "status": "current",
        "adult_score": Decimal(85),
        "child_score": Decimal(86),
        "vru_score": Decimal(79),
        "assist_score": Decimal(77),
    },
]


def _get_model(session: Session, brand_name: str, model_name: str) -> CarModel:
    model = session.scalar(
        select(CarModel).join(Brand).where(Brand.name == brand_name, CarModel.name == model_name)
    )
    if model is None:
        raise RuntimeError(
            f"{brand_name} {model_name} not found in the database — "
            "run its brand ingest script (T1.4/T1.5) first"
        )
    return model


def run(session: Session) -> None:
    for rating in RATINGS:
        model = _get_model(session, str(rating["brand"]), str(rating["model"]))
        source = insert_source(
            session,
            kind="euro_ncap_report",
            publisher="Euro NCAP",
            url=str(rating["url"]),
            document_title=f"Euro NCAP | {rating['model']}",
            document_path=DATA_DIR / str(rating["file"]),
            retrieved_at=INGESTED_AT,
            verified_at=INGESTED_AT,
        )
        session.add(
            SafetyRating(
                model_id=model.id,
                protocol="euro_ncap",
                year=rating["year"],
                tested_variant=rating["tested_variant"],
                status=rating["status"],
                adult_score=rating["adult_score"],
                child_score=rating["child_score"],
                vru_score=rating["vru_score"],
                assist_score=rating["assist_score"],
                report_source_id=source.id,
            )
        )


def main() -> None:
    with SessionLocal() as session:
        run(session)
        session.commit()


if __name__ == "__main__":
    main()
