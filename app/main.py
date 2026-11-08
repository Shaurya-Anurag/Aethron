import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import settings
from .database import init_db, connect, rows, one
from .models import AssessmentCreate
from .scope import parse_scope
from .reporting import build_report
from .execution import start_assessment, cancel_assessment, recover_interrupted_assessments

BASE = Path(__file__).parent
app = FastAPI(title="AETHRON", version="0.2.0")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")
templates.env.filters["from_json"] = json.loads


def now():
    return datetime.now(timezone.utc).isoformat()


def event(aid, kind, title, detail):
    with connect() as db:
        db.execute(
            "INSERT INTO events(assessment_id,at,kind,title,detail) VALUES(?,?,?,?,?)",
            (aid, now(), kind, title, detail),
        )


@app.on_event("startup")
def startup():
    init_db()
    recover_interrupted_assessments()


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    assessments = rows("SELECT * FROM assessments ORDER BY created_at DESC LIMIT 12")
    requested_id = request.query_params.get("assessment")
    active = one("SELECT * FROM assessments WHERE id=?", (requested_id,)) if requested_id else None
    if active is None:
        active = assessments[0] if assessments else None
    hosts = rows("SELECT * FROM hosts WHERE assessment_id=? ORDER BY address", (active["id"],)) if active else []
    findings = rows(
        """SELECT * FROM findings WHERE assessment_id=?
           ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1
           WHEN 'medium' THEN 2 ELSE 3 END""",
        (active["id"],),
    ) if active else []
    events = rows("SELECT * FROM events WHERE assessment_id=? ORDER BY id DESC LIMIT 20", (active["id"],)) if active else []
    context = {
        "assessments": assessments, "active": active, "hosts": hosts,
        "findings": findings, "events": events,
        "bifrost": bool(settings.bifrost_base_url and settings.bifrost_model),
        "tavily": bool(settings.tavily_api_key),
    }
    return templates.TemplateResponse(request=request, name="index.html", context=context)


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "AETHRON", "version": app.version}


@app.get("/api/assessments")
async def list_assessments():
    return rows("SELECT * FROM assessments ORDER BY created_at DESC")


@app.post("/api/assessments")
async def create_assessment(payload: AssessmentCreate):
    if payload.mode not in ("live", "demo"):
        raise HTTPException(400, "Mode must be live or demo.")
    try:
        parsed = parse_scope(payload.scope_text)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    aid = uuid.uuid4().hex[:12]
    with connect() as db:
        db.execute(
            "INSERT INTO assessments VALUES(?,?,?,?,?,?,?,?)",
            (aid, payload.name, payload.objective, payload.scope_text, "ready", payload.mode, now(), now()),
        )
    event(
        aid, "system", "Assessment created",
        f"{len(parsed.addresses) + len(parsed.hostnames)} explicit target(s); {len(parsed.networks)} network range(s).",
    )
    return {"id": aid, "status": "ready"}


@app.post("/api/assessments/{aid}/run", status_code=202)
async def run(aid: str):
    assessment = one("SELECT * FROM assessments WHERE id=?", (aid,))
    if not assessment:
        raise HTTPException(404, "Assessment not found.")
    if assessment["status"] == "running":
        raise HTTPException(409, "Assessment is already running.")
    if assessment["status"] == "complete":
        raise HTTPException(409, "Assessment is already complete. Create a new assessment to run it again.")
    with connect() as db:
        db.execute("UPDATE assessments SET status=?,updated_at=? WHERE id=?", ("running", now(), aid))
    event(aid, "system", "Execution queued", "Assessment worker accepted the run.")
    try:
        start_assessment(assessment)
    except RuntimeError as exc:
        with connect() as db:
            db.execute("UPDATE assessments SET status=?,updated_at=? WHERE id=?", ("needs_attention", now(), aid))
        raise HTTPException(409, str(exc))
    return {"status": "running", "id": aid}


@app.post("/api/assessments/{aid}/cancel")
async def cancel(aid: str):
    assessment = one("SELECT * FROM assessments WHERE id=?", (aid,))
    if not assessment:
        raise HTTPException(404, "Assessment not found.")
    if assessment["status"] != "running" or not cancel_assessment(aid):
        raise HTTPException(409, "No cancellable run is active for this assessment.")
    return {"status": "cancellation_requested", "id": aid}


@app.get("/api/assessments/{aid}")
async def assessment_detail(aid: str):
    assessment = one("SELECT * FROM assessments WHERE id=?", (aid,))
    if not assessment:
        raise HTTPException(404, "Assessment not found.")
    return {
        "assessment": assessment,
        "hosts": rows("SELECT * FROM hosts WHERE assessment_id=? ORDER BY address", (aid,)),
        "findings": rows("SELECT * FROM findings WHERE assessment_id=? ORDER BY severity", (aid,)),
        "events": rows("SELECT * FROM events WHERE assessment_id=? ORDER BY id DESC LIMIT 100", (aid,)),
    }


@app.get("/api/assessments/{aid}/events")
async def assessment_events(aid: str, after: int = 0):
    if not one("SELECT id FROM assessments WHERE id=?", (aid,)):
        raise HTTPException(404, "Assessment not found.")
    return rows(
        "SELECT * FROM events WHERE assessment_id=? AND id>? ORDER BY id LIMIT 250",
        (aid, after),
    )


@app.get("/api/assessments/{aid}/hosts")
async def assessment_hosts(aid: str):
    if not one("SELECT id FROM assessments WHERE id=?", (aid,)):
        raise HTTPException(404, "Assessment not found.")
    result = rows("SELECT * FROM hosts WHERE assessment_id=? ORDER BY address", (aid,))
    for host in result:
        host["ports"] = json.loads(host.pop("ports_json"))
    return result


@app.get("/api/assessments/{aid}/report", response_class=PlainTextResponse)
async def report(aid: str):
    assessment = one("SELECT * FROM assessments WHERE id=?", (aid,))
    if not assessment:
        raise HTTPException(404, "Assessment not found.")
    return build_report(
        assessment,
        rows("SELECT * FROM hosts WHERE assessment_id=?", (aid,)),
        rows("SELECT * FROM findings WHERE assessment_id=?", (aid,)),
        rows("SELECT * FROM events WHERE assessment_id=? ORDER BY id", (aid,)),
    )


@app.post("/api/assessments/{aid}/findings")
async def add_finding(aid: str, payload: dict):
    if not one("SELECT id FROM assessments WHERE id=?", (aid,)):
        raise HTTPException(404, "Assessment not found.")
    required = ["title", "severity", "host", "service", "evidence", "confidence", "remediation"]
    if any(not isinstance(payload.get(key), str) or not payload[key].strip() for key in required):
        raise HTTPException(422, "All finding fields are required.")
    if payload["severity"] not in ("critical", "high", "medium", "low", "informational"):
        raise HTTPException(422, "Invalid severity.")
    fid = uuid.uuid4().hex[:10]
    with connect() as db:
        db.execute(
            "INSERT INTO findings VALUES(?,?,?,?,?,?,?,?,?,?)",
            (fid, aid, payload["title"], payload["severity"], payload["host"],
             payload["service"], payload["evidence"], payload["confidence"],
             payload["remediation"], "needs_validation"),
        )
    event(aid, "evidence", "Finding recorded", f"{payload['severity'].upper()} · {payload['title']} · marked needs_validation.")
    return {"id": fid, "status": "needs_validation"}
