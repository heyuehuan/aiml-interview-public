"""internet_access is a record, not a control. Nothing enforces it, so the
create/edit forms stop offering Full/Restricted (a control-shaped label), new sessions
are always recorded as full, edits preserve whatever a legacy row says, and the detail
page states plainly that a recorded "restricted" was never enforced.
"""
import pytest

import db
import model
import views_admin


@pytest.fixture(autouse=True)
def fresh_db():
    con = db.connect()
    con.executescript("DROP TABLE IF EXISTS sessions;")
    con.commit()
    con.close()
    db.init()


@pytest.fixture
def admin_mod(monkeypatch):
    """The admin module with auth stubbed out, imported at run time (see above)."""
    import admin
    monkeypatch.setattr(admin, "_require", lambda req: ("root", None))
    return admin


class _Req:
    """The slice of server.Request the session handlers use."""
    def __init__(self, form=None, lists=None):
        self.form = form or {}
        self._lists = lists or {}

    def getlist(self, name):
        return self._lists.get(name, [])


def _new(**kw):
    kw.setdefault("candidate_name", "Alex Doe")
    kw.setdefault("workspace_user", "candidate")
    return model.create_session(**kw)


# --- forms stop offering the toggle ------------------------------------------
def test_session_form_has_no_internet_control_and_says_why():
    page = views_admin.session_new_page("root", problems=[])
    assert 'name="internet_access"' not in page
    assert "restriction is not implemented" in page


def test_edit_form_has_no_internet_control_even_for_a_restricted_row():
    s = _new(internet_access=False)
    page = views_admin.admin_edit_session("root", s, problems=[])
    assert 'name="internet_access"' not in page


# --- handlers: create records full; a stale/forged field is ignored ----------
def test_create_records_full_even_if_the_old_field_is_posted(admin_mod):
    req = _Req(form={"candidate_name": "Alex Doe", "workspace_user": "candidate",
                     "internet_access": "0"})
    resp = admin_mod.create(req)
    assert resp.status == 303
    sessions = model.list_sessions()
    assert len(sessions) == 1 and sessions[0]["internet_access"] is True


def test_edit_preserves_a_legacy_restricted_record(admin_mod):
    s = _new(internet_access=False)
    req = _Req(form={"candidate_name": "Alex Doe", "workspace_user": "candidate",
                     "internet_access": "1"})
    resp = admin_mod.edit_save(req, s["id"])
    assert resp.status == 303
    assert model.get_session(s["id"])["internet_access"] is False


# --- detail page tells the truth ---------------------------------------------
def test_detail_page_marks_legacy_restricted_as_never_enforced():
    s = _new(internet_access=False)
    page = views_admin.admin_session_detail("root", s)
    assert "recorded, never enforced" in page

    full = views_admin.admin_session_detail("root", _new())
    assert "full (unrestricted)" in full
    assert "never enforced" not in full
