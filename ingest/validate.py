"""Gate between scraped/entered data and the database.

Every ingest script (ingest/product_docs.py, ingest/service_centres.py, ...)
must run each fact through validate_fact_record before it reaches a
session.add(). Nothing here inserts anything — it only decides whether a
record is allowed to.
"""

from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field, field_validator

# The primary-source list from AGENTS.md rule 3, given a machine-checkable kind.
ALLOWED_SOURCE_KINDS = frozenset(
    {
        "oem_site",  # Volvo/BMW/Mercedes-Benz/Audi India official sites
        "product_document",  # the five reformatted product documents, docs/CORPUS.md
        "euro_ncap_report",
        "homologation_data",  # official homologated range/efficiency figures
        "service_locator",  # Volvo's own dealer and service locator
    }
)

# The entire corpus, per docs/CORPUS.md — "if a document isn't listed here,
# it isn't in scope — do not go hunting for it, and do not ingest anything
# not named below." Titles match docs/CORPUS.md's "Document" column exactly.
ALLOWED_PRODUCT_DOCUMENT_TITLES = frozenset(
    {
        "Volvo XC60 product document",
        "Volvo EX30 product document",
        "BMW X3 product document",
        "Mercedes GLC product document",
        "Audi Q5 product document",
    }
)

# How old verified_at may be before a source is treated as stale. Ingestion
# runs weekly per docs/ARCHITECTURE.md; 180 days gives headroom for the
# manual-entry phase (T1.4/T1.5) without letting a fact go unchecked for a year.
STALENESS_THRESHOLD = timedelta(days=180)


class IngestValidationError(Exception):
    """A record failed validation and must not be inserted."""


class SourceRecord(BaseModel):
    """Metadata for a single citation, as an ingest script would produce it."""

    kind: str
    publisher: str
    url: str
    document_title: str | None = None
    retrieved_at: datetime
    verified_at: datetime | None = None
    checksum: str | None = None

    @field_validator("retrieved_at", "verified_at")
    @classmethod
    def _require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware (store UTC)")
        return value


class FactRecord(BaseModel):
    """A fact row awaiting insertion, paired with the source it must cite."""

    source: SourceRecord | None = None
    payload: dict[str, object] = Field(default_factory=dict)


def validate_fact_record(record: FactRecord, *, now: datetime | None = None) -> SourceRecord:
    """Validate one fact record. Returns its source on success.

    Raises IngestValidationError if the record has no source, the source
    cites a kind outside ALLOWED_SOURCE_KINDS, or the source is unverified
    or stale. This is the enforcement point for AGENTS.md rule 1 and rule 3
    on the ingest side — the schema's `source_id NOT NULL` is the other half.
    """
    if record.source is None:
        raise IngestValidationError("record has no source")

    source = record.source
    if source.kind not in ALLOWED_SOURCE_KINDS:
        raise IngestValidationError(f"unknown source kind: {source.kind!r}")

    if source.kind == "product_document" and source.document_title not in (
        ALLOWED_PRODUCT_DOCUMENT_TITLES
    ):
        raise IngestValidationError(
            f"document {source.document_title!r} is not in docs/CORPUS.md's corpus — "
            "do not ingest anything not named there"
        )

    if source.verified_at is None:
        raise IngestValidationError("source has never been verified")

    reference_time = now if now is not None else datetime.now(UTC)
    age = reference_time - source.verified_at
    if age > STALENESS_THRESHOLD:
        raise IngestValidationError(
            f"source verified_at={source.verified_at.isoformat()} is "
            f"{age.days} days old, past the {STALENESS_THRESHOLD.days}-day threshold"
        )

    return source
