import datetime

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.models import QueryEvent
from api.routers.admin import _aggregate_metrics
from api.settings import settings


def _event(
    *,
    intent: str | None = "SPEC",
    refused: bool = False,
    conceded: bool = False,
    cost_usd: float | None = 0.01,
    day: str = "2026-09-08",
    refusal_reason: str | None = None,
    first_attempt_had_violation: bool | None = None,
) -> QueryEvent:
    return QueryEvent(
        intent=intent,
        refused=refused,
        conceded=conceded,
        blocked_by_input_guardrail=None,
        refusal_reason=refusal_reason,
        first_attempt_had_violation=first_attempt_had_violation,
        top_score=0.05,
        latency_ms=100.0,
        cost_usd=cost_usd,
        created_at=datetime.datetime.fromisoformat(f"{day}T12:00:00+00:00"),
    )


def test_aggregate_metrics_on_no_events() -> None:
    result = _aggregate_metrics([])
    assert result["totals"] == {
        "n": 0,
        "refusal_rate": 0.0,
        "concession_rate": 0.0,
        "first_attempt_hallucination_rate": 0.0,
        "generated_n": 0,
        "hallucination_refusal_rate": 0.0,
    }
    assert result["by_intent"] == {}
    assert result["daily"] == []


def test_aggregate_metrics_computes_rates_and_groups_by_intent_and_day() -> None:
    events = [
        _event(intent="SPEC", refused=False, day="2026-09-08"),
        _event(intent="SPEC", refused=True, day="2026-09-08"),
        _event(intent="OBJECTION", conceded=True, day="2026-09-09"),
        _event(intent=None, refused=True, cost_usd=None, day="2026-09-09"),
    ]

    result = _aggregate_metrics(events)

    assert result["totals"] == {
        "n": 4,
        "refusal_rate": 0.5,
        "concession_rate": 0.25,
        "first_attempt_hallucination_rate": 0.0,
        "generated_n": 0,
        "hallucination_refusal_rate": 0.0,
    }
    assert result["by_intent"] == {"SPEC": 2, "OBJECTION": 1, "(blocked before classify)": 1}
    assert result["daily"] == [
        {
            "date": "2026-09-08",
            "n": 2,
            "refusal_rate": 0.5,
            "concession_rate": 0.0,
            "cost_usd": 0.02,
        },
        {
            "date": "2026-09-09",
            "n": 2,
            "refusal_rate": 0.5,
            "concession_rate": 0.5,
            "cost_usd": 0.01,
        },
    ]


def test_aggregate_metrics_computes_hallucination_rates() -> None:
    events = [
        # Reached generation, first attempt clean.
        _event(first_attempt_had_violation=False),
        # Reached generation, first attempt hallucinated but self-corrected.
        _event(first_attempt_had_violation=True),
        # Reached generation, hallucinated on both attempts, refused.
        _event(
            refused=True,
            refusal_reason="grounding_violation",
            first_attempt_had_violation=True,
        ),
        # Never reached generation at all (blocked pre-retrieval) — must be
        # excluded from the hallucination-rate denominator, not counted as
        # a clean attempt.
        _event(refused=True, refusal_reason="no_answer_outside_corpus"),
    ]

    result = _aggregate_metrics(events)

    # 2 of the 3 that reached generation had a first-attempt violation.
    assert result["totals"]["generated_n"] == 3
    assert result["totals"]["first_attempt_hallucination_rate"] == pytest.approx(2 / 3)
    # 1 of all 4 queries ended in a refusal specifically caused by a
    # hallucination surviving both attempts.
    assert result["totals"]["hallucination_refusal_rate"] == 0.25


def test_admin_metrics_rejects_without_a_token() -> None:
    with TestClient(app) as client:
        response = client.get("/admin/metrics")
    assert response.status_code == 403


def test_admin_metrics_returns_aggregates_with_a_valid_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "admin_ingest_token", "the-real-token")
    with TestClient(app) as client:
        response = client.get("/admin/metrics", headers={"x-admin-token": "the-real-token"})
    assert response.status_code == 200
    body = response.json()
    assert "totals" in body
    assert "by_intent" in body
    assert "daily" in body


def test_admin_dashboard_serves_html_without_a_token() -> None:
    with TestClient(app) as client:
        response = client.get("/admin/dashboard")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "/admin/metrics" in response.text


def test_admin_ingest_rejects_without_a_token() -> None:
    with TestClient(app) as client:
        response = client.post("/admin/ingest")
    assert response.status_code == 403


def test_admin_ingest_rejects_a_wrong_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "admin_ingest_token", "the-real-token")
    with TestClient(app) as client:
        response = client.post("/admin/ingest", headers={"x-admin-token": "wrong"})
    assert response.status_code == 403


def test_admin_ingest_rejects_when_no_token_is_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "admin_ingest_token", "")
    with TestClient(app) as client:
        response = client.post("/admin/ingest", headers={"x-admin-token": ""})
    assert response.status_code == 403


def test_admin_ingest_skips_product_docs_and_objection_guide_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real bug found before this session's deploy: the original gate was
    "any sources exist -> skip everything", which would have silently
    skipped the objection guide forever on a database that already had the
    five product documents from an earlier deploy. Each source now has its
    own independent skip check — this covers the "product docs already
    ingested, objection guide is not" case without a real embedding call.
    """
    import api.routers.admin as admin_module

    monkeypatch.setattr(settings, "admin_ingest_token", "the-real-token")
    monkeypatch.setattr(
        admin_module,
        "ingest_product_docs",
        lambda session: pytest.fail("should not run — product docs already exist"),
    )
    monkeypatch.setattr(
        admin_module,
        "ingest_service_centres",
        lambda session: pytest.fail("should not run — product docs already exist"),
    )

    class _FakeObjectionGuideReport:
        chunk_count = 28
        malformed_external_ids: list[str] = []

    monkeypatch.setattr(
        admin_module, "ingest_objection_guide", lambda session: _FakeObjectionGuideReport()
    )

    class _FakeQuery:
        def count(self) -> int:
            return 5  # product docs + service centres already present

        def filter_by(self, **kwargs: object) -> "_FakeQuery":
            return self

        def first(self) -> None:
            return None  # objection guide not yet ingested

    class _FakeSession:
        def query(self, *args: object) -> _FakeQuery:
            return _FakeQuery()

        def commit(self) -> None:
            pass

        def __enter__(self) -> "_FakeSession":
            return self

        def __exit__(self, *exc: object) -> None:
            pass

    monkeypatch.setattr(admin_module, "SessionLocal", lambda: _FakeSession())

    with TestClient(app) as client:
        response = client.post("/admin/ingest", headers={"x-admin-token": "the-real-token"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "product_docs_already_ingested"
    assert body["product_documents"] == []
    assert body["objection_guide"] == {
        "status": "ok",
        "chunk_count": 28,
        "malformed_external_ids": [],
    }
