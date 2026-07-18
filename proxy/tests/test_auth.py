"""Auth unit tests: the per-session control-file key and the
fail-closed key set."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unillm.proxy import auth  # noqa: E402


def _write_control(tmp_path, doc):
    p = tmp_path / "active.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return str(p)


def test_session_key_valid_while_active(tmp_path, monkeypatch):
    path = _write_control(tmp_path, {"state": "active", "session_id": "s1",
                                     "llm_api_key": "sk-cand-abc"})
    monkeypatch.setenv("CONTROL_FILE", path)
    monkeypatch.setenv("UNILLM_MASTER_KEY", "sk-master")
    keys = auth.get_allowed_keys()
    assert "sk-cand-abc" in keys
    assert "sk-master" in keys


def test_session_key_revoked_when_control_cleared(tmp_path, monkeypatch):
    path = _write_control(tmp_path, {"state": "inactive"})
    monkeypatch.setenv("CONTROL_FILE", path)
    monkeypatch.setenv("UNILLM_MASTER_KEY", "sk-master")
    assert auth.get_allowed_keys() == {"sk-master"}


def test_no_configured_keys_fails_closed(tmp_path, monkeypatch):
    """an empty key config must refuse requests, not allow-all."""
    import asyncio

    import pytest
    from fastapi import HTTPException
    from fastapi.security import HTTPAuthorizationCredentials

    for var in ("UNILLM_MASTER_KEY", "LITELLM_MASTER_KEY", "UNILLM_API_KEYS"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CONTROL_FILE", str(tmp_path / "absent.json"))

    class _Req:
        headers = {}

    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="sk-anything")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(auth.user_api_key_auth(_Req(), creds))
    assert exc.value.status_code == 503


def test_missing_or_broken_control_file_adds_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTROL_FILE", str(tmp_path / "nope.json"))
    monkeypatch.setenv("UNILLM_MASTER_KEY", "sk-master")
    assert auth.get_allowed_keys() == {"sk-master"}
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("CONTROL_FILE", str(broken))
    assert auth.get_allowed_keys() == {"sk-master"}
