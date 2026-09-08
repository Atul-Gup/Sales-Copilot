"""ingest/product_docs.py — T1.4: parse, chunk, and embed the five product
documents into `chunks` (docs/CORPUS.md, docs/ARCHITECTURE.md).

Each document is already organised into numbered sections ("1. Product
Overview", "2. Powertrain & Performance", ...), one label/value fact table
per section. A section is the semantic unit — splitting inside one would
separate a spec label from its value — so a section is one chunk unless it
exceeds `MAX_CHUNK_CHARS`, in which case it's greedily split on blank-line
boundaries without breaking a paragraph.

Every chunk carries a `source_id`, validated via `ingest/validate.py`
against `docs/CORPUS.md`'s document allowlist — the same gate every ingest
script uses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.db import SessionLocal
from api.llm.embeddings import EmbeddingClient
from api.models import Chunk, Model
from ingest.common import insert_source

PRODUCTS_DIR = Path(__file__).resolve().parent.parent / "data" / "sources" / "products"

# Merged paragraphs never exceed this many characters within a section —
# only reached by a handful of unusually long sections (docstring above).
MAX_CHUNK_CHARS = 1500

_SECTION_HEADING_RE = re.compile(r"\n(?=\d+\.\s)")


class _DocumentSpec(TypedDict):
    brand: str
    model_name: str
    document_title: str
    publisher: str
    url: str
    document_path: Path


DOCUMENTS: list[_DocumentSpec] = [
    {
        "brand": "Volvo",
        "model_name": "XC60",
        "document_title": "Volvo XC60 product document",
        "publisher": "Volvo Auto India Pvt. Ltd.",
        "url": "https://www.volvocars.com/in/cars/xc60-suv/",
        "document_path": PRODUCTS_DIR / "volvo" / "Volvo_XC60_Product_Specifications.pdf",
    },
    {
        "brand": "Volvo",
        "model_name": "EX30",
        "document_title": "Volvo EX30 product document",
        "publisher": "Volvo Auto India Pvt. Ltd.",
        "url": "https://www.volvocars.com/in/cars/ex30-electric/",
        "document_path": PRODUCTS_DIR / "volvo" / "Volvo_EX30_Product_Specifications.pdf",
    },
    {
        "brand": "BMW",
        "model_name": "X3",
        "document_title": "BMW X3 product document",
        "publisher": "BMW India",
        "url": "https://www.bmw.in/en/all-models/x-series/x3/",
        "document_path": PRODUCTS_DIR / "BMW" / "BMW_X3_Product_Specifications.pdf",
    },
    {
        "brand": "Mercedes-Benz",
        "model_name": "GLC",
        "document_title": "Mercedes GLC product document",
        "publisher": "Mercedes-Benz India Private Limited",
        "url": "https://www.mercedes-benz.co.in/passengercars/models/suv/glc.html",
        "document_path": PRODUCTS_DIR / "Mercedes" / "Mercedes_GLC_Product_Specifications.pdf",
    },
    {
        "brand": "Audi",
        "model_name": "Q5",
        "document_title": "Audi Q5 product document",
        "publisher": "Audi India (a division of ŠKODA AUTO Volkswagen India Private Limited)",
        "url": "https://www.audi.in/en/models/q5.html",
        "document_path": PRODUCTS_DIR / "Audi" / "Audi_Q5_Product_Specifications.pdf",
    },
]


@dataclass(frozen=True)
class RawChunk:
    text: str
    page: int
    section: str | None


@dataclass(frozen=True)
class IngestReport:
    document_title: str
    chunk_count: int
    error: str | None


def _extract_pages(path: Path) -> list[str]:
    reader = PdfReader(str(path))
    return [page.extract_text() or "" for page in reader.pages]


def _split_paragraphs(text: str, *, max_chars: int) -> list[str]:
    """Greedily merge blank-line-delimited paragraphs up to `max_chars`,
    never splitting a paragraph itself.
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    merged: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if current and len(candidate) > max_chars:
            merged.append(current)
            current = paragraph
        else:
            current = candidate
    if current:
        merged.append(current)
    return merged


