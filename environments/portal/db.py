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
    created_at    TEXT NOT NULL,
    -- Bumped on logout so outstanding signed cookies stop verifying. A password
    -- change invalidates them too, because the cookie version also digests the hash.
    cookie_epoch  INTEGER NOT NULL DEFAULT 0
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

-- One candidate at a time. A partial unique index makes "at most one active
-- session" a database invariant: every indexed row has state='active', so uniqueness
-- on that column permits only one. This backstops the application-level check in
-- model.activate() — two concurrent activations on separate connections can both pass
-- `active_session() is None`, but only one UPDATE to 'active' can commit.
CREATE UNIQUE INDEX IF NOT EXISTS one_active_session ON sessions(state) WHERE state='active';
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
        # Add cookie_epoch to admins tables created before cookie epochs.
        cols = {r["name"] for r in con.execute("PRAGMA table_info(admins)").fetchall()}
        if "cookie_epoch" not in cols:
            con.execute("ALTER TABLE admins ADD COLUMN cookie_epoch INTEGER NOT NULL DEFAULT 0")
        con.commit()
    finally:
        con.close()
