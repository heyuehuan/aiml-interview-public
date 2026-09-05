"""Gemini access is optional at two levels: the instance (`LLM_ENABLED`, which compose
fills from COMPOSE_PROFILES) and the session (`sessions.llm_enabled`). Off at either
level means no key is minted, the control file carries none, and every candidate-facing
surface — nav item, home tile, /llm page and chat API, handout bullet — is absent."""
import json
import re

import pytest

import db
import handout
import model
import portal
import views
import views_admin


@pytest.fixture(autouse=True)
def fresh_db():
    con = db.connect()
    con.executescript("DROP TABLE IF EXISTS sessions;")
    con.commit()
    con.close()
    db.init()


@pytest.fixture
def control(tmp_path, monkeypatch):
    import integrations
    monkeypatch.setattr(integrations, "CONTROL_FILE", str(tmp_path / "active.json"))
    return integrations


def _new(**kw):
    kw.setdefault("candidate_name", "Alex Doe")
    kw.setdefault("workspace_user", "candidate")
    return model.create_session(**kw)


def _doc(control):
    with open(control.CONTROL_FILE, encoding="utf-8") as fh:
        return json.load(fh)


# --- the instance switch ------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [
    (None, True),          # unset: a bare checkout behaves as before
    ("", False),           # compose with no COMPOSE_PROFILES
    ("llm", True),
    ("debug,llm", True),   # any profile list that includes llm
    ("1", True), ("true", True), ("yes", True),
    ("0", False), ("debug", False),
])
def test_llm_enabled_from_env(raw, expected):
    assert model._llm_enabled_from_env(raw) is expected


def test_boot_check_needs_the_master_key_only_while_llm_is_on(monkeypatch):
    monkeypatch.setattr(model, "APP_ENV", "prod")
    monkeypatch.setattr(model, "SECRET", b"a-real-secret")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "a-real-password")
    monkeypatch.delenv("ADMIN_PASSWORD_HASH", raising=False)

    monkeypatch.setattr(model, "LLM_ENABLED", False)
    monkeypatch.delenv("UNILLM_MASTER_KEY", raising=False)
    model.assert_boot_config()                          # no proxy: no key needed
    monkeypatch.setenv("UNILLM_MASTER_KEY", model.DEFAULT_UNILLM_MASTER_KEY)
    model.assert_boot_config()                          # ...and the dev value is inert

    monkeypatch.setattr(model, "LLM_ENABLED", True)
    monkeypatch.delenv("UNILLM_MASTER_KEY", raising=False)
    with pytest.raises(SystemExit) as e:
        model.assert_boot_config()
    assert "UNILLM_MASTER_KEY" in str(e.value)


def test_instance_off_overrides_a_session_that_asks_for_gemini(monkeypatch):
    s = _new()
    assert s["llm_enabled"] is True and model.session_llm_enabled(s)
    monkeypatch.setattr(model, "LLM_ENABLED", False)
    assert not model.session_llm_enabled(s)


# --- the session switch ------------------------------------------------------
def test_session_flag_defaults_on_and_is_editable():
    s = _new(llm_enabled=False)
    assert s["llm_enabled"] is False and not model.session_llm_enabled(s)
    s2 = model.update_session(
        s["id"], candidate_name="Alex Doe", workspace_user="candidate", access_code=None,
        duration_minutes=60, llm_budget_usd=5, llm_models=None, internet_access=True,
        terms_text=None, problem_ids=[], llm_enabled=True)
    assert s2["llm_enabled"] is True
    assert _new(access_code="ZZZZZZ")["llm_enabled"] is True


def test_sessions_table_from_before_the_switch_gains_the_column():
    con = db.connect()
    con.executescript("""
        DROP TABLE sessions;
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY, access_code TEXT NOT NULL, candidate_name TEXT NOT NULL,
            workspace_user TEXT NOT NULL, problem_ids TEXT NOT NULL DEFAULT '[]',
            state TEXT NOT NULL DEFAULT 'created', terms_text TEXT, terms_accepted_at TEXT,
            duration_minutes INTEGER NOT NULL DEFAULT 90, starts_at TEXT, ends_at TEXT,
            llm_budget_usd REAL NOT NULL DEFAULT 5, llm_models TEXT NOT NULL DEFAULT '[]',
            internet_access INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
            activated_at TEXT, closed_at TEXT);
        INSERT INTO sessions (id, access_code, candidate_name, workspace_user, created_at)
            VALUES ('old', 'ABCDEF', 'Old Timer', 'old', '2026-01-01T00:00:00Z');
    """)
    con.commit()
    con.close()
    db.init()
    assert model.get_session("old")["llm_enabled"] is True  # existing sessions keep Gemini


def test_llm_limits_cannot_be_set_on_a_session_without_gemini():
    s = _new(llm_enabled=False)
    with pytest.raises(ValueError, match="no Gemini access"):
        model.update_llm_limits(s["id"], llm_budget_usd=10, llm_models=None)


# --- activation: the key and the control file ---------------------------------
def test_activation_mints_no_key_for_a_session_without_gemini(control):
    s = _new(llm_enabled=False)
    model.activate(s["id"])
    control.on_activate(model.get_session(s["id"]))
    doc = _doc(control)
    assert doc["state"] == "active" and doc["session_id"] == s["id"]
    assert doc["llm_enabled"] is False
    assert doc["llm_api_key"] is None and doc["llm_base_url"] is None
    assert doc["llm_models"] == [] and doc["llm_budget_usd"] == 0
    assert control.get_session_llm_key(s["id"]) is None


