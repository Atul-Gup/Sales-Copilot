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
) -> QueryEvent:
    return QueryEvent(
        intent=intent,
        refused=refused,
        conceded=conceded,
        blocked_by_input_guardrail=None,
        top_score=0.05,
        latency_ms=100.0,
        cost_usd=cost_usd,
        created_at=datetime.datetime.fromisoformat(f"{day}T12:00:00+00:00"),
    )


def test_aggregate_metrics_on_no_events() -> None:
    result = _aggregate_metrics([])
    assert result["totals"] == {"n": 0, "refusal_rate": 0.0, "concession_rate": 0.0}
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

    assert result["totals"] == {"n": 4, "refusal_rate": 0.5, "concession_rate": 0.25}
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
