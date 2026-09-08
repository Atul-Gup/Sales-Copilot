"""api/services/concede.py — must_concede (T4.6).

Detects known-weakness objections and answers them from the actual
structured data rather than letting a free-form LLM narration either
deflect the concern or invent a number to sound complete. Every branch here
is a plain function over real queried data (`ServiceCentre`) or a fixed,
source-referenced statement (resale/EX30) — deliberately not an LLM call,
for the same reason `pipeline.py::refuse_gracefully` isn't one: a concession
is exactly the moment a model is most tempted to reach for a plausible but
unsourced number to soften the answer, and the one guarantee against that is
never handing it the chance.

Three categories, matching `evals/dataset/concessions.jsonl`:

- `service_network` — grounded in the ingested `ServiceCentre` table
  (`ingest/service_centres.py`). Queried directly, not retrieved, per
  `api/models/network.py`'s own docstring.
- `resale_value` — no resale-value document exists anywhere in the corpus
  (see docs/CORPUS.md). The concession here is tone (take the concern
  seriously) with a hard refusal on any figure, never a fabricated percentage.
- `ex30_price_class_gap` — the EX30 ships with zero ingested competitors by
  design (docs/CORPUS.md: the only BMW file obtained was a mislabelled,
  wrong-class X1 and was rejected rather than substituted). A fixed,
  source-referenced statement, not a table lookup.

Known limitation, stated honestly rather than overclaimed: the
`ServiceCentre` table has no geographic coordinates, so "nearest Volvo
centre" cannot be computed as an actual distance. `concede_service_network`
lists Volvo's real listed centres instead of asserting a specific one is
"nearest" — a real city name a consultant can act on, not a fabricated
proximity claim.
"""

from __future__ import annotations

import re
from enum import StrEnum

from sqlalchemy.orm import Session

from api.models import CityAlias, ServiceCentre

_SERVICE_NETWORK_PATTERNS = [
    r"\bservice\b",
    r"\bnetwork\b",
    r"\bcentre[s]?\b",
    r"\bcenter[s]?\b",
]
_RESALE_PATTERNS = [
    r"\bresale\b",
    r"\bresell\b",
    r"\bdepreciat",
    r"\bhold(s)? (its|their) value\b",
    r"\blose[s]? value\b",
]
_EX30_GAP_PATTERNS = [
    r"\bcompet\w*\b",
    r"\bcompar\w*\b",
    r"\brival\b",
    r"\boverpriced\b",
    r"\blike-for-like\b",
    r"\bcompetitively priced\b",
]

_OTHER_BRANDS = ["Mercedes-Benz", "Audi", "BMW"]
_BRAND_PATTERNS: dict[str, str] = {
    "Mercedes-Benz": r"\bmercedes(-benz)?\b|\bmerc\b",
    "Audi": r"\baudi\b",
    "BMW": r"\bbmw\b",
}

RESALE_CONCESSION = (
    "That's a fair concern to take seriously — resale value matters to most buyers. But "
    "I don't have verified resale or depreciation figures for any brand, so I can't give "
    "you a specific number or ranking here rather than guessing at one."
)

EX30_PRICE_CLASS_GAP_CONCESSION = (
    "That's a real gap, not a talking point to argue around — there's no documented "
    "German (or other) rival for the EX30 at all. The BMW file we had was actually a "
    "mislabelled, different-class X1, so there's no like-for-like comparison to offer, "
    "and no pricing document exists for the EX30 or any competitor either. Best to say "
    "plainly that no comparison is available rather than reaching for a mismatched one."
)


class ConcessionCategory(StrEnum):
    SERVICE_NETWORK = "service_network"
    RESALE_VALUE = "resale_value"
    EX30_PRICE_CLASS_GAP = "ex30_price_class_gap"


def _matches_any(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text) for p in patterns)


