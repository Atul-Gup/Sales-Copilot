"""api/test_main.py — app-level wiring (T7.1): CORS for the Next.js dev
server (`web/`), which needs the browser to be allowed to call this API
cross-origin.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import app
from api.settings import settings


def test_cors_allows_the_configured_frontend_origin() -> None:
    origin = settings.cors_allow_origins[0]
    with TestClient(app) as client:
        response = client.get("/health", headers={"Origin": origin})
    assert response.headers["access-control-allow-origin"] == origin


def test_cors_default_origin_is_the_nextjs_dev_server() -> None:
    assert "http://localhost:3000" in settings.cors_allow_origins
