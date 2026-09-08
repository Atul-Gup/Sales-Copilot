from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError as PydanticValidationError

from ingest.validate import (
    ALLOWED_PRODUCT_DOCUMENT_TITLES,
    STALENESS_THRESHOLD,
    FactRecord,
    IngestValidationError,
    SourceRecord,
    validate_fact_record,
)

NOW = datetime(2026, 9, 3, tzinfo=UTC)


def _source(**overrides: object) -> SourceRecord:
    fields: dict[str, object] = {
        "kind": "oem_site",
        "publisher": "Volvo Cars India",
        "url": "https://www.volvocars.com/in/xc60/specs",
        "retrieved_at": NOW,
        "verified_at": NOW,
    }
    fields.update(overrides)
    return SourceRecord(**fields)  # type: ignore[arg-type]


def _product_document(**overrides: object) -> SourceRecord:
    fields: dict[str, object] = {
        "kind": "product_document",
        "publisher": "Volvo Cars India",
        "url": "https://www.volvocars.com/in/xc60",
        "document_title": "Volvo XC60 product document",
        "retrieved_at": NOW,
        "verified_at": NOW,
    }
    fields.update(overrides)
    return SourceRecord(**fields)  # type: ignore[arg-type]


def test_accepts_a_freshly_verified_permitted_source() -> None:
    record = FactRecord(source=_source(), payload={"attribute": "boot_space_litres"})
    assert validate_fact_record(record, now=NOW) == record.source


def test_rejects_a_record_with_no_source() -> None:
    record = FactRecord(source=None, payload={"attribute": "boot_space_litres"})
    with pytest.raises(IngestValidationError, match="no source"):
        validate_fact_record(record, now=NOW)


def test_rejects_an_unknown_source_kind() -> None:
    record = FactRecord(source=_source(kind="carwale_aggregator"))
    with pytest.raises(IngestValidationError, match="unknown source kind"):
        validate_fact_record(record, now=NOW)


def test_rejects_a_never_verified_source() -> None:
    record = FactRecord(source=_source(verified_at=None))
    with pytest.raises(IngestValidationError, match="never been verified"):
        validate_fact_record(record, now=NOW)


def test_rejects_a_source_older_than_the_staleness_threshold() -> None:
    stale_at = NOW - STALENESS_THRESHOLD - timedelta(days=1)
    record = FactRecord(source=_source(verified_at=stale_at))
    with pytest.raises(IngestValidationError, match="days old"):
        validate_fact_record(record, now=NOW)


def test_accepts_a_source_right_at_the_staleness_boundary() -> None:
    boundary_at = NOW - STALENESS_THRESHOLD
    record = FactRecord(source=_source(verified_at=boundary_at))
    validate_fact_record(record, now=NOW)


def test_rejects_a_naive_timestamp_at_construction() -> None:
    with pytest.raises(PydanticValidationError, match="timezone-aware"):
        _source(verified_at=datetime(2026, 9, 3))  # noqa: DTZ001


def test_accepts_a_product_document_named_in_corpus_md() -> None:
    record = FactRecord(source=_product_document())
    assert validate_fact_record(record, now=NOW) == record.source


def test_rejects_a_product_document_not_named_in_corpus_md() -> None:
    record = FactRecord(source=_product_document(document_title="BMW iX1 product document"))
    with pytest.raises(IngestValidationError, match="not in docs/CORPUS.md"):
        validate_fact_record(record, now=NOW)


def test_rejects_a_product_document_with_no_title() -> None:
    record = FactRecord(source=_product_document(document_title=None))
    with pytest.raises(IngestValidationError, match="not in docs/CORPUS.md"):
        validate_fact_record(record, now=NOW)


def test_every_corpus_document_title_is_accepted() -> None:
    for title in ALLOWED_PRODUCT_DOCUMENT_TITLES:
        record = FactRecord(source=_product_document(document_title=title))
        validate_fact_record(record, now=NOW)
