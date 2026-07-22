"""Tests for the LLM transcript audit stream (proxy/unillm/proxy/transcript.py).

This stream is one of the three things an interviewer reviews after a session. The properties that matter: calls land against the
right session, a call with no active session is still not lost, and a failure to log
never breaks the candidate's request.
"""
import importlib.util
import json
import os

import pytest

_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "unillm", "proxy", "transcript.py")


@pytest.fixture
def tx(tmp_path, monkeypatch):
    """Load the audit sink against a throwaway data dir + control file.

    Loaded straight from its file rather than as `unillm.proxy.transcript`: that package's
    __init__ imports the whole FastAPI app, and the audit sink deliberately does not need
    it (it must be able to write a line even in a stripped environment)."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CONTROL_FILE", str(tmp_path / "active.json"))
    spec = importlib.util.spec_from_file_location("transcript_under_test", _SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _activate(tx, sid):
    with open(tx.CONTROL_FILE, "w") as fh:
        json.dump({"state": "active", "session_id": sid}, fh)


def _lines(tx, sid):
    path = os.path.join(tx.DATA_DIR, "sessions", sid, "llm_transcript.jsonl")
    with open(path) as fh:
        return [json.loads(l) for l in fh]


def test_completion_is_attributed_to_the_active_session(tx):
    _activate(tx, "sess-1")
    tx.record(endpoint="chat.completions", model="gemini-3.5-flash",
              messages=[{"role": "user", "content": "hi"}],
              response_text="hello", usage={"total_tokens": 7}, latency_ms=120)

    (entry,) = _lines(tx, "sess-1")
    assert entry["session_id"] == "sess-1"
    assert entry["model"] == "gemini-3.5-flash"
    assert entry["messages"] == [{"role": "user", "content": "hi"}]
    assert entry["response"] == "hello"
    assert entry["usage"] == {"total_tokens": 7}
    assert entry["ts"].endswith("+00:00")


def test_source_defaults_to_api_and_is_recorded(tx):
    _activate(tx, "sess-1")
    tx.record(endpoint="chat.completions", model="m", response_text="a")           # no source
    tx.record(endpoint="chat.completions", model="m", response_text="b", source="ui")
    first, second = _lines(tx, "sess-1")
    assert first["source"] == "api"        # candidate/direct is the default attribution
    assert second["source"] == "ui"        # portal playground tag preserved


def test_stream_is_append_only_across_calls(tx):
    _activate(tx, "sess-1")
    for i in range(3):
        tx.record(endpoint="chat.completions", model="m", messages=[], response_text=str(i))
    assert [e["response"] for e in _lines(tx, "sess-1")] == ["0", "1", "2"]


def test_calls_follow_the_control_file_to_the_next_session(tx):
    _activate(tx, "sess-1")
    tx.record(endpoint="chat.completions", model="m", response_text="first")
    _activate(tx, "sess-2")
    tx.record(endpoint="chat.completions", model="m", response_text="second")

    assert [e["response"] for e in _lines(tx, "sess-1")] == ["first"]
    assert [e["response"] for e in _lines(tx, "sess-2")] == ["second"]


def test_call_with_no_active_session_is_recorded_not_dropped(tx):
    with open(tx.CONTROL_FILE, "w") as fh:
        json.dump({"state": "inactive"}, fh)
    tx.record(endpoint="chat.completions", model="m", response_text="orphan")

    path = os.path.join(tx.DATA_DIR, "sessions", "unattributed.jsonl")
    with open(path) as fh:
        entry = json.loads(fh.readline())
    assert entry["session_id"] is None and entry["response"] == "orphan"


def test_logging_failure_never_breaks_the_request(tx, monkeypatch):
    """The candidate's completion must survive a broken audit sink."""
    _activate(tx, "sess-1")
    monkeypatch.setattr(tx, "_append", lambda e: (_ for _ in ()).throw(OSError("disk full")))
    tx.record(endpoint="chat.completions", model="m", response_text="x")   # must not raise


def test_oversized_content_is_clipped(tx):
    _activate(tx, "sess-1")
    tx.record(endpoint="chat.completions", model="m",
              messages=[{"role": "user", "content": "x" * (tx.MAX_CHARS + 500)}],
              response_text="ok")
    content = _lines(tx, "sess-1")[0]["messages"][0]["content"]
    assert len(content) < tx.MAX_CHARS + 200 and "clipped" in content


def test_errors_are_recorded(tx):
    _activate(tx, "sess-1")
    tx.record(endpoint="chat.completions", model="m", error=RuntimeError("vertex 429"))
    assert "vertex 429" in _lines(tx, "sess-1")[0]["error"]


@pytest.mark.asyncio
async def test_streamed_reply_is_teed_into_the_transcript(tx):
    """A streaming candidate call must reach them intact AND be audited."""
    _activate(tx, "sess-1")

    async def chunks():
        for tok in ["Hel", "lo"]:
            yield f'data: {{"choices":[{{"delta":{{"content":"{tok}"}}}}]}}\n\n'
        yield "data: [DONE]\n\n"

    import time
    seen = []
    async for c in tx.tee_stream(chunks(), endpoint="chat.completions", model="m",
                                 messages=[{"role": "user", "content": "hi"}],
                                 started=time.monotonic()):
        seen.append(c)

    assert len(seen) == 3                       # candidate got every chunk, untouched
    entry = _lines(tx, "sess-1")[0]
    assert entry["response"] == "Hello" and entry["stream"] is True
