from __future__ import annotations

from fastapi.testclient import TestClient

from fpl_predictor.web.api import app

client = TestClient(app)


def test_index_serves_dark_ui() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "FPL Predictor" in response.text
    assert "/static/styles.css" in response.text


def test_state_never_fetches_on_page_load() -> None:
    payload = client.get("/api/state").json()
    assert "snapshot" in payload
    assert "squads" in payload


def test_transfers_requires_a_squad_source() -> None:
    response = client.post("/api/transfers", json={"refresh": False})
    assert response.status_code == 400
    assert "manager id" in response.json()["detail"]
