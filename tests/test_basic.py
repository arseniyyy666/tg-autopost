from fastapi.testclient import TestClient

from app.database.session import prepare_url
from app.main import app


def test_prepare_url_converts_scheme_and_ssl():
    url, args = prepare_url(
        "postgresql://user:pass@host/db?sslmode=require&channel_binding=require"
    )
    assert url == "postgresql+asyncpg://user:pass@host/db"
    assert args == {"ssl": True}


def test_prepare_url_without_ssl():
    url, args = prepare_url("postgres://user:pass@host:5432/db")
    assert url == "postgresql+asyncpg://user:pass@host:5432/db"
    assert args == {}


def test_live_endpoint():
    client = TestClient(app)
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