def detect_known_weakness(query: str) -> ConcessionCategory | None:
    """Classify a customer objection into one of the three documented
    known-weakness categories, or None if it isn't one of these — a plain
    query gets no special handling here and falls through to normal
    generation."""
    text = query.lower()

    if "ex30" in text and _matches_any(_EX30_GAP_PATTERNS, text):
        return ConcessionCategory.EX30_PRICE_CLASS_GAP
    if _matches_any(_RESALE_PATTERNS, text):
        return ConcessionCategory.RESALE_VALUE
    if _matches_any(_SERVICE_NETWORK_PATTERNS, text):
        return ConcessionCategory.SERVICE_NETWORK
    return None


def _known_cities(session: Session) -> dict[str, str]:
    """Lowercased alias/city -> canonical city, so a query can name a city
    however it's commonly spelled and still resolve."""
    cities = {row[0] for row in session.query(ServiceCentre.city).distinct()}
    mapping = {city.lower(): city for city in cities}
    for alias in session.query(CityAlias).all():
        mapping[alias.alias.lower()] = alias.canonical_city
    return mapping


def _extract_city(text: str, known_cities: dict[str, str]) -> str | None:
    for lowered, canonical in known_cities.items():
        if re.search(rf"\b{re.escape(lowered)}\b", text):
            return canonical
    return None


def _extract_brand(text: str) -> str | None:
    for brand, pattern in _BRAND_PATTERNS.items():
        if re.search(pattern, text):
            return brand
    return None


def concede_resale_value(_query: str) -> str:
    return RESALE_CONCESSION


def concede_ex30_price_class_gap(_query: str) -> str:
    return EX30_PRICE_CLASS_GAP_CONCESSION


def concede_service_network(query: str, session: Session) -> str:
    text = query.lower()
    known_cities = _known_cities(session)
    city = _extract_city(text, known_cities)
    named_brand = _extract_brand(text)

    volvo_rows = session.query(ServiceCentre).filter_by(brand="Volvo").all()
    volvo_cities = sorted({row.city for row in volvo_rows})

    if city is not None:
        candidate_brands = [named_brand] if named_brand else _OTHER_BRANDS
        brands_here = [
            brand
            for brand in candidate_brands
            if session.query(ServiceCentre).filter_by(brand=brand, city=city).first() is not None
        ]
        volvo_here = city in volvo_cities
        if brands_here and not volvo_here:
            return (
                f"That's accurate — {', '.join(brands_here)} has a service centre in "
                f"{city} and Volvo doesn't currently list one there. Volvo's listed "
                f"centres in our data are: {', '.join(volvo_cities)}. Worth checking "
                "with the customer which of those is workable, rather than promising "
                "coverage that isn't there."
            )

    brands_to_compare = [named_brand] if named_brand else _OTHER_BRANDS
    counts = {
        brand: session.query(ServiceCentre).filter_by(brand=brand).count()
        for brand in brands_to_compare
    }
    volvo_count = len(volvo_rows)
    breakdown = ", ".join([f"Volvo: {volvo_count}"] + [f"{b}: {c}" for b, c in counts.items()])
    behind = [b for b, c in counts.items() if c > volvo_count]
    ahead = [b for b, c in counts.items() if c <= volvo_count]

    clauses = []
    if behind:
        clauses.append(f"Volvo trails {', '.join(behind)} in total centre count")
    if ahead:
        clauses.append(f"currently has as many or more listed centres than {', '.join(ahead)}")
    verdict = (
        " and ".join(clauses) + " in this data."
        if clauses
        else "the counts are close in this data."
    )

    return f"By the numbers we have ({breakdown} centres), {verdict}"


def concede(query: str, session: Session) -> str | None:
    """Dispatch to the right concession, or None if this query isn't a
    known-weakness objection — the caller should fall through to normal
    generation in that case."""
    category = detect_known_weakness(query)
    if category is ConcessionCategory.SERVICE_NETWORK:
        return concede_service_network(query, session)
    if category is ConcessionCategory.RESALE_VALUE:
        return concede_resale_value(query)
    if category is ConcessionCategory.EX30_PRICE_CLASS_GAP:
        return concede_ex30_price_class_gap(query)
    return None
