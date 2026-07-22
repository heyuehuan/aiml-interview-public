"""Tests for the Gemini-page chat history
and the generation-param whitelist the send endpoint applies."""
import os
import sys
import tempfile

import pytest

_TMP = tempfile.mkdtemp(prefix="portal-test-")
os.environ["PLATFORM_DB"] = os.path.join(_TMP, "platform.db")
os.environ["DATA_DIR"] = _TMP
os.environ["PORTAL_SECRET"] = "test-secret"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db  # noqa: E402
import model  # noqa: E402
from model import clean_llm_params as _clean_params  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    con = db.connect()
    con.executescript("DROP TABLE IF EXISTS sessions; DROP TABLE IF EXISTS admins;"
                      "DROP TABLE IF EXISTS chats;")
    con.commit()
    con.close()
    db.init()


SID = "session-1"


def test_chat_crud_and_title():
    chat = model.create_chat(SID, params={"temperature": 0.5})
    assert chat["title"] == "New chat" and chat["messages"] == []
    assert chat["params"] == {"temperature": 0.5}

    saved = model.append_chat_messages(SID, chat["id"], [
        {"role": "user", "content": "  Explain   gradient boosting please  "},
        {"role": "assistant", "content": "ok", "model": "gemini-3.5-flash"},
    ])
    assert saved["title"] == "Explain gradient boosting please"
    assert len(saved["messages"]) == 2

    # Title derives from the FIRST user message, once.
    model.append_chat_messages(SID, chat["id"], [{"role": "user", "content": "another"}])
    assert model.get_chat(SID, chat["id"])["title"] == "Explain gradient boosting please"

    listing = model.list_chats(SID)
    assert len(listing) == 1 and listing[0]["message_count"] == 3
    assert "messages" not in listing[0]

    assert model.delete_chat(SID, chat["id"]) is True
    assert model.list_chats(SID) == []


def test_long_title_truncated():
    chat = model.create_chat(SID)
    model.append_chat_messages(SID, chat["id"],
                               [{"role": "user", "content": "x" * 100}])
    title = model.get_chat(SID, chat["id"])["title"]
    assert len(title) == model.CHAT_TITLE_LEN + 1 and title.endswith("…")


def test_chats_are_session_scoped():
    chat = model.create_chat(SID)
    assert model.get_chat("other-session", chat["id"]) is None
    assert model.delete_chat("other-session", chat["id"]) is False
    assert model.append_chat_messages("other-session", chat["id"],
                                      [{"role": "user", "content": "hi"}]) is None
    assert model.get_chat(SID, chat["id"])["messages"] == []


def test_clean_params_whitelists_and_bounds():
    out = _clean_params({"temperature": 3.5, "top_p": -1, "max_tokens": 999999,
                         "stop": ["a", "", "b", "c", "d", "e"], "n": 5, "model": "x"})
    assert out == {"temperature": 2.0, "top_p": 0.0, "max_tokens": 8192,
                   "stop": ["a", "b", "c", "d"]}
    assert _clean_params({"stop": "END"})["stop"] == ["END"]
    assert _clean_params(None) == {}
    assert _clean_params({"temperature": "not-a-number"}) == {}
