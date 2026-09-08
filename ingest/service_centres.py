"""Ingest service centre locations from data/sources/service centres/.

Per T1.7: one row per centre in `service_centres`, with brand, city, state,
address, and source. Populates `city_aliases` so a lookup by an alternate
spelling (Bangalore, Gurgaon, Delhi) still resolves.

The sheet is 24 rows; 22 are ingested. Two are excluded, not because they
are absent from the sheet but because the sheet's own annotations say they
don't clear AGENTS.md rule 3 (primary sources only) or rule 5 (never
overstate service coverage):

- Audi Bhopal — verification_status says "Third-party dealer directory;
  verify against Audi locator before production use". That is a
  self-flagged aggregator-style source, not a primary one.
- BMW Deutsche Motoren Whitefield Showroom — centre_type is plain "Dealer"
  (not "Service Centre" or "Dealer / Service" like every other row), and
  verification_status says "service capability should be confirmed
  separately". Including it would let an unconfirmed service claim into
  the exact table the service_overstatement guardrail reads from — and
  Bengaluru already has confirmed BMW service coverage from the other two
  rows, so nothing real is lost by holding this one out.

Every other row is ingested exactly as given; no centre is added or
inferred beyond what the sheet states.
"""

from datetime import UTC, datetime
from pathlib import Path

import openpyxl
from sqlalchemy.orm import Session

from api.db import SessionLocal
from api.models import CityAlias, ServiceCentre, Source
from ingest.common import insert_source

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "sources" / "service centres"
SHEET_PATH = DATA_DIR / "Volvo and its competitors service centre.xlsx"

# Rows excluded by (brand, centre_name) — see module docstring for why.
EXCLUDED_ROWS = {
    ("BMW", "BMW Deutsche Motoren | Whitefield Showroom Bengaluru"),
    ("Audi", "Audi Bhopal"),
}

# Seeded with the aliases named in the task plus the one other common
# variant spelling among the cities this sheet actually contains. Not
# derived from the sheet — this is general Indian-city naming knowledge,
# not a sourced fact, so it carries no source_id.
CITY_ALIASES = {
    "Bangalore": "Bengaluru",
    "Gurgaon": "Gurugram",
    "Delhi": "New Delhi",
}

# Brand publisher/locator metadata, keyed off the sheet's own
# `official_source` column (identical for every row of a given brand).
BRAND_SOURCES = {
    "Volvo": ("Volvo Auto India Pvt. Ltd.", "https://www.volvocars.com/in/dealers/find-a-dealer/"),
    "BMW": ("BMW India", "https://www.bmw.in/en/service-portal.html"),
    "Mercedes-Benz": (
        "Mercedes-Benz India Private Limited",
        "https://www.mercedes-benz.co.in/passengercars/mercedes-benz-cars/dealer-locator.html",
    ),
    "Audi": (
        "Audi India (a division of ŠKODA AUTO Volkswagen India Private Limited)",
        "https://www.audi.in/en/",
    ),
}


def _canonical_city(raw_city: str) -> str:
    return CITY_ALIASES.get(raw_city, raw_city)


def run(session: Session) -> None:
    now = datetime.now(UTC)

    for alias, canonical in CITY_ALIASES.items():
        session.add(CityAlias(alias=alias, canonical_city=canonical))

    sources: dict[str, Source] = {}
    for brand_name, (publisher, url) in BRAND_SOURCES.items():
        sources[brand_name] = insert_source(
            session,
            kind="service_locator",
            publisher=publisher,
            url=url,
            document_title=f"{brand_name} India Service Centre Locations",
            document_path=SHEET_PATH,
            retrieved_at=now,
            verified_at=now,
        )

    wb = openpyxl.load_workbook(SHEET_PATH, data_only=True)
    ws = wb["Service Centres"]
    rows = ws.iter_rows(min_row=2, values_only=True)

    for row in rows:
        (
            _manufacturer,
            raw_brand_name,
            _centre_type,
            raw_centre_name,
            raw_address,
            raw_city,
            raw_state,
            _pincode,
            _phone,
            _verification_status,
            _official_source,
            _last_checked,
        ) = row
        brand_name, centre_name, address, city, state = (
            str(raw_brand_name),
            str(raw_centre_name),
            str(raw_address),
            str(raw_city),
            str(raw_state),
        )

        if (brand_name, centre_name) in EXCLUDED_ROWS:
            continue

        session.add(
            ServiceCentre(
                brand=brand_name,
                city=_canonical_city(city),
                state=state,
                address=f"{centre_name}, {address}",
                source_id=sources[brand_name].id,
            )
        )


def main() -> None:
    with SessionLocal() as session:
        run(session)
        session.commit()


if __name__ == "__main__":
    main()
