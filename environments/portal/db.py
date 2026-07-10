"""SQLite access for the portal session service (platform.db).

The portal is the sole writer; other workstreams may read. One small file, opened per
operation with WAL so the portal (:8000) and admin (:8001) processes can share it.
"""
from __future__ import annotations

import os
import sqlite3

DB_PATH = os.environ.get("PLATFORM_DB", "/data/platform.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id                TEXT PRIMARY KEY,
    access_code       TEXT NOT NULL,
    candidate_name    TEXT NOT NULL,
    workspace_user    TEXT NOT NULL,
    problem_ids       TEXT NOT NULL DEFAULT '[]',
    state             TEXT NOT NULL DEFAULT 'created',
    terms_text        TEXT,
    terms_accepted_at TEXT,
    duration_minutes  INTEGER NOT NULL DEFAULT 90,
    starts_at         TEXT,
    ends_at           TEXT,
    llm_budget_usd    REAL NOT NULL DEFAULT 5,
    llm_models        TEXT NOT NULL DEFAULT '[]',
    internet_access   INTEGER NOT NULL DEFAULT 1,
    created_at        TEXT NOT NULL,
    activated_at      TEXT,
    closed_at         TEXT
);

CREATE TABLE IF NOT EXISTS admins (
    id            TEXT PRIMARY KEY,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

-- Per-session, per-problem moderation state: how many subproblems the admin has
-- released to the candidate. 0 = not shown yet; N = background + Q1..QN visible.
CREATE TABLE IF NOT EXISTS moderation (
    session_id TEXT NOT NULL,
    problem_id TEXT NOT NULL,
    released   INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT,
    PRIMARY KEY (session_id, problem_id)
);
"""


def connect():
    path = DB_PATH
    if path != ":memory:":
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    con = sqlite3.connect(path, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init():
    con = connect()
    try:
        con.executescript(_SCHEMA)
        con.commit()
    finally:
        con.close()
