"""In-process assessment execution lifecycle.

The current starter runs one task per assessment in this process. A durable queue
(worker + broker) is a later deployment concern; stale running jobs are marked
needs_attention on restart rather than silently treated as successful.
"""
import asyncio
import json

from .config import settings
from .database import connect, rows
from .agent import run_assessment
from .intelligence import remediation_research

_tasks: dict[str, asyncio.Task] = {}


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _event(aid: str, kind: str, title: str, detail: str):
    with connect() as db:
        db.execute(
            "INSERT INTO events(assessment_id,at,kind,title,detail) VALUES(?,?,?,?,?)",
            (aid, _now(), kind, title, detail),
        )


async def _run_worker(assessment: dict):
    aid = assessment["id"]

    async def emit(kind, title, detail):
        _event(aid, kind, title, detail)

    async def save_host(result):
        with connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO hosts(assessment_id,address,state,ports_json) VALUES(?,?,?,?)",
                (aid, result["address"], result["state"], json.dumps(result["ports"])),
            )

    try:
        if assessment["mode"] == "demo":
            # Synthetic fixture is explicitly labelled and never opens a socket.
            demo_hosts = [
                {
                    "address": "192.168.56.10", "state": "up",
                    "ports": [
                        {"port": 22, "protocol": "tcp", "state": "open", "service": "ssh", "product": "OpenSSH", "version": "8.9p1", "extra": ""},
                        {"port": 8080, "protocol": "tcp", "state": "open", "service": "http-proxy", "product": "nginx", "version": "1.24.0", "extra": ""},
                    ],
                },
                {
                    "address": "192.168.56.11", "state": "up",
                    "ports": [
                        {"port": 5432, "protocol": "tcp", "state": "open", "service": "postgresql", "product": "PostgreSQL", "version": "15.4", "extra": ""},
                    ],
                },
            ]
            for host in demo_hosts:
                await emit("decision", "Planner: discover_services", f"Inspect explicitly scoped demo host {host['address']}.")
                await save_host(host)
                await emit("tool", f"Discovery complete · {host['address']}", f"State: up · Open TCP services: {len(host['ports'])}")
            await emit("system", "Demo pass complete", "Synthetic observations only. No network traffic was generated.")
        else:
            await run_assessment({**assessment, "save_host": save_host}, emit)

        # Tavily is limited to defensive product/version research. No target address is sent.
        if settings.tavily_api_key:
            seen = set()
            for host in rows("SELECT * FROM hosts WHERE assessment_id=?", (aid,)):
                for service in json.loads(host["ports_json"]):
                    key = (service.get("service", ""), service.get("product", ""), service.get("version", ""))
                    if not any(key):
                        continue
                    if key in seen:
                        continue
                    seen.add(key)
                    try:
                        references = await remediation_research(*key)
                        if references:
                            await emit(
                                "research",
                                f"Tavily research · {key[0] or key[1]}",
                                json.dumps({
                                    "note": "Defensive remediation references only; no target address transmitted.",
                                    "references": references,
                                }, ensure_ascii=False),
                            )
                    except Exception as exc:
                        await emit("warning", "Tavily research unavailable", str(exc)[:300])

        with connect() as db:
            db.execute(
                "UPDATE assessments SET status=?,updated_at=? WHERE id=?",
                ("complete", _now(), aid),
            )
        _event(aid, "system", "Assessment completed", "Execution finished. Review observations and validate findings.")
    except asyncio.CancelledError:
        with connect() as db:
            db.execute(
                "UPDATE assessments SET status=?,updated_at=? WHERE id=?",
                ("cancelled", _now(), aid),
            )
        _event(aid, "warning", "Assessment cancelled", "Execution was cancelled by the operator.")
        raise
    except Exception as exc:
        with connect() as db:
            db.execute(
                "UPDATE assessments SET status=?,updated_at=? WHERE id=?",
                ("needs_attention", _now(), aid),
            )
        _event(aid, "warning", "Execution halted", str(exc)[:1000])
    finally:
        _tasks.pop(aid, None)


def start_assessment(assessment: dict):
    aid = assessment["id"]
    current = _tasks.get(aid)
    if current and not current.done():
        raise RuntimeError("Assessment is already running.")
    task = asyncio.create_task(_run_worker(assessment), name=f"aethron-assessment-{aid}")
    _tasks[aid] = task


def cancel_assessment(aid: str) -> bool:
    task = _tasks.get(aid)
    if not task or task.done():
        return False
    task.cancel()
    return True


def recover_interrupted_assessments():
    """Fail closed after a process restart; never mark an interrupted run complete."""
    with connect() as db:
        cursor = db.execute(
            "UPDATE assessments SET status=?,updated_at=? WHERE status=?",
            ("needs_attention", _now(), "running"),
        )
        count = cursor.rowcount
    if count:
        # A global event cannot be linked to a single assessment; status is authoritative.
        return count
    return 0
