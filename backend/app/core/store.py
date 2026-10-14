"""Durable single-worker SQLite queue with replayable progress events."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from app.core.models import CreateJob, now


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS jobs (
                  id TEXT PRIMARY KEY, url TEXT NOT NULL, pillars TEXT NOT NULL,
                  status TEXT NOT NULL, created_at TEXT NOT NULL, started_at TEXT,
                  finished_at TEXT, attempts INTEGER NOT NULL DEFAULT 0,
                  progress TEXT NOT NULL DEFAULT '{}', report TEXT, error TEXT);
                CREATE INDEX IF NOT EXISTS queue_order ON jobs(status, created_at);
                CREATE TABLE IF NOT EXISTS events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
                  created_at TEXT NOT NULL, data TEXT NOT NULL,
                  FOREIGN KEY(job_id) REFERENCES jobs(id));
                CREATE INDEX IF NOT EXISTS events_job ON events(job_id, id);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _job(row, with_report=False):
        if row is None:
            return None
        result = dict(row)
        result["pillars"] = json.loads(result["pillars"])
        result["progress"] = json.loads(result["progress"])
        raw = result.pop("report", None)
        if with_report:
            result["report"] = json.loads(raw) if raw else None
        elif raw:
            summary = json.loads(raw)
            result["overall_score"] = summary.get("overall_score")
            result["issue_count"] = len(summary.get("findings", []))
            result["coverage"] = summary.get("coverage", 0)
            result["partial"] = summary.get("partial", True)
            result["sample"] = summary.get("sample", False)
        return result

    def create_job(self, request: CreateJob, max_queue: int = 12) -> dict:
        jid = uuid4().hex
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            count = db.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]
            if count >= max_queue:
                raise ValueError("Queue is full. Wait for an existing test to finish.")
            db.execute("INSERT INTO jobs(id,url,pillars,status,created_at) VALUES(?,?,?,'queued',?)",
                       (jid, request.url, json.dumps(request.pillars), now()))
        self.event(jid, {"type": "queued", "message": "Test added to the persistent queue."})
        return self.get_job(jid)

    def get_job(self, jid: str, with_report: bool = False) -> dict | None:
        with self.connect() as db:
            return self._job(db.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone(), with_report)

    def list_jobs(self, limit: int = 50, offset: int = 0) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
        return [self._job(r) for r in rows]

    def recover(self) -> None:
        with self.connect() as db:
            db.execute("UPDATE jobs SET status='queued', started_at=NULL WHERE status='running' AND attempts<2")
            db.execute("UPDATE jobs SET status='failed',finished_at=?,error='Repeated process interruption.' WHERE status='running'", (now(),))

    def claim(self) -> dict | None:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT id FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
            if not row:
                return None
            db.execute("UPDATE jobs SET status='running',started_at=?,attempts=attempts+1 WHERE id=?", (now(), row[0]))
        return self.get_job(row[0])

    def update(self, jid: str, **values) -> None:
        allowed = {"status", "started_at", "finished_at", "progress", "report", "error"}
        if not values or not set(values).issubset(allowed):
            raise ValueError("Invalid job update")
        pairs = []
        args = []
        for key, val in values.items():
            pairs.append(f"{key}=?")
            args.append(json.dumps(val, ensure_ascii=False) if key in {"report", "progress"} else val)
        with self.connect() as db:
            db.execute(f"UPDATE jobs SET {','.join(pairs)} WHERE id=?", (*args, jid))

    def event(self, jid: str, data: dict) -> int:
        with self.connect() as db:
            cur = db.execute("INSERT INTO events(job_id,created_at,data) VALUES(?,?,?)", (jid, now(), json.dumps(data, ensure_ascii=False)))
            return cur.lastrowid

    def events(self, jid: str, since: int = 0) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM events WHERE job_id=? AND id>? ORDER BY id LIMIT 200", (jid, since)).fetchall()
        return [{**dict(r), "data": json.loads(r["data"])} for r in rows]

    def import_report(self, report: dict) -> None:
        """Import a real sample, never silently fabricate dashboard history."""
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO jobs(id,url,pillars,status,created_at,started_at,finished_at,report,progress) VALUES(?,?,?,'completed',?,?,?,?,?)",
                       (report["id"], report["url"], json.dumps(report["selected_pillars"]), report["created_at"], report["created_at"], report["finished_at"], json.dumps(report), json.dumps({"steps": report["steps"], "percent": 100})))
