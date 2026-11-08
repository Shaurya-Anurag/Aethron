import json, uuid
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
from .agent import run_assessment
from .reporting import build_report
from .intelligence import remediation_research

BASE = Path(__file__).parent
app = FastAPI(title='AETHRON', version='0.1.0')
app.mount('/static', StaticFiles(directory=BASE / 'static'), name='static')
templates = Jinja2Templates(directory=BASE / 'templates')
templates.env.filters['from_json'] = json.loads

@app.on_event('startup')
def startup(): init_db()

def now(): return datetime.now(timezone.utc).isoformat()

def event(aid, kind, title, detail):
    with connect() as db: db.execute('INSERT INTO events(assessment_id,at,kind,title,detail) VALUES(?,?,?,?,?)',(aid,now(),kind,title,detail))

@app.get('/', response_class=HTMLResponse)
async def home(request: Request):
    assessments = rows('SELECT * FROM assessments ORDER BY created_at DESC LIMIT 12')
    latest = assessments[0] if assessments else None
    hosts = rows('SELECT * FROM hosts WHERE assessment_id=? ORDER BY address',(latest['id'],)) if latest else []
    findings = rows('SELECT * FROM findings WHERE assessment_id=? ORDER BY CASE severity WHEN "critical" THEN 0 WHEN "high" THEN 1 WHEN "medium" THEN 2 ELSE 3 END',(latest['id'],)) if latest else []
    events = rows('SELECT * FROM events WHERE assessment_id=? ORDER BY id DESC LIMIT 12',(latest['id'],)) if latest else []
    return templates.TemplateResponse('index.html', {'request':request,'assessments':assessments,'active':latest,'hosts':hosts,'findings':findings,'events':events,'bifrost':bool(settings.bifrost_base_url and settings.bifrost_model),'tavily':bool(settings.tavily_api_key)})

@app.get('/api/assessments')
async def list_assessments(): return rows('SELECT * FROM assessments ORDER BY created_at DESC')

@app.post('/api/assessments')
async def create_assessment(payload: AssessmentCreate):
    if payload.mode not in ('live','demo'): raise HTTPException(400,'Mode must be live or demo.')
    try: parsed = parse_scope(payload.scope_text)
    except ValueError as e: raise HTTPException(422,str(e))
    aid = uuid.uuid4().hex[:12]
    with connect() as db:
        db.execute('INSERT INTO assessments VALUES(?,?,?,?,?,?,?,?)',(aid,payload.name,payload.objective,payload.scope_text,'ready',payload.mode,now(),now()))
    event(aid,'system','Assessment created',f"{len(parsed.addresses)+len(parsed.hostnames)} explicit target(s); {len(parsed.networks)} network range(s).")
    return {'id':aid,'status':'ready'}

@app.post('/api/assessments/{aid}/run')
async def run(aid: str):
    a = one('SELECT * FROM assessments WHERE id=?',(aid,))
    if not a: raise HTTPException(404,'Assessment not found.')
    if a['status']=='running': raise HTTPException(409,'Assessment is already running.')
    with connect() as db: db.execute('UPDATE assessments SET status=?,updated_at=? WHERE id=?',('running',now(),aid))
    event(aid,'system','Execution started','Scope policy is active. Only fixed discovery actions are available.')
    async def emit(kind,title,detail): event(aid,kind,title,detail)
    async def save_host(result):
        with connect() as db:
            db.execute('INSERT OR REPLACE INTO hosts(assessment_id,address,state,ports_json) VALUES(?,?,?,?)',(aid,result['address'],result['state'],json.dumps(result['ports'])))
    try:
        if a['mode']=='demo':
            demo=[{'address':'192.168.56.10','state':'up','ports':[{'port':22,'protocol':'tcp','state':'open','service':'ssh','product':'OpenSSH','version':'8.9p1','extra':''},{'port':8080,'protocol':'tcp','state':'open','service':'http-proxy','product':'nginx','version':'1.24.0','extra':''}]},{'address':'192.168.56.11','state':'up','ports':[{'port':5432,'protocol':'tcp','state':'open','service':'postgresql','product':'PostgreSQL','version':'15.4','extra':''}]}]
            for h in demo:
                await emit('decision','Planner: discover_services',f"Inspect explicitly scoped demo host {h['address']}.")
                await save_host(h); await emit('tool',f"Discovery complete · {h['address']}",f"State: up · Open TCP services: {len(h['ports'])}")
            await emit('system','Demo pass complete','Synthetic observations only. No network traffic was generated.')
        else:
            await run_assessment({**a,'save_host':save_host},emit)
        # Tavily is used only for defensive remediation context; target addresses are never sent.
        if settings.tavily_api_key:
            seen=set()
            for host in rows('SELECT * FROM hosts WHERE assessment_id=?',(aid,)):
                for svc in json.loads(host['ports_json']):
                    key=(svc.get('service',''),svc.get('product',''),svc.get('version',''))
                    if key in seen: continue
                    seen.add(key)
                    try:
                        refs=await remediation_research(*key)
                        if refs: await emit('research',f"Tavily research · {key[0]}",json.dumps({"note":"Defensive remediation references only; no target address transmitted.","references":refs},ensure_ascii=False))
                    except Exception as research_error:
                        await emit('warning','Tavily research unavailable',str(research_error)[:300])
        with connect() as db: db.execute('UPDATE assessments SET status=?,updated_at=? WHERE id=?',('complete',now(),aid))
    except Exception as e:
        with connect() as db: db.execute('UPDATE assessments SET status=?,updated_at=? WHERE id=?',('needs_attention',now(),aid))
        event(aid,'warning','Execution halted',str(e))
        raise HTTPException(400,str(e))
    return {'status':'complete','id':aid}

@app.get('/api/assessments/{aid}/report', response_class=PlainTextResponse)
async def report(aid: str):
    a=one('SELECT * FROM assessments WHERE id=?',(aid,))
    if not a: raise HTTPException(404,'Assessment not found.')
    return build_report(a,rows('SELECT * FROM hosts WHERE assessment_id=?',(aid,)),rows('SELECT * FROM findings WHERE assessment_id=?',(aid,)),rows('SELECT * FROM events WHERE assessment_id=? ORDER BY id',(aid,)))

@app.post('/api/assessments/{aid}/findings')
async def add_finding(aid: str, payload: dict):
    if not one('SELECT id FROM assessments WHERE id=?',(aid,)): raise HTTPException(404,'Assessment not found.')
    required=['title','severity','host','service','evidence','confidence','remediation']
    if any(not isinstance(payload.get(k),str) or not payload[k].strip() for k in required): raise HTTPException(422,'All finding fields are required.')
    if payload['severity'] not in ('critical','high','medium','low','informational'): raise HTTPException(422,'Invalid severity.')
    fid=uuid.uuid4().hex[:10]
    with connect() as db: db.execute('INSERT INTO findings VALUES(?,?,?,?,?,?,?,?,?,?)',(fid,aid,payload['title'],payload['severity'],payload['host'],payload['service'],payload['evidence'],payload['confidence'],payload['remediation'],'needs_validation'))
    event(aid,'evidence','Finding recorded',f"{payload['severity'].upper()} · {payload['title']} · marked needs_validation.")
    return {'id':fid,'status':'needs_validation'}
