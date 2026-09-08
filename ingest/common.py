"""Shared helpers for ingest scripts: validating and inserting `Source` rows."""

import hashlib
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models import Source
from ingest.validate import FactRecord, SourceRecord, validate_fact_record


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def insert_source(
    session: Session,
    *,
    kind: str,
    publisher: str,
    url: str,
    document_title: str,
    document_path: Path,
    retrieved_at: datetime,
    verified_at: datetime,
) -> Source:
    """Validate and insert one Source row, citing the local file's checksum."""
    record = SourceRecord(
        kind=kind,
        publisher=publisher,
        url=url,
        document_title=document_title,
        retrieved_at=retrieved_at,
        verified_at=verified_at,
        checksum=sha256_of(document_path),
    )
    validate_fact_record(FactRecord(source=record))

    row = Source(
        kind=record.kind,
        publisher=record.publisher,
        url=record.url,
        document_title=record.document_title,
        retrieved_at=record.retrieved_at,
        verified_at=record.verified_at,
        checksum=record.checksum,
    )
    session.add(row)
    session.flush()
    return row


def get_or_insert_source(
    session: Session,
    *,
    kind: str,
    publisher: str,
    url: str,
    document_title: str,
    document_path: Path,
    retrieved_at: datetime,
    verified_at: datetime,
) -> Source:
    """Like `insert_source`, but reuses an existing row (matched by the
    local file's checksum) instead of inserting a duplicate.
    """
    checksum = sha256_of(document_path)
    existing = session.scalar(select(Source).where(Source.checksum == checksum))
    if existing is not None:
        return existing
    return insert_source(
        session,
        kind=kind,
        publisher=publisher,
        url=url,
        document_title=document_title,
        document_path=document_path,
        retrieved_at=retrieved_at,
        verified_at=verified_at,
    )
