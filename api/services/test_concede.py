from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from api.models import Base
from api.services.concede import (
    ConcessionCategory,
    concede,
    concede_ex30_price_class_gap,
    concede_resale_value,
    concede_service_network,
    detect_known_weakness,
)
from ingest.service_centres import run as ingest_service_centres


@pytest.fixture
def session() -> Generator[Session]:
    engine = create_engine("sqlite:///:memory:")

    def _enable_fk(dbapi_connection: object, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    event.listen(engine, "connect", _enable_fk)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        ingest_service_centres(db)
        db.flush()
        yield db


# --- detect_known_weakness -------------------------------------------------


@pytest.mark.parametrize(
    "query,expected",
    [
        (
            "My customer's from Thane and heard Mercedes has a centre there.",
            ConcessionCategory.SERVICE_NETWORK,
        ),
        (
            "Doesn't Mercedes have more service centres overall than Volvo?",
            ConcessionCategory.SERVICE_NETWORK,
        ),
        (
            "My customer heard that Volvo's resale value is bad.",
            ConcessionCategory.RESALE_VALUE,
        ),
        (
            "Customer says BMW holds its value better than Volvo.",
            ConcessionCategory.RESALE_VALUE,
        ),
        (
            "The customer says there's nothing that competes with the EX30 at its price.",
            ConcessionCategory.EX30_PRICE_CLASS_GAP,
        ),
        ("What's the boot space on the XC60?", None),
    ],
)
def test_detect_known_weakness(query: str, expected: ConcessionCategory | None) -> None:
    assert detect_known_weakness(query) == expected


@pytest.mark.parametrize(
    "query",
    [
        # Real live bug: the bare word "service" in "service warranty"
        # matched SERVICE_NETWORK, so this answered with unrelated
        # service-*centre* count data instead of falling through to a
        # normal (correctly refusing) retrieval on "warranty" — a
        # permanently out-of-corpus topic per docs/CORPUS.md.
        "bmw service warranty is better than volvo?",
        "Is BMW's service warranty better than Volvo's?",
        "What's the maintenance package warranty like for the X3?",
    ],
)
def test_detect_known_weakness_excludes_never_ingested_topics_even_with_service_wording(
    query: str,
) -> None:
    assert detect_known_weakness(query) is None


# --- concede_service_network -----------------------------------------------


def test_concedes_a_real_city_gap(session: Session) -> None:
    query = (
        "My customer's from Thane and heard Mercedes has a service centre there, but Volvo doesn't."
    )
    result = concede_service_network(query, session)
    assert "Mercedes-Benz" in result.text
    assert "Thane" in result.text
    assert "Volvo doesn't currently list one there" in result.text
    # names Volvo's real listed cities rather than inventing a "nearest" one
    assert "Bengaluru" in result.text and "Chennai" in result.text
    assert result.is_weakness is True


def test_concedes_a_real_city_gap_for_audi(session: Session) -> None:
    result = concede_service_network(
        "There's no Volvo service centre in New Delhi, only Audi's — is that right?", session
    )
    assert "Audi" in result.text
    assert "New Delhi" in result.text
    assert result.is_weakness is True


def test_concedes_a_city_gap_with_no_brand_named(session: Session) -> None:
    query = "My customer wants to know if Volvo can even service the car if they live in Thane."
    result = concede_service_network(query, session)
    assert "Thane" in result.text
    assert "Mercedes-Benz" in result.text  # the only brand actually present in Thane
    assert result.is_weakness is True


def test_concedes_the_aggregate_count_against_mercedes(session: Session) -> None:
    result = concede_service_network(
        "Doesn't Mercedes have more service centres overall than Volvo?", session
    )
    assert "Volvo: 5" in result.text
    assert "Mercedes-Benz: 9" in result.text
    assert "Volvo trails Mercedes-Benz" in result.text
    assert result.is_weakness is True


def test_concedes_the_aggregate_count_against_audi_using_ingested_figures(
    session: Session,
) -> None:
    # ingest/service_centres.py excludes one Audi row (Audi Bhopal) as a
    # self-flagged aggregator source — the ingested count (6) must be what
    # this concedes against, not the raw sheet's uncorrected count (7).
    query = "Isn't Audi's service network bigger than Volvo's in India?"
    result = concede_service_network(query, session)
    assert "Audi: 6" in result.text
    assert "Volvo: 5" in result.text
    assert result.is_weakness is True


def test_does_not_overstate_a_blanket_claim_against_every_german_brand(session: Session) -> None:
    # cc_007: Volvo (5) trails Mercedes-Benz (9) and Audi (6) but leads BMW
    # (2) in this table — the response must not claim Volvo trails "every"
    # German brand.
    query = (
        "The customer says Volvo's network is thin compared to the German brands "
        "generally — is that fair?"
    )
    result = concede_service_network(query, session)
    assert "Mercedes-Benz" in result.text and "Audi" in result.text
    assert "BMW" in result.text
    assert "trails Mercedes-Benz, Audi" in result.text
    assert "more listed centres than BMW" in result.text
    assert result.is_weakness is True  # still trails at least one brand


def test_does_not_badge_a_favourable_comparison_as_a_weakness(session: Session) -> None:
    # Real live bug report: "BMW has more service centres than Volvo,
    # right?" matches the service_network category, but the real ingested
    # data has Volvo (5) *ahead* of BMW (2) — the old code still badged
    # this "Honest Concession" / "a known Volvo weakness" regardless. The
    # text is the same honest, data-backed answer either way; only the
    # framing must change.
    query = "BMW has more service centres than Volvo, right?"
    result = concede_service_network(query, session)
    assert "Volvo: 5" in result.text
    assert "BMW: 2" in result.text
    assert "more listed centres than BMW" in result.text
    assert result.is_weakness is False


# --- concede_resale_value ---------------------------------------------------


def test_resale_concession_never_states_a_figure() -> None:
    query = "My customer heard that Volvo's resale value is bad — is that true?"
    result = concede_resale_value(query)
    assert not any(ch.isdigit() for ch in result.text)
    assert "%" not in result.text
    assert "fair" in result.text.lower() or "concern" in result.text.lower()
    assert result.is_weakness is True


# --- concede_ex30_price_class_gap -------------------------------------------


def test_ex30_gap_concession_names_the_real_reason() -> None:
    result = concede_ex30_price_class_gap(
        "Why doesn't Volvo have a documented German competitor for the EX30?"
    )
    assert "X1" in result.text
    assert "mislabelled" in result.text or "different-class" in result.text
    assert result.is_weakness is True


def test_ex30_gap_concession_refuses_a_price_comparison() -> None:
    query = "Isn't the BMW iX1 a direct rival to the EX30, and cheaper too?"
    result = concede_ex30_price_class_gap(query)
    assert "no pricing document" in result.text.lower()


# --- concede() dispatcher ----------------------------------------------------


def test_concede_dispatches_by_category(session: Session) -> None:
    assert concede("What's the boot space on the XC60?", session) is None
    network_query = "Doesn't Mercedes have more service centres than Volvo?"
    network_result = concede(network_query, session)
    assert network_result is not None
    assert "Volvo" in network_result.text
    resale_query = "My customer heard that Volvo's resale value is bad."
    assert concede(resale_query, session) == concede_resale_value(resale_query)
