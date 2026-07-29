"""Per-session LLM dollar budget.

Every completion is priced from the config's per-model ``pricing`` block and added to a
running per-session total. The budget itself (``llm_budget_usd``) comes from the portal
control file — read per request, like the session key — so an admin raising it on the
Edit form takes effect on the very next call. Enforcement is two-stage: the admin panel warns from 100% of budget, and unillm hard-refuses
candidate-driven calls once spend reaches ``CUTOFF_FACTOR`` × budget.

Restart-proof: the in-process total for a session is seeded, on first sight, by summing
the ``cost_usd`` stamps already in that session's ``llm_transcript.jsonl`` — so a proxy
restart mid-interview cannot reset spend. Lines that predate cost stamping count as 0.

Like transcript.py, this module must stay stdlib-only so the audit/accounting path never
depends on the FastAPI/Vertex import chain.
"""
from __future__ import annotations

import json
import os
import threading
from typing import Any, Dict, Optional

DATA_DIR = os.environ.get("DATA_DIR", "/data")
CONTROL_FILE = os.environ.get("CONTROL_FILE", "/control/active.json")

# Warn at 100% of llm_budget_usd (admin panel), refuse candidate-driven calls at 120%
# (cutoff with 20% headroom, interviewer can add room live).
CUTOFF_FACTOR = 1.2

# USD per 1M tokens for a model the config forgot to price. Deliberately conservative
# (pro-tier-ish): an unpriced model must overcount, never silently ride for free.
DEFAULT_PRICING = {"input_per_1m": 2.5, "output_per_1m": 15.0}

_pricing: Dict[str, Dict[str, float]] = {}
_totals: Dict[str, float] = {}  # session_id -> spent USD, transcript-seeded
_lock = threading.Lock()


def configure(model_list) -> None:
    """Load per-model pricing from the config's model_list (proxy startup)."""
    table = {}
    for mc in model_list or []:
        name = mc.get("model_name")
        p = mc.get("pricing")
        if name and isinstance(p, dict):
            table[name] = {
                "input_per_1m": float(p.get("input_per_1m", DEFAULT_PRICING["input_per_1m"])),
                "output_per_1m": float(p.get("output_per_1m", DEFAULT_PRICING["output_per_1m"])),
            }
    with _lock:
        _pricing.clear()
        _pricing.update(table)


def cost_of(model: str, usage: Optional[Dict[str, Any]]) -> float:
    """Price one completion's token usage in USD (0.0 when there is no usage)."""
    if not usage:
        return 0.0
    p = _pricing.get(model, DEFAULT_PRICING)
    prompt = float(usage.get("prompt_tokens") or 0)
    completion = float(usage.get("completion_tokens") or 0)
    return (prompt * p["input_per_1m"] + completion * p["output_per_1m"]) / 1_000_000


def session_policy() -> Optional[Dict[str, Any]]:
    """The active session's LLM policy from the control file, or None.

    Returns {"session_id", "llm_models", "llm_budget_usd"} only while a session is
    active. Read per request so an Edit-form change (more budget, more models) or a
    close/reset is honoured immediately; any read/parse problem means 'no policy',
    which callers treat as nothing-to-enforce (matching auth's session-key behaviour)."""
    try:
        with open(CONTROL_FILE, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return None
    if doc.get("state") != "active" or not doc.get("session_id"):
        return None
    return {
        "session_id": doc["session_id"],
        "llm_models": doc.get("llm_models"),
        "llm_budget_usd": doc.get("llm_budget_usd"),
    }


def _transcript_path(session_id: str) -> str:
    return os.path.join(DATA_DIR, "sessions", session_id, "llm_transcript.jsonl")


def _seed_locked(session_id: str) -> None:
    """Sum the session's existing cost_usd stamps into _totals (caller holds _lock)."""
    if session_id in _totals:
        return
    total = 0.0
    try:
        with open(_transcript_path(session_id), encoding="utf-8") as fh:
            for line in fh:
                try:
                    c = json.loads(line).get("cost_usd")
                    if c is not None:
                        total += float(c)
                except (ValueError, TypeError):
                    continue
    except OSError:
        pass
    _totals[session_id] = total


def spent(session_id: str) -> float:
    """USD spent by this session so far (transcript-seeded on first sight)."""
    with _lock:
        _seed_locked(session_id)
        return _totals[session_id]


def add(session_id: str, cost: float) -> None:
    """Count one completion's cost against the session.

    Call BEFORE appending the transcript line it prices: seeding reads the file, so
    adding after the append would double-count the line on a cold start."""
    if not session_id or cost <= 0:
        return
    with _lock:
        _seed_locked(session_id)
        _totals[session_id] += cost


def blocked(session_id: str, budget_usd: Optional[float]) -> bool:
    """True when the session has reached the hard cutoff (CUTOFF_FACTOR × budget).

    A missing budget (old control file) enforces nothing; a budget of 0 means the
    admin granted no candidate LLM spend, so the first priced call already blocks."""
    if budget_usd is None:
        return False
    return spent(session_id) >= CUTOFF_FACTOR * float(budget_usd)


def reset() -> None:
    """Clear accounting state (test helper)."""
    with _lock:
        _totals.clear()
