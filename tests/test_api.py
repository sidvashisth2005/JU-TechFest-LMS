"""API tests. Auth, disease and rover-proxy tests need no services; the herd tests run only
when the database from infra/ is reachable (they are skipped in CI)."""

import dataclasses
import logging

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from backend.api import auth
from backend.api import rover as rover_api
from backend.api.main import RedactTokens, app
from backend.config import settings

TEST_SETTINGS = dataclasses.replace(
    settings,
    admin_user="admin",
    admin_password="test-password-123",
    jwt_secret="x" * 32,
    rover_url="http://rover.test",
    rover_token="rover-secret",
)


@pytest.fixture(scope="module")
def _app_client():
    # one client per module: the DB pool opened by the app lifespan cannot be reopened
    with TestClient(app) as c:
        yield c


@pytest.fixture
def client(_app_client, monkeypatch):
    monkeypatch.setattr(auth, "settings", TEST_SETTINGS)
    monkeypatch.setattr(rover_api, "settings", TEST_SETTINGS)
    monkeypatch.setattr(auth.time, "sleep", lambda s: None)  # skip the anti-guessing delay
    return _app_client


def login(c) -> dict:
    r = c.post("/api/auth/login", json={"username": "admin", "password": "test-password-123"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_health_answers_without_login(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_login_rejects_wrong_password(client):
    assert client.post("/api/auth/login", json={"username": "admin", "password": "nope"}).status_code == 401


def test_protected_routes_need_a_token(client):
    for path in ("/api/animals", "/api/alerts", "/api/summary", "/api/rover/status", "/api/disease/symptoms"):
        assert client.get(path).status_code == 401, path
    assert client.get("/api/animals", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_token_in_query_works_for_streams(client):
    token = login(client)["Authorization"].split()[1]
    assert client.get(f"/api/auth/me?token={token}").json() == {"user": "admin"}


@pytest.mark.skipif(
    not (pytest.importorskip("ml.disease.predict").ARTIFACTS / "disease_model.joblib").exists(),
    reason="disease model not trained",
)
def test_disease_predict(client):
    h = login(client)
    syms = client.get("/api/disease/symptoms", headers=h).json()
    assert "fever" in syms["symptoms"]
    r = client.post(
        "/api/disease/predict", headers=h, json={"symptoms": ["udder_swelling", "udder_heat", "milk_clots"]}
    )
    assert r.json()["predictions"][0]["disease"] == "mastitis"


def test_rover_proxy_sends_token_and_hides_rover_401(client, monkeypatch):
    seen = {}

    async def fake_request(self, method, url, json=None, headers=None):
        seen["url"], seen["headers"] = url, headers
        if url.endswith("/status"):
            return httpx.Response(200, json={"mode": "idle"})
        return httpx.Response(401, json={"detail": "rover token required"})

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    h = login(client)
    assert client.get("/api/rover/status", headers=h).json() == {"mode": "idle"}
    assert seen["url"] == "http://rover.test/status"
    assert seen["headers"] == {"X-Rover-Token": "rover-secret"}
    # a rover-side 401 must not reach the browser as 401 (that would log the user out)
    assert client.post("/api/rover/mode", headers=h, json={"mode": "follow"}).status_code == 502


def test_access_log_hides_tokens():
    rec = logging.LogRecord(
        "uvicorn.access", 20, "", 0, '%s "%s %s"', ("1.2.3.4", "GET", "/api/rover/stream.mjpg?token=abc.def"), None
    )
    RedactTokens().filter(rec)
    assert "abc.def" not in rec.getMessage() and "token=***" in rec.getMessage()


def _db_up() -> bool:
    try:
        psycopg.connect(settings.database_url, connect_timeout=2).close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not settings.database_url or not _db_up(), reason="database not running")
def test_herd_endpoints_with_database(client):
    h = login(client)
    summary = client.get("/api/summary", headers=h).json()
    assert {"animals", "online", "open_alerts", "environment"} <= summary.keys()
    animals = client.get("/api/animals", headers=h).json()
    assert isinstance(animals, list)
    if animals:
        aid = animals[0]["animal_id"]
        assert client.get(f"/api/animals/{aid}", headers=h).status_code == 200
        hist = client.get(f"/api/animals/{aid}/history?hours=6", headers=h).json()
        assert "points" in hist
    assert client.get("/api/animals/NO_SUCH_COW", headers=h).status_code == 404
    assert isinstance(client.get("/api/alerts?open=false&limit=5", headers=h).json(), list)
