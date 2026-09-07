"""ingest/documents.py — Corpus B ingestion (T4.2a).

Parses, chunks, and embeds Showroom Copilot's narrative documents (warranty
terms and full Euro NCAP reports) into `document_chunks`, for the objection
path's hybrid retrieval (T4.2b). Distinct from Corpus A (ingest/volvo.py,
ingest/euroncap.py, etc.): these are documents where the answer is a
passage, not a field — see docs/RETRIEVAL.md's Corpus A/B split.

Per docs/CORPUS.md, the Volvo service plan and any owner's manual are not
available for the India market ("not published on the India site... do NOT
substitute" a different market's document), so only the warranty document
and the four already-ingested Euro NCAP reports are chunked here.
Competitor warranty/service documents are out of scope by design
(docs/CORPUS.md: "warranty is not a comparison axis... document-QA for the
Volvo owner only").

Every chunk carries a `source_id` — the same rule ingest/*.py already
applies to Corpus A fact rows: a chunk with no traceable source is not
created. The Euro NCAP PDFs already have a `Source` row from
`ingest/euroncap.py`; `get_or_insert_source` reuses it by checksum rather
than creating a duplicate, so this module works whether or not
`ingest/euroncap.py` has already run in the same session.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

from pypdf import PdfReader
from sqlalchemy.orm import Session

from api.db import SessionLocal
from api.llm.embeddings import EmbeddingClient
from api.models import DocumentChunk
from ingest.common import get_or_insert_source

VOLVO_DIR = Path(__file__).resolve().parent.parent / "data" / "sources" / "volvo"
NCAP_DIR = Path(__file__).resolve().parent.parent / "data" / "sources" / "euroncap"
INGESTED_AT = datetime(2026, 9, 4, tzinfo=UTC)

# Merged paragraphs never exceed this many characters — keeps a chunk small
# enough for focused retrieval without splitting a paragraph mid-thought.
MAX_CHUNK_CHARS = 1000


class _DocumentSpec(TypedDict):
    kind: str
    publisher: str
    url: str
    document_title: str
    document_path: Path


DOCUMENTS: list[_DocumentSpec] = [
    {
        "kind": "oem_site",
        "publisher": "Volvo Auto India Pvt. Ltd.",
        "url": "https://www.volvocars.com/in/support/warranty/",
        "document_title": "Volvo Warranty (India)",
        "document_path": VOLVO_DIR / "Volvo Warranty.pdf",
    },
    {
        "kind": "euro_ncap_report",
        "publisher": "Euro NCAP",
        "url": "https://www.euroncap.com/assessments/volvo/xc60/0699/",
        "document_title": "Euro NCAP | XC60",
        "document_path": NCAP_DIR / "Euro NCAP _ Volvo XC60.pdf",
    },
    {
        "kind": "euro_ncap_report",
        "publisher": "Euro NCAP",
        "url": "https://www.euroncap.com/assessments/volvo/ex30/1098/",
        "document_title": "Euro NCAP | EX30",
        "document_path": NCAP_DIR / "Euro NCAP _ Volvo EX30.pdf",
    },
    {
        "kind": "euro_ncap_report",
        "publisher": "Euro NCAP",
        "url": "https://www.euroncap.com/assessments/mercedes-benz/glc/0937/",
        "document_title": "Euro NCAP | GLC",
        "document_path": NCAP_DIR / "Euro NCAP _ Mercedes-Benz GLC.pdf",
    },
    {
        "kind": "euro_ncap_report",
        "publisher": "Euro NCAP",
        "url": "https://www.euroncap.com/assessments/audi/q5/1106/",
        "document_title": "Euro NCAP | Q5",
        "document_path": NCAP_DIR / "Euro NCAP _ Audi Q5.pdf",
    },
]


@dataclass(frozen=True)
class RawChunk:
    text: str
    page: int


def _extract_pages(path: Path) -> list[str]:
    reader = PdfReader(str(path))
    return [page.extract_text() or "" for page in reader.pages]


def chunk_pdf(path: Path, *, max_chars: int = MAX_CHUNK_CHARS) -> list[RawChunk]:
    """Split each page on blank-line paragraph boundaries, then greedily
    merge consecutive paragraphs up to `max_chars`.

    A chunk never crosses a page boundary, so its `page` citation is always
    exact — semantic section boundaries (docs/RETRIEVAL.md's `section`
    field) aren't detected here, since pypdf's text extraction doesn't
    reliably expose heading structure for these documents; `section` is
    left null on every chunk rather than guessed.
    """
    chunks: list[RawChunk] = []
    for page_number, page_text in enumerate(_extract_pages(path), start=1):
        paragraphs = [p.strip() for p in page_text.split("\n\n") if p.strip()]
        current = ""
        for paragraph in paragraphs:
            candidate = f"{current}\n\n{paragraph}" if current else paragraph
            if current and len(candidate) > max_chars:
                chunks.append(RawChunk(text=current, page=page_number))
                current = paragraph
            else:
                current = candidate
        if current:
            chunks.append(RawChunk(text=current, page=page_number))
    return chunks


def run(session: Session, embedder: EmbeddingClient | None = None) -> None:
    embedder = embedder if embedder is not None else EmbeddingClient()
    for doc in DOCUMENTS:
        path = doc["document_path"]
        if not path.exists():
            continue

        raw_chunks = chunk_pdf(path)
        if not raw_chunks:
            continue

        source = get_or_insert_source(
            session,
            kind=doc["kind"],
            publisher=doc["publisher"],
            url=doc["url"],
            document_title=doc["document_title"],
            document_path=path,
            retrieved_at=INGESTED_AT,
            verified_at=INGESTED_AT,
        )

        result = embedder.embed([chunk.text for chunk in raw_chunks])
        for raw_chunk, vector in zip(raw_chunks, result.vectors, strict=True):
            session.add(
                DocumentChunk(
                    source_id=source.id,
                    document_title=doc["document_title"],
                    section=None,
                    page=raw_chunk.page,
                    text=raw_chunk.text,
                    embedding=vector,
                )
            )


def main() -> None:
    with SessionLocal() as session:
        run(session)
        session.commit()


if __name__ == "__main__":
    main()
