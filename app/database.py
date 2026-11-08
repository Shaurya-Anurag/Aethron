import sqlite3
from contextlib import contextmanager
from pathlib import Path
from .config import settings

SCHEMA = '''
CREATE TABLE IF NOT EXISTS assessments (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, objective TEXT NOT NULL,
 scope_text TEXT NOT NULL, status TEXT NOT NULL, mode TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, assessment_id TEXT NOT NULL,
 at TEXT NOT NULL, kind TEXT NOT NULL, title TEXT NOT NULL, detail TEXT NOT NULL,
 FOREIGN KEY(assessment_id) REFERENCES assessments(id)
);
CREATE TABLE IF NOT EXISTS hosts (
 id INTEGER PRIMARY KEY AUTOINCREMENT, assessment_id TEXT NOT NULL,
 address TEXT NOT NULL, state TEXT NOT NULL, ports_json TEXT NOT NULL,
 UNIQUE(assessment_id,address), FOREIGN KEY(assessment_id) REFERENCES assessments(id)
);
CREATE TABLE IF NOT EXISTS findings (
 id TEXT PRIMARY KEY, assessment_id TEXT NOT NULL, title TEXT NOT NULL,
 severity TEXT NOT NULL, host TEXT NOT NULL, service TEXT NOT NULL,
 evidence TEXT NOT NULL, confidence TEXT NOT NULL, remediation TEXT NOT NULL,
 status TEXT NOT NULL, FOREIGN KEY(assessment_id) REFERENCES assessments(id)
);
'''

@contextmanager
def connect():
    path = Path(settings.database_path)
    if path.parent != Path('.'): path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        yield db
        db.commit()
    finally:
        db.close()

def init_db():
    with connect() as db: db.executescript(SCHEMA)

def rows(query, params=()):
    with connect() as db: return [dict(r) for r in db.execute(query, params).fetchall()]

def one(query, params=()):
    with connect() as db:
        r = db.execute(query, params).fetchone()
        return dict(r) if r else None

def execute(query, params=()):
    with connect() as db: return db.execute(query, params)
