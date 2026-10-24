from fastapi.testclient import TestClient

from app.main import app


def test_webapp_page_is_served():
    client = TestClient(app)
    response = client.get("/webapp/")
    assert response.status_code == 200
    assert "telegram-web-app.js" in response.text
