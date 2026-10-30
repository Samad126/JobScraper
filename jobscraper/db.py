import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "jobs.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id        TEXT PRIMARY KEY,
    channel   TEXT NOT NULL,
    posted_at TEXT,
    text      TEXT NOT NULL
);
-- one post can advertise several jobs; posts with no jobs are still listed here
CREATE TABLE IF NOT EXISTS extracted (
    post_id TEXT PRIMARY KEY REFERENCES posts(id)
);
CREATE TABLE IF NOT EXISTS jobs (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id   TEXT NOT NULL REFERENCES posts(id),
    job_title TEXT,
    category  TEXT,
    location  TEXT,
    company   TEXT,
    url       TEXT,
    stack     TEXT,
    role      TEXT,
    level     TEXT,
    UNIQUE (post_id, job_title, url)
);
-- details scraped from the vacancy links; status 'expired' = page is gone (404)
CREATE TABLE IF NOT EXISTS vacancies (
    url      TEXT PRIMARY KEY,
    status   TEXT NOT NULL,
    title    TEXT,
    company  TEXT,
    city     TEXT,
    job_type TEXT,
    deadline TEXT
);
"""


def connect(path=DB_PATH):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    have = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
    for column in ("stack", "role", "level"):  # database made before these columns existed
        if column not in have:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {column} TEXT")
    return conn
