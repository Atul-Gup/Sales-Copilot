"""ingest/objection_guide.py — the objection-handling guide (docs/CORPUS.md).

Unlike `ingest/product_docs.py`'s five documents, this one is **already
chunked** by its own author into 28 numbered objection/response units, each
carrying its own ID (`EX30_001`, `XC60_010`, `GENERAL_027`, ...). The
semantic chunker (`chunk_pdf`/`_split_paragraphs`) must not run on it —
splitting on paragraph size here would cut an objection apart from its own
response. This module instead splits on the document's own numbered-item
boundaries exactly, one chunk per item, and stores the given ID as
`chunks.external_id` (docs/CORPUS.md's own instruction).

Cross-model shape, unlike the five per-model documents:
- `EX30_001`-`008` belong to the EX30.
- `XC60_010`-`026` belong to the XC60 (including items that compare it
  against BMW X3/Audi Q5 — those are still fundamentally XC60 consultant
  guidance, framed from the XC60 side).
- `GENERAL_027`-`029` belong to no single model — cross-cutting guidance
  (value framing, feature-availability caution, missing-info handling).
  `chunks.document_id` is nullable specifically for this case (migration
  `b7e2f14a9c3d`); assigning them to one model's `document_id` would be a
  fabricated association `pipeline.py::_model_labels` would then present to
  the LLM as fact.

Item 9 (`EX30_009`) has already been removed from the source document per
docs/CORPUS.md — the numbering genuinely skips from 8 to 10.

One `sources` row for the whole file (`document_title="Volvo Objection
Handling Guide"`, added to `ingest/validate.py`'s allowlist) — every chunk
from this file cites that same row. Each item's own "Supporting source"
line (e.g. "EX30 brochure: Powertrain & Performance") is kept as part of
the chunk's `text`, per docs/CORPUS.md: it's descriptive content inside the
chunk, not a second citation target, since the underlying brochure isn't
independently re-ingested here.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.llm.embeddings import EmbeddingClient
from api.models import Chunk, Model
from ingest.common import insert_source

DOCUMENT_PATH = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "sources"
    / "products"
    / "volvo"
    / "objection-handling.docx"
)
DOCUMENT_TITLE = "Volvo Objection Handling Guide"
PUBLISHER = "Volvo Auto India Pvt. Ltd. (internal sales enablement material)"
# Not a public webpage, unlike the five brochures — an internal consultant
# training document has no external URL to cite honestly. Stated as such
# rather than pointing at Volvo's public site, which would misattribute it.
URL = "internal://volvo-sales-enablement/objection-handling-guide"

_ITEM_HEADING_RE = re.compile(r"^\d+\.\s")
_EXTERNAL_ID_RE = re.compile(r"^[A-Z][A-Z0-9]*_\d+$")
_BRAND_MARKERS = {"EX30": "EX30", "XC60": "XC60", "General": None}


@dataclass(frozen=True)
class ObjectionItem:
    heading: str
    objection: str
    response: str
    supporting_source: str
    external_id: str
    external_id_raw: str  # what was actually found, even if it didn't parse cleanly
    brand: str | None  # "EX30" | "XC60" | None (General)


@dataclass
class ParseReport:
    items: list[ObjectionItem] = field(default_factory=list)
    malformed_external_ids: list[tuple[str, str]] = field(default_factory=list)  # (heading, raw)


def _extract_docx_paragraphs(path: Path) -> list[str]:
    """Plain-text paragraphs from a .docx's `word/document.xml`, in order.
    No external dependency (`python-docx` isn't installed in this project)
    — a .docx is a zip archive; `<w:t>` runs are the visible text."""
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    paragraphs = re.findall(r"<w:p[ >].*?</w:p>", xml, re.S)
    texts = []
    for paragraph_xml in paragraphs:
        runs = re.findall(r"<w:t[^>]*>(.*?)</w:t>", paragraph_xml)
        text = "".join(runs)
        text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        texts.append(text.strip())
    return texts


def _next_nonempty(paragraphs: list[str], start: int) -> tuple[int, str]:
    """Index and text of the next non-empty paragraph at or after `start` —
    tolerates stray blank paragraphs (docs/CORPUS.md's guide has at least
    one, before the "General" section) without losing alignment."""
    i = start
    while i < len(paragraphs) and paragraphs[i] == "":
        i += 1
    if i >= len(paragraphs):
        raise ValueError("ran out of paragraphs while looking for content")
    return i, paragraphs[i]


def parse_objection_guide(path: Path) -> ParseReport:
    paragraphs = _extract_docx_paragraphs(path)
    report = ParseReport()
    current_brand: str | None = None
    i = 0
    while i < len(paragraphs):
        text = paragraphs[i]
        if text in _BRAND_MARKERS:
            current_brand = _BRAND_MARKERS[text]
            i += 1
            continue
        if _ITEM_HEADING_RE.match(text):
            heading = text
            i, label = _next_nonempty(paragraphs, i + 1)
            assert (
                label == "Customer objection"
            ), f"expected 'Customer objection' after {heading!r}, got {label!r}"
            i, objection = _next_nonempty(paragraphs, i + 1)
            i, label = _next_nonempty(paragraphs, i + 1)
            assert (
                label == "Recommended response"
            ), f"expected 'Recommended response', got {label!r}"
            i, response = _next_nonempty(paragraphs, i + 1)
            i, label = _next_nonempty(paragraphs, i + 1)
            assert label == "Supporting source", f"expected 'Supporting source', got {label!r}"
            i, supporting_source = _next_nonempty(paragraphs, i + 1)
            i, label = _next_nonempty(paragraphs, i + 1)
            assert label == "Chunk ID", f"expected 'Chunk ID', got {label!r}"
            i, raw_id = _next_nonempty(paragraphs, i + 1)

            if _EXTERNAL_ID_RE.match(raw_id):
                external_id = raw_id
            else:
                external_id = raw_id  # keep it anyway — flagged below, not dropped
                report.malformed_external_ids.append((heading, raw_id))

            report.items.append(
                ObjectionItem(
                    heading=heading,
                    objection=objection,
                    response=response,
                    supporting_source=supporting_source,
                    external_id=external_id,
                    external_id_raw=raw_id,
                    brand=current_brand,
                )
            )
            i += 1
            continue
        i += 1
    return report


def _chunk_text(item: ObjectionItem) -> str:
    return (
        f"{item.heading}\n"
        f"Customer objection: {item.objection}\n"
        f"Recommended response: {item.response}\n"
        f"Supporting source: {item.supporting_source}"
    )


def _get_model(session: Session, *, brand: str, name: str) -> Model:
    model = session.scalar(select(Model).where(Model.brand == brand, Model.name == name))
    if model is None:
        raise ValueError(
            f"no existing Model row for {brand} {name} — run ingest/product_docs.py first"
        )
    return model


@dataclass(frozen=True)
class ObjectionGuideReport:
    chunk_count: int
    chunk_ids: list[int]
    malformed_external_ids: list[tuple[str, str]]


def run(session: Session, embedder: EmbeddingClient | None = None) -> ObjectionGuideReport:
    embedder = embedder if embedder is not None else EmbeddingClient()
    parsed = parse_objection_guide(DOCUMENT_PATH)

    source = insert_source(
        session,
        kind="product_document",
        publisher=PUBLISHER,
        url=URL,
        document_title=DOCUMENT_TITLE,
        document_path=DOCUMENT_PATH,
        retrieved_at=datetime.now(UTC),
        verified_at=datetime.now(UTC),
    )

    xc60 = _get_model(session, brand="Volvo", name="XC60")
    ex30 = _get_model(session, brand="Volvo", name="EX30")
    brand_to_model_id = {"XC60": xc60.id, "EX30": ex30.id, None: None}

    texts = [_chunk_text(item) for item in parsed.items]
    result = embedder.embed(texts)

    chunk_ids: list[int] = []
    for item, text, vector in zip(parsed.items, texts, result.vectors, strict=True):
        chunk = Chunk(
            source_id=source.id,
            document_id=brand_to_model_id[item.brand],
            text=text,
            embedding=vector,
            section=item.heading,
            page=None,
            external_id=item.external_id,
        )
        session.add(chunk)
        session.flush()
        chunk_ids.append(chunk.id)

    return ObjectionGuideReport(
        chunk_count=len(parsed.items),
        chunk_ids=chunk_ids,
        malformed_external_ids=parsed.malformed_external_ids,
    )


def main() -> None:
    from api.db import SessionLocal

    with SessionLocal() as session:
        report = run(session)
        session.commit()

    print(f"Ingested {report.chunk_count} chunks.")
    if report.malformed_external_ids:
        print("Malformed external_id values:")
        for heading, raw in report.malformed_external_ids:
            print(f"  {heading}: {raw!r}")
    else:
        print("All external_id values parsed cleanly.")
    print(f"Chunk IDs: {report.chunk_ids}")


if __name__ == "__main__":
    main()
