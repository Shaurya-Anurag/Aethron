from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def test_health_and_assessment_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "test.db"))

    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"

        created = client.post(
            "/api/assessments",
            json={
                "name": "Local test lab",
                "objective": "Inventory the explicitly scoped test host",
                "scope_text": "127.0.0.1",
                "mode": "demo",
            },
        )
        assert created.status_code == 200
        assessment_id = created.json()["id"]

        detail = client.get(f"/api/assessments/{assessment_id}")
        assert detail.status_code == 200
        assert detail.json()["assessment"]["status"] == "ready"

        events = client.get(f"/api/assessments/{assessment_id}/events")
        assert events.status_code == 200
        assert any(item["title"] == "Assessment created" for item in events.json())

        report = client.get(f"/api/assessments/{assessment_id}/report")
        assert report.status_code == 200
        assert "Local test lab" in report.text


def test_assessment_creation_rejects_invalid_scope(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "invalid.db"))

    with TestClient(app) as client:
        response = client.post(
            "/api/assessments",
            json={
                "name": "Bad scope",
                "objective": "This should not be accepted",
                "scope_text": "not a valid target!",
                "mode": "demo",
            },
        )
        assert response.status_code == 422
