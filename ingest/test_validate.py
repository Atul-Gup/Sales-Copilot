from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError as PydanticValidationError

from ingest.validate import (
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
