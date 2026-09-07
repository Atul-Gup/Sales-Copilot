"""Shared helpers for the per-brand ingest scripts."""

import hashlib
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models import CarModel, Source, Spec, Variant
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
    """Validate and insert one Source row, citing the local PDF's checksum."""
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
    local file's checksum) instead of inserting a duplicate — for documents
    another ingest script may already have sourced (e.g. the Euro NCAP PDFs,
    already inserted by `ingest/euroncap.py` for `SafetyRating` rows, are
    re-chunked for Corpus B by `ingest/documents.py` without a second
    `Source` row per PDF).
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


def add_variant_with_specs(
    session: Session,
    model: CarModel,
    source: Source,
    *,
    name: str,
    powertrain: str,
    page: int,
    numeric_specs: list[tuple[str, float, str]] | None = None,
    text_specs: list[tuple[str, str]] | None = None,
    ex_showroom_paise: int | None = None,
    price_source_id: int | None = None,
) -> Variant:
    """Insert one Variant plus a flat list of numeric/text Spec rows, all
    citing the same source page. All specs are verified=True — callers with
    ambiguous or conflicting figures should add those Spec rows separately.
    """
    variant = Variant(
        model_id=model.id,
        name=name,
        powertrain=powertrain,
        ex_showroom_paise=ex_showroom_paise,
        price_source_id=price_source_id,
    )
    session.add(variant)
    session.flush()

    for attribute, value_num, unit in numeric_specs or []:
        session.add(
            Spec(
                variant_id=variant.id,
                attribute=attribute,
                value_num=value_num,
                unit=unit,
                source_id=source.id,
                source_page=page,
                verified=True,
            )
        )
    for attribute, value_text in text_specs or []:
        session.add(
            Spec(
                variant_id=variant.id,
                attribute=attribute,
                value_text=value_text,
                source_id=source.id,
                source_page=page,
                verified=True,
            )
        )
    return variant