def chunk_pdf(path: Path, *, max_chars: int = MAX_CHUNK_CHARS) -> list[RawChunk]:
    """Chunk one product document by numbered section, splitting further
    only when a section exceeds `max_chars`.

    A chunk's `page` is the page its section starts on. Most sections stay
    on one page in these documents; a section that continues onto the next
    page still cites the page it started on, which is close enough for a
    consultant to find the passage without pretending to a precision the
    source layout doesn't give.
    """
    pages = _extract_pages(path)
    page_lengths = [len(page) + 1 for page in pages]  # +1 for the "\n" join separator
    full_text = "\n".join(pages)

    section_starts = [0] + [m.start() + 1 for m in _SECTION_HEADING_RE.finditer(full_text)]
    section_ends = [*section_starts[1:], len(full_text)]

    chunks: list[RawChunk] = []
    for start, end in zip(section_starts, section_ends, strict=True):
        section_text = full_text[start:end].strip()
        if not section_text:
            continue

        offset = 0
        page_number = 1
        for candidate_page, length in enumerate(page_lengths, start=1):
            if start < offset + length:
                page_number = candidate_page
                break
            offset += length

        heading = section_text.splitlines()[0].strip()
        section_label = heading if re.match(r"^\d+\.\s", heading) else None

        for piece in _split_paragraphs(section_text, max_chars=max_chars):
            chunks.append(RawChunk(text=piece, page=page_number, section=section_label))

    return chunks


def _get_or_create_model(session: Session, *, brand: str, name: str) -> Model:
    existing = session.scalar(select(Model).where(Model.brand == brand, Model.name == name))
    if existing is not None:
        return existing
    model = Model(brand=brand, name=name, status="active")
    session.add(model)
    session.flush()
    return model


def run(session: Session, embedder: EmbeddingClient | None = None) -> list[IngestReport]:
    embedder = embedder if embedder is not None else EmbeddingClient()
    now = datetime.now(UTC)
    reports: list[IngestReport] = []

    for doc in DOCUMENTS:
        path = doc["document_path"]
        if not path.exists():
            reports.append(
                IngestReport(
                    document_title=doc["document_title"], chunk_count=0, error="file not found"
                )
            )
            continue

        try:
            raw_chunks = chunk_pdf(path)
        except Exception as exc:  # noqa: BLE001 — reported per document, not raised
            reports.append(
                IngestReport(document_title=doc["document_title"], chunk_count=0, error=str(exc))
            )
            continue

        if not raw_chunks:
            reports.append(
                IngestReport(
                    document_title=doc["document_title"], chunk_count=0, error="no text extracted"
                )
            )
            continue

        source = insert_source(
            session,
            kind="product_document",
            publisher=doc["publisher"],
            url=doc["url"],
            document_title=doc["document_title"],
            document_path=path,
            retrieved_at=now,
            verified_at=now,
        )
        model = _get_or_create_model(session, brand=doc["brand"], name=doc["model_name"])

        result = embedder.embed([chunk.text for chunk in raw_chunks])
        for raw_chunk, vector in zip(raw_chunks, result.vectors, strict=True):
            session.add(
                Chunk(
                    source_id=source.id,
                    document_id=model.id,
                    text=raw_chunk.text,
                    embedding=vector,
                    section=raw_chunk.section,
                    page=raw_chunk.page,
                )
            )

        reports.append(
            IngestReport(
                document_title=doc["document_title"], chunk_count=len(raw_chunks), error=None
            )
        )

    return reports


def main() -> None:
    with SessionLocal() as session:
        reports = run(session)
        session.commit()

    for report in reports:
        if report.error is not None:
            print(f"{report.document_title}: FAILED — {report.error}")
        else:
            print(f"{report.document_title}: {report.chunk_count} chunks")


if __name__ == "__main__":
    main()