def test_activation_mints_a_key_for_a_session_with_gemini(control):
    s = _new()
    model.activate(s["id"])
    control.on_activate(model.get_session(s["id"]))
    doc = _doc(control)
    assert doc["llm_enabled"] is True
    assert doc["llm_api_key"].startswith("sk-cand-")
    assert doc["llm_models"] == s["llm_models"]
    assert control.get_session_llm_key(s["id"]) == doc["llm_api_key"]


def test_instance_off_mints_no_key_at_all(control, monkeypatch):
    monkeypatch.setattr(model, "LLM_ENABLED", False)
    s = _new()                                            # session flag on, instance off
    model.activate(s["id"])
    control.on_activate(model.get_session(s["id"]))
    assert _doc(control)["llm_api_key"] is None


def test_refresh_leaves_a_keyless_control_file_without_limits(control):
    s = _new(llm_enabled=False)
    model.activate(s["id"])
    live = model.get_session(s["id"])
    control.on_activate(live)
    control.refresh_control_session_fields(dict(live, llm_models=["gemini-3.1-pro"],
                                                llm_budget_usd=99))
    doc = _doc(control)
    assert doc["llm_models"] == [] and doc["llm_budget_usd"] == 0


# --- candidate surfaces --------------------------------------------------------
def test_candidate_pages_show_gemini_only_with_access(monkeypatch):
    on = _new()
    off = _new(candidate_name="Bo", access_code="BBBBBB", llm_enabled=False)
    assert 'href="/llm"' in views.home(on, 30) and "Gemini" in views.home(on, 30)
    for page in (views.home(off, 30), views.problems_page(off, [])):
        assert "/llm" not in page and "Gemini" not in page
    monkeypatch.setattr(model, "LLM_ENABLED", False)
    assert "/llm" not in views.home(on, 30)


def test_llm_page_and_api_gate_refuse_a_session_without_gemini(monkeypatch):
    off = dict(_new(llm_enabled=False), terms_accepted_at="2026-09-05T17:00:00Z")
    on = dict(_new(access_code="CCCCCC"), terms_accepted_at="2026-09-05T17:00:00Z")
    monkeypatch.setattr(portal, "_current", lambda req: off)
    assert portal._llm_gated(None) is None
    assert portal.llm_page(None).status == 303
    assert portal.llm_chats(None).status == 401
    monkeypatch.setattr(portal, "_current", lambda req: on)
    assert portal._llm_gated(None) == on
    monkeypatch.setattr(model, "LLM_ENABLED", False)
    assert portal._llm_gated(None) is None


# --- admin surfaces ------------------------------------------------------------
def test_session_form_offers_the_switch_only_while_the_instance_has_llm(monkeypatch):
    switch = re.compile(r'<input type="checkbox" name="llm_enabled"\s+value="1"( checked)?>')
    assert switch.search(views_admin._session_form_fields([], None)).group(1)  # default on
    off = _new(llm_enabled=False)
    assert switch.search(views_admin._session_form_fields([], off)).group(1) is None
    monkeypatch.setattr(model, "LLM_ENABLED", False)
    hidden = views_admin._session_form_fields([], None)
    assert 'name="llm_enabled"' not in hidden and 'name="llm_budget_usd"' not in hidden
    assert "without the LLM proxy" in hidden


def test_session_detail_and_limits_form_follow_the_flag(monkeypatch):
    off = _new(llm_enabled=False)
    model.activate(off["id"])
    off = model.get_session(off["id"])
    page = views_admin.admin_session_detail("root", off, llm_spend=1.0, llm_cutoff_usd=6.0)
    assert "off for this session" in page
    assert "LLM limits" not in page and "LLM spend" not in page
    assert views_admin._llm_limits_form(off["id"], off) == ""
    on = _new(access_code="DDDDDD")
    assert "$5.00 ·" in views_admin.admin_session_detail("root", on)
    monkeypatch.setattr(model, "LLM_ENABLED", False)
    assert "runs without the LLM proxy" in views_admin.admin_session_detail("root", on)


def test_llm_admin_tab_explains_an_instance_without_llm():
    page = views_admin.llm_admin_page("root", None, enabled=False)
    assert "LLM support is <b>off</b>" in page and "COMPOSE_PROFILES=llm" in page
    assert "Test Gemini" not in page and "master key" not in page.lower()
    live = views_admin.llm_admin_page("root", "sk-unillm-x")
    assert "Test Gemini" in live and "sk-unillm-x" in live


# --- the printed handout ---------------------------------------------------------
def test_handout_drops_the_gemini_bullet_without_access(tmp_path, monkeypatch):
    p = tmp_path / "handout.md"
    p.write_text("## What's provided\n\n- {icon:problems} **Problems** — tasks.\n"
                 "- {icon:gemini} **Gemini** — Chat playground **and a key**\n  provided.\n"
                 "- {icon:ide} **IDE** — VS Code.\n", encoding="utf-8")
    monkeypatch.setattr(handout, "HANDOUT_FILE", str(p))
    values = {"url": "https://x.test/", "access_code": "ABCDEF",
              "candidate_name": "Ada", "terms": "T"}
    with_it = handout.content(values)["body_html"]
    assert "Gemini" in with_it and with_it.count('<li class="ico">') == 3
    without = handout.content({**values, "llm_enabled": False})["body_html"]
    assert "Gemini" not in without and without.count('<li class="ico">') == 2
    assert "Problems" in without and "IDE" in without


def test_printed_handout_matches_the_session():
    off = _new(llm_enabled=False)
    assert "Gemini" not in views_admin.session_handout(off, "https://x.test/")
    on = _new(access_code="EEEEEE")
    assert "Gemini" in views_admin.session_handout(on, "https://x.test/")
