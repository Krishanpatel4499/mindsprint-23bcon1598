import json

import pytest
from fastapi.testclient import TestClient

import server


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("APP_SECRET", "test-secret")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with TestClient(server.app) as test_client:
        yield test_client


def register(client, email="student@example.com"):
    return client.post(
        "/api/auth/register",
        json={"name": "Krishan Kumar", "email": email, "password": "secure-pass-123"},
    )


def test_register_sets_http_only_cookie_and_rejects_duplicate_email(client):
    response = register(client)
    assert response.status_code == 201
    assert response.json()["user"]["email"] == "student@example.com"
    assert response.cookies.get(server.SESSION_COOKIE)
    assert "httponly" in response.headers["set-cookie"].lower()

    duplicate = register(client)
    assert duplicate.status_code == 409


def test_tasks_require_auth_and_are_private_to_their_owner(client):
    assert client.get("/api/tasks").status_code == 401
    assert register(client).status_code == 201
    created = client.post(
        "/api/tasks",
        json={"title": "Review recursion", "description": "Work through two examples"},
    )
    assert created.status_code == 201
    task = created.json()["task"]
    assert task["title"] == "Review recursion"

    second_client = TestClient(server.app)
    assert register(second_client, "another@example.com").status_code == 201
    assert second_client.get("/api/tasks").json()["tasks"] == []
    assert second_client.patch(f"/api/tasks/{task['id']}", json={"completed": True}).status_code == 404


def test_ai_plan_requires_key_and_persists_generated_tasks(client, monkeypatch):
    register(client)
    payload = {"goal": "Learn Python dictionaries", "days": 3}
    missing_key = client.post("/api/ai/plan", json=payload)
    assert missing_key.status_code == 503

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    today = server.date.today()
    generated = {
        "summary": "A focused three-day plan.",
        "tasks": [
            {
                "title": "Learn dictionary basics",
                "description": "Review key-value pairs.",
                "due_date": today.isoformat(),
            }
        ],
    }
    monkeypatch.setattr(server, "request_ai_plan", lambda goal, days: generated)
    response = client.post("/api/ai/plan", json=payload)
    assert response.status_code == 200
    assert response.json()["summary"] == generated["summary"]
    assert response.json()["tasks"][0]["title"] == "Learn dictionary basics"
    assert client.get("/api/tasks").json()["tasks"][0]["title"] == "Learn dictionary basics"
