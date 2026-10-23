import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from backend.models import Event, Job, Settings

CACHE_TABLES = {"spec_cache", "convert_cache", "explain_cache", "sample_cache"}


def cache_key(*parts: str) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            for table in CACHE_TABLES:
                db.execute(f"CREATE TABLE IF NOT EXISTS {table} (key TEXT PRIMARY KEY, value TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, value TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, value TEXT)")
            db.execute("""CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL REFERENCES jobs(id), value TEXT NOT NULL)""")
            db.execute("CREATE INDEX IF NOT EXISTS events_job ON events(job_id, id)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS research_index (key TEXT PRIMARY KEY, value TEXT)"
            )
            db.execute("CREATE TABLE IF NOT EXISTS results (job_id TEXT PRIMARY KEY, value TEXT)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS api_credentials (host TEXT PRIMARY KEY, value TEXT)"
            )
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, table: str, key: str):
        if table not in CACHE_TABLES:
            raise ValueError("Unknown cache")
        with self.connect() as db:
            row = db.execute(f"SELECT value FROM {table} WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, table: str, key: str, value):
        if table not in CACHE_TABLES:
            raise ValueError("Unknown cache")
        with self.connect() as db:
            db.execute(f"INSERT OR REPLACE INTO {table} VALUES (?, ?)", (key, json.dumps(value)))

    def settings(self) -> Settings:
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE id=1").fetchone()
        return Settings.model_validate_json(row[0]) if row else Settings()

    def save_settings(self, settings: Settings):
        value = settings.model_dump(mode="json")
        value["api_key"] = settings.api_key.get_secret_value()
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES (1, ?)", (json.dumps(value),))

    def save_job(self, job: Job):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO jobs VALUES (?, ?)", (job.id, job.model_dump_json()))

    def job(self, job_id: str) -> Job | None:
        with self.connect() as db:
            row = db.execute("SELECT value FROM jobs WHERE id=?", (job_id,)).fetchone()
        return Job.model_validate_json(row[0]) if row else None

    def append_event(self, event: Event) -> int:
        with self.connect() as db:
            cursor = db.execute(
                "INSERT INTO events(job_id,value) VALUES (?, ?)",
                (event.job_id, event.model_dump_json()),
            )
            return cursor.lastrowid

    def events(self, job_id: str, after: int = 0):
        with self.connect() as db:
            rows = db.execute(
                "SELECT id,value FROM events WHERE job_id=? AND id>? ORDER BY id", (job_id, after)
            ).fetchall()
        return [(i, Event.model_validate_json(value)) for i, value in rows]

    def index(self, key, value=None):
        with self.connect() as db:
            if value is not None:
                db.execute("INSERT OR REPLACE INTO research_index VALUES (?, ?)", (key, value))
            row = db.execute("SELECT value FROM research_index WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def save_result(self, job_id, value):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO results VALUES (?, ?)", (job_id, json.dumps(value)))

    def result(self, job_id):
        with self.connect() as db:
            row = db.execute("SELECT value FROM results WHERE job_id=?", (job_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def jobs(self):
        with self.connect() as db:
            rows = db.execute("SELECT value FROM jobs ORDER BY rowid DESC LIMIT 50").fetchall()
        return [Job.model_validate_json(row[0]) for row in rows]

    def credential(self, host, key=None):
        with self.connect() as db:
            if key is not None:
                db.execute("INSERT OR REPLACE INTO api_credentials VALUES (?, ?)", (host, key))
            row = db.execute("SELECT value FROM api_credentials WHERE host=?", (host,)).fetchone()
        return row[0] if row else None
