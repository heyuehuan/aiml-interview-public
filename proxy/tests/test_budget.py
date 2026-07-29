"""the per-session dollar budget and per-session model gate.

llm_budget_usd was recorded-but-never-enforced, and llm_models stopped at the portal —
a candidate calling the proxy directly could use any configured model. The properties
that matter: every completion is priced (streams included, unknown models never ride
free), spend survives a proxy restart, candidate-driven calls stop at 120% of budget
(admin diagnostics never do), and a session key can only name the session's models.

No test here talks to Vertex — everything runs against local files and stubs.
"""
import json
import os
import sys

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unillm.proxy import budget, proxy_server  # noqa: E402
from unillm.types import UserAPIKeyAuth  # noqa: E402


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    monkeypatch.setattr(budget, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(budget, "CONTROL_FILE", str(tmp_path / "active.json"))
    budget.configure([])
    budget.reset()
    yield
    budget.configure([])
    budget.reset()


def _control(doc):
    with open(budget.CONTROL_FILE, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)


def _transcript(sid, costs):
    path = budget._transcript_path(sid)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for c in costs:
            fh.write(json.dumps({"cost_usd": c} if c is not None else {}) + "\n")


# --- pricing ----------------------------------------------------------------
def test_cost_uses_the_configured_per_model_pricing():
    budget.configure([{"model_name": "m", "pricing": {"input_per_1m": 1.0, "output_per_1m": 2.0}}])
    usage = {"prompt_tokens": 1_000_000, "completion_tokens": 500_000, "total_tokens": 1_500_000}
    assert budget.cost_of("m", usage) == pytest.approx(2.0)


def test_unpriced_model_costs_the_conservative_default_never_zero():
    cost = budget.cost_of("mystery-model", {"prompt_tokens": 1000, "completion_tokens": 1000})
    assert cost == pytest.approx((1000 * 2.5 + 1000 * 15.0) / 1_000_000)
    assert cost > 0


def test_no_usage_costs_nothing():
    assert budget.cost_of("m", None) == 0.0
    assert budget.cost_of("m", {}) == 0.0


# --- restart-proof accounting ------------------------------------------------
def test_spend_is_seeded_from_the_transcript():
    _transcript("s1", [0.5, None, 0.25])  # None = a pre-feature line, counts 0
    assert budget.spent("s1") == pytest.approx(0.75)


def test_add_accumulates_on_top_of_the_seed():
    _transcript("s1", [0.5])
    budget.add("s1", 0.1)
    assert budget.spent("s1") == pytest.approx(0.6)


def test_sessions_are_accounted_separately():
    budget.add("s1", 1.0)
    assert budget.spent("s2") == 0.0


# --- cutoff thresholds --------------------------------------------------------
def test_blocked_only_from_120_percent_of_budget():
    _transcript("s1", [1.19])
    assert budget.blocked("s1", 1.0) is False   # over budget, inside the 20% headroom
    budget.add("s1", 0.01)
    assert budget.blocked("s1", 1.0) is True    # at 1.2x: hard cutoff


def test_missing_budget_enforces_nothing_and_zero_budget_blocks_at_once():
    assert budget.blocked("s1", None) is False
    assert budget.blocked("s1", 0) is True      # admin granted no candidate LLM spend


# --- control-file policy ------------------------------------------------------
def test_policy_absent_without_an_active_session():
    assert budget.session_policy() is None
    _control({"state": "inactive"})
    assert budget.session_policy() is None


def test_policy_reads_models_and_budget_from_the_control_file():
    _control({"state": "active", "session_id": "s1",
              "llm_models": ["gemini-3.5-flash"], "llm_budget_usd": 5})
    p = budget.session_policy()
    assert p == {"session_id": "s1", "llm_models": ["gemini-3.5-flash"], "llm_budget_usd": 5}


# --- enforcement at the endpoints --------------------------------------------
def _key(k="sk-x"):
    return UserAPIKeyAuth(api_key=k, valid=True)


def test_session_key_cannot_use_a_model_outside_the_session_list(monkeypatch):
    _control({"state": "active", "session_id": "s1",
              "llm_models": ["gemini-3.5-flash"], "llm_budget_usd": 5})
    monkeypatch.setattr(proxy_server, "is_session_key", lambda k: True)
    with pytest.raises(HTTPException) as exc:
        proxy_server._enforce_session_policy("gemini-3.1-pro", _key(), "api")
    assert exc.value.status_code == 400
    proxy_server._enforce_session_policy("gemini-3.5-flash", _key(), "api")  # allowed


def test_master_key_stays_config_gated_only(monkeypatch):
    _control({"state": "active", "session_id": "s1",
              "llm_models": ["gemini-3.5-flash"], "llm_budget_usd": 5})
    monkeypatch.setattr(proxy_server, "is_session_key", lambda k: False)
    proxy_server._enforce_session_policy("gemini-3.1-pro", _key(), "admin-test")


def test_candidate_calls_blocked_at_cutoff_admin_test_never(monkeypatch):
    _control({"state": "active", "session_id": "s1",
              "llm_models": ["gemini-3.5-flash"], "llm_budget_usd": 1})
    _transcript("s1", [1.2])
    monkeypatch.setattr(proxy_server, "is_session_key", lambda k: False)
    for source in ("api", "ui"):
        with pytest.raises(HTTPException) as exc:
            proxy_server._enforce_session_policy("gemini-3.5-flash", _key(), source)
        assert exc.value.status_code == 429
    proxy_server._enforce_session_policy("gemini-3.5-flash", _key(), "admin-test")
    proxy_server._enforce_session_policy("gemini-3.5-flash", _key(), "server")


def test_no_control_file_enforces_nothing(monkeypatch):
    monkeypatch.setattr(proxy_server, "is_session_key", lambda k: True)
    proxy_server._enforce_session_policy("anything", _key(), "api")


# --- streamed usage mapping ---------------------------------------------------
def test_vertex_stream_chunk_carries_final_usage_through():
    from unillm.llm.vertex_ai import VertexAIHandler
    h = VertexAIHandler(project="p", location="global")
    plain = h._convert_stream_chunk({"candidates": [{"content": {"parts": [{"text": "hi"}]}}]}, "m")
    assert "usage" not in plain
    final = h._convert_stream_chunk(
        {"candidates": [{"content": {"parts": []}, "finishReason": "STOP"}],
         "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 20,
                           "totalTokenCount": 30}}, "m")
    assert final["usage"] == {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
