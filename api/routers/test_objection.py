"""api/routers/test_objection.py — `/objection/stream` SSE endpoint (T6.3)."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api.db import get_db
from api.main import app
from api.models import Base, Brand, ServiceCentre, Source
from api.objection.test_stream import _FakeEmbedder, _llm
from api.routers.objection import get_embedding_client, get_llm_client

WELL_FORMED_CHUNKS = [
    "WHAT'S TRUE: Volvo has 1 ingested service centre.\n",
    "HOW TO FRAME IT: That's a fair point — Volvo has fewer centres than rivals.\n",
    "WHAT NOT TO CLAIM: Don't promise a new centre opening.",
]


@pytest.fixture
def session() -> Generator[Session]:
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    def _enable_fk(dbapi_connection: object, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    event.listen(engine, "connect", _enable_fk)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        volvo = Brand(name="Volvo Cars", segment="luxury")
        db.add(volvo)
        db.flush()
        source = Source(
            kind="service_locator",
            publisher="Test",
            url="https://example.com",
            document_title=None,
            retrieved_at=datetime(2026, 9, 4, tzinfo=UTC),
            verified_at=datetime(2026, 9, 4, tzinfo=UTC),
            checksum="deadbeef",
        )
        db.add(source)
        db.flush()
        db.add(
            ServiceCentre(
                brand_id=volvo.id, city="Mumbai", state="MH", address="x", source_id=source.id
            )
        )
        db.commit()
        yield db


@pytest.fixture
def client(session: Session) -> Generator[TestClient]:
    llm = _llm(
        create_replies=['{"category": "service_network", "confidence": 0.95}'],
        stream_chunks=WELL_FORMED_CHUNKS,
    )
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_llm_client] = lambda: llm
    app.dependency_overrides[get_embedding_client] = lambda: _FakeEmbedder()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_objection_stream_emits_sse_frames_in_order(client: TestClient) -> None:
    response = client.post(
        "/objection/stream",
        json={
            "objection_text": "Volvo barely has service centres",
            "context": {"volvo_brand": "Volvo Cars"},
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    body = response.text
    assert "event: category" in body
    assert "event: token" in body
    assert "event: done" in body
    assert body.index("event: category") < body.index("event: token") < body.index("event: done")


def test_objection_stream_includes_response_payload_on_done(client: TestClient) -> None:
    response = client.post(
        "/objection/stream",
        json={
            "objection_text": "Volvo barely has service centres",
            "context": {"volvo_brand": "Volvo Cars"},
        },
    )
    body = response.text
    done_frame = body.split("event: done\n")[1]
    assert "1 ingested service centre" in done_frame
