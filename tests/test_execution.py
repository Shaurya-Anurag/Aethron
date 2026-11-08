import asyncio

from app.config import settings
from app.database import connect, init_db, rows
from app.execution import _run_worker


def test_demo_execution_never_observes_out_of_scope_fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "demo-scope.db"))
    monkeypatch.setattr(settings, "tavily_api_key", "")
    init_db()

    assessment = {
        "id": "demo-scope-1",
        "name": "Single host demo",
        "objective": "Inventory only the authorized host",
        "scope_text": "192.168.56.10",
        "mode": "demo",
    }
    with connect() as db:
        db.execute(
            "INSERT INTO assessments VALUES(?,?,?,?,?,?,?,?)",
            (
                assessment["id"], assessment["name"], assessment["objective"],
                assessment["scope_text"], "running", "demo",
                "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00",
            ),
        )

    asyncio.run(_run_worker(assessment))

    observed = rows(
        "SELECT address FROM hosts WHERE assessment_id=? ORDER BY address",
        (assessment["id"],),
    )
    assert [host["address"] for host in observed] == ["192.168.56.10"]

    event_titles = [
        event["title"]
        for event in rows(
            "SELECT title FROM events WHERE assessment_id=? ORDER BY id",
            (assessment["id"],),
        )
    ]
    assert not any("192.168.56.11" in title for title in event_titles)
