"""Portal side: the control file carries `llm_budget_usd`, LLM limits are
editable on a *live* session (and republished to the control file so unillm honours
the change on the next call), and the admin detail page shows spend vs budget.
"""
import json
import os
import sys
import tempfile

import pytest

_TMP = tempfile.mkdtemp(prefix="portal-issue3-test-")
os.environ["PLATFORM_DB"] = os.path.join(_TMP, "platform.db")
os.environ["DATA_DIR"] = _TMP
os.environ["PORTAL_SECRET"] = "test-secret"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db  # noqa: E402
import model  # noqa: E402
import views_admin  # noqa: E402

# integrations is deliberately NOT imported at module scope: test modules import at
# collection time in filename order, and test_workspace_files relies on being the
# first importer so integrations' dir constants freeze to ITS tmp dirs. Importing
# inside the fixture happens at run time, after every module-level import.


@pytest.fixture(autouse=True)
def fresh_db():
    con = db.connect()
    con.executescript("DROP TABLE IF EXISTS sessions;")
    con.commit()
    con.close()
    db.init()


@pytest.fixture
def control(tmp_path, monkeypatch):
    """The integrations module, pointed at a throwaway control file."""
    import integrations
    monkeypatch.setattr(integrations, "CONTROL_FILE", str(tmp_path / "active.json"))
    return integrations


def _new(**kw):
    kw.setdefault("candidate_name", "Alex Doe")
    kw.setdefault("workspace_user", "candidate")
    return model.create_session(**kw)


def _transcript(sid, costs):
    # model.DATA_DIR, not this module's _TMP: pytest freezes the path to the
    # first-imported module's env.
    path = model.transcript_path(sid)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for c in costs:
            entry = {"endpoint": "chat.completions"}
            if c is not None:
                entry["cost_usd"] = c
            fh.write(json.dumps(entry) + "\n")


# --- control file carries the budget -----------------------------------------
def _doc(control):
    with open(control.CONTROL_FILE, encoding="utf-8") as fh:
        return json.load(fh)


def test_write_control_publishes_budget(control):
    s = _new(llm_budget_usd=7.5)
    control.write_control(s, "sk-session-key")
    doc = _doc(control)
    assert doc["llm_budget_usd"] == 7.5
    assert doc["llm_models"] == s["llm_models"]


# --- live LLM-limits edit -----------------------------------------------------
def test_update_llm_limits_on_active_session_and_republish(control):
    s = _new(llm_budget_usd=5)
    model.activate(s["id"])
    control.write_control(model.get_session(s["id"]), "sk-session-key")
    s2 = model.update_llm_limits(s["id"], llm_budget_usd=12,
                                 llm_models=["gemini-3.1-pro"], actor="root")
    control.refresh_control_session_fields(s2)
    assert s2["llm_budget_usd"] == 12 and s2["llm_models"] == ["gemini-3.1-pro"]
    doc = _doc(control)
    assert doc["llm_budget_usd"] == 12
    assert doc["llm_models"] == ["gemini-3.1-pro"]
    assert doc["llm_api_key"] == "sk-session-key"  # untouched: no key re-issue
    with open(model.events_path(s["id"]), encoding="utf-8") as fh:
        events = [json.loads(line) for line in fh if line.strip()]
    assert any(e["event"] == "llm_limits_updated" for e in events)


def test_update_llm_limits_refused_after_close():
    s = _new()
    model.activate(s["id"])
    model.close(s["id"])
    with pytest.raises(ValueError):
        model.update_llm_limits(s["id"], llm_budget_usd=10, llm_models=None)


def test_refresh_never_clobbers_another_sessions_control(control):
    s1 = _new(access_code="AAAAAA")
    s2 = _new(candidate_name="Other", access_code="BBBBBB")
    control.write_control(s1, "sk-1")
    control.refresh_control_session_fields(
        dict(s2, llm_budget_usd=99))  # other session: must be a no-op
    doc = _doc(control)
    assert doc["session_id"] == s1["id"]
    assert doc["llm_budget_usd"] == s1["llm_budget_usd"]


# --- spend fold + display -----------------------------------------------------
def test_llm_spend_sums_cost_stamps_and_skips_unstamped_lines():
    s = _new()
    _transcript(s["id"], [0.01, None, 0.002])  # None = pre-feature line, counts 0
    assert model.llm_spend_usd(s["id"]) == pytest.approx(0.012)
    assert model.llm_spend_usd("no-such-session") == 0.0


def test_detail_page_shows_spend_and_over_budget_banner():
    s = _new(llm_budget_usd=5)
    page = views_admin.admin_session_detail("root", s, llm_spend=1.23, llm_cutoff_usd=6.0)
    assert "$1.23 of $5.00" in page and "cutoff $6.00" in page
    assert "has reached the session budget" not in page
    over = views_admin.admin_session_detail("root", s, llm_spend=5.5, llm_cutoff_usd=6.0)
    assert "has reached the session budget" in over


def test_llm_limits_form_only_on_active_sessions():
    s = _new()
    assert "/llm" not in views_admin._llm_limits_form(s["id"], s)
    model.activate(s["id"])
    active = model.get_session(s["id"])
    html = views_admin._llm_limits_form(active["id"], active)
    assert f"/admin/sessions/{active['id']}/llm" in html
    assert "Budget (USD)" in html
