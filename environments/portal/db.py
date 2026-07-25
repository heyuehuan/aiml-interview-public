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

-- Gemini-page chat history: one row per conversation,
-- messages as a JSON array. the portal is the sole writer; the audit source of
-- truth for what the LLM actually said stays llm_transcript.jsonl (unillm writes it).
CREATE TABLE IF NOT EXISTS chats (
    id         TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    title      TEXT NOT NULL DEFAULT 'New chat',
    params     TEXT NOT NULL DEFAULT '{}',
    messages   TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS chats_by_session ON chats(session_id, updated_at);

"""

# Multiple-choice answers. `mcq_answers` is the current
# selection — which *is* the answer, there is no submit step — and `mcq_answer_events` is
# the append-only trail of how it got there, so a reviewer sees first guesses and changes
# of mind, not just the end state. Every write also lands in events.jsonl, which is what
# the export bundle carries. Kept out of _SCHEMA so the migration below can reuse the DDL.
_MCQ_SCHEMA = """
CREATE TABLE IF NOT EXISTS mcq_answers (
    session_id  TEXT NOT NULL,
    problem_id  TEXT NOT NULL,
    question_id TEXT NOT NULL,
    selected    TEXT NOT NULL DEFAULT '[]',   -- JSON array of option keys, e.g. ["A","C"]
    revision    INTEGER NOT NULL DEFAULT 0,   -- bumped on every recorded change
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (session_id, problem_id, question_id)
);

CREATE TABLE IF NOT EXISTS mcq_answer_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    problem_id  TEXT NOT NULL,
    question_id TEXT NOT NULL,
    revision    INTEGER NOT NULL,
    selected    TEXT NOT NULL,
    previous    TEXT NOT NULL,
    ts          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS mcq_events_by_session
    ON mcq_answer_events(session_id, problem_id, question_id, id);
"""

_SCHEMA_TAIL = """
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


def _drop_mcq_submit_columns(con):
    """Migration: the MCQ Submit button was removed the same day it shipped — the current
    selection is the answer — so `final`/`final_at`/`action` are gone. Rebuild the two
    tables if they predate that, carrying any rows across. `CREATE TABLE IF NOT EXISTS`
    won't do it, and leaving dead columns would make the answer sheet lie about status."""
    cols = {r["name"] for r in con.execute("PRAGMA table_info(mcq_answers)").fetchall()}
    if not cols or "final" not in cols:
        return
    con.executescript("""
        ALTER TABLE mcq_answers RENAME TO mcq_answers_old;
        ALTER TABLE mcq_answer_events RENAME TO mcq_answer_events_old;
        DROP INDEX IF EXISTS mcq_events_by_session;
    """)
    con.executescript(_MCQ_SCHEMA)
    con.executescript("""
        INSERT INTO mcq_answers
            (session_id, problem_id, question_id, selected, revision, created_at, updated_at)
            SELECT session_id, problem_id, question_id, selected, revision,
                   created_at, updated_at FROM mcq_answers_old;
        INSERT INTO mcq_answer_events
            (id, session_id, problem_id, question_id, revision, selected, previous, ts)
            SELECT id, session_id, problem_id, question_id, revision, selected, previous, ts
            FROM mcq_answer_events_old;
        DROP TABLE mcq_answers_old;
        DROP TABLE mcq_answer_events_old;
    """)


def init():
    con = connect()
    try:
        con.executescript(_SCHEMA)
        con.executescript(_MCQ_SCHEMA)
        con.executescript(_SCHEMA_TAIL)
        # Add cookie_epoch to admins tables created before cookie epochs.
        cols = {r["name"] for r in con.execute("PRAGMA table_info(admins)").fetchall()}
        if "cookie_epoch" not in cols:
            con.execute("ALTER TABLE admins ADD COLUMN cookie_epoch INTEGER NOT NULL DEFAULT 0")
        _drop_mcq_submit_columns(con)
        con.commit()
    finally:
        con.close()
