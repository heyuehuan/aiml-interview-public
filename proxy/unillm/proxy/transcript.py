"""LLM transcript audit stream (`data/sessions/<id>/llm_transcript.jsonl`).

Every completion this proxy serves is appended, as one JSON line, to the *active*
session's transcript. This is the record of how a candidate used the LLM — one of the
three audit streams an interviewer reviews, alongside the shadow-git snapshots and the
session events.

Design notes:

  * The session is resolved per-request from the control file the portal writes
    (`/control/active.json`), not from the API key: the MVP uses one shared master key
    for every candidate, so the key identifies nothing. No active session ⇒ no session
    to attribute the call to ⇒ it lands in `unattributed.jsonl` rather than being lost.
  * Append-only, one line per call, `O_APPEND` writes under an advisory lock — the
    stream is never rewritten, lines can't interleave, and nothing
    candidate-reachable can reach this path.
  * **Logging must never break a candidate's request.** Every entry point swallows its
    own exceptions: a full disk or a malformed control file degrades the audit trail,
    it does not take the proxy down mid-interview.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone

try:
    import fcntl  # POSIX advisory file locks (the deploy target is Linux containers)
except ImportError:  # pragma: no cover - non-POSIX dev host
    fcntl = None

# Plain stdlib logger (same name the proxy's own logger uses, so output is consistent).
# Deliberately not importing unillm._logging: the audit sink must stay loadable on its
# own, without pulling in the FastAPI/Vertex import chain behind `unillm.proxy`.
verbose_proxy_logger = logging.getLogger("unillm.proxy")

DATA_DIR = os.environ.get("DATA_DIR", "/data")
CONTROL_FILE = os.environ.get("CONTROL_FILE", "/control/active.json")
# Truncate very long message bodies so one pasted dataset can't blow up the disk the
# candidate's own workspace lives on. Generous enough to keep prompts reviewable.
MAX_CHARS = int(os.environ.get("TRANSCRIPT_MAX_CHARS", "20000"))


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def active_session_id():
    """The session the control file says is live, or None."""
    try:
        with open(CONTROL_FILE, encoding="utf-8") as fh:
            doc = json.load(fh)
        if doc.get("state") == "active":
            return doc.get("session_id") or None
    except (OSError, ValueError):
        pass
    return None


def _clip(text):
    if not isinstance(text, str):
        text = json.dumps(text, default=str) if text is not None else ""
    return text if len(text) <= MAX_CHARS else text[:MAX_CHARS] + f"…[clipped {len(text) - MAX_CHARS} chars]"


def _path_for(session_id):
    if session_id:
        return os.path.join(DATA_DIR, "sessions", session_id, "llm_transcript.jsonl")
    # A call with no active session still gets recorded — losing it silently would be
    # the one thing an audit trail must not do.
    return os.path.join(DATA_DIR, "sessions", "unattributed.jsonl")


def _append(entry):
    sid = entry.get("session_id")
    path = _path_for(sid)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    line = json.dumps(entry, separators=(",", ":"), default=str) + "\n"
    with open(path, "a", encoding="utf-8") as fh:
        # A full transcript line (two ~MAX_CHARS fields) can exceed PIPE_BUF (~4 KiB),
        # above which an O_APPEND write is no longer guaranteed atomic — two writers
        # could interleave and corrupt a line. The proxy runs a single uvicorn worker
        # today (proxy_cli.py), so nothing interleaves, but serialize writers with an
        # advisory lock so a future workers>1 deploy stays safe. Best-effort:
        # a lock failure must not lose the audit line.
        locked = False
        try:
            if fcntl is not None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
                locked = True
            fh.write(line)
        finally:
            if locked:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def record(*, endpoint, model, messages=None, prompt=None, response_text=None,
           usage=None, stream=False, latency_ms=None, error=None, source=None,
           cost_usd=None):
    """Append one completion to the active session's transcript. Never raises.

    ``source`` attributes the call: "api" for a candidate's direct workspace call, "ui"
    for the portal Gemini playground, "admin-test" for the admin health check. The proxy
    derives it from *which key* authenticated the request, not from candidate-settable
    input, so it can't be spoofed (see auth.is_session_key).

    ``cost_usd`` is priced by the caller (proxy_server + budget), not here:
    this module must stay loadable without the unillm.proxy package, whose __init__
    pulls in the FastAPI app."""
    try:
        entry = {
            "ts": _now_iso(),
            "session_id": active_session_id(),
            "endpoint": endpoint,
            "source": source or "api",
            "model": model,
            "stream": bool(stream),
            "latency_ms": latency_ms,
        }
        if messages is not None:
            entry["messages"] = [
                {"role": m.get("role"), "content": _clip(m.get("content"))}
                for m in messages if isinstance(m, dict)
            ]
        if prompt is not None:
            entry["prompt"] = _clip(prompt)
        if response_text is not None:
            entry["response"] = _clip(response_text)
        if usage is not None:
            entry["usage"] = usage
        if cost_usd is not None:
            entry["cost_usd"] = round(float(cost_usd), 6)
        if error is not None:
            entry["error"] = _clip(str(error))
        _append(entry)
    except Exception as exc:  # audit must degrade, never break the interview
        verbose_proxy_logger.warning(f"transcript write failed: {exc}")


def text_of(response):
    """Best-effort assistant text out of a ChatCompletionResponse / CompletionResponse."""
    try:
        choice = response.choices[0]
        msg = getattr(choice, "message", None)
        if msg is not None and getattr(msg, "content", None) is not None:
            return msg.content
        return getattr(choice, "text", None)
    except (AttributeError, IndexError, TypeError):
        return None


def usage_of(response):
    try:
        u = getattr(response, "usage", None)
        return u.model_dump() if u is not None else None
    except AttributeError:
        return None


async def tee_stream(chunks, *, endpoint, model, messages=None, prompt=None, started,
                     source=None, price=None):
    """Wrap a streaming response so the transcript still captures what was said.

    Yields every chunk through untouched, accumulating the assistant deltas (and the
    token usage Gemini reports on its final chunk), and writes a single transcript line
    when the stream ends. ``price`` is an optional callable mapping that
    usage dict to a cost_usd — supplied by proxy_server so streamed completions count
    against the session budget exactly like non-streamed ones. A parse failure on one
    chunk costs us that fragment of the transcript, never the candidate's stream."""
    parts = []
    usage = None
    try:
        async for chunk in chunks:
            try:
                parts.append(_delta_text(chunk))
                usage = _chunk_usage(chunk) or usage
            except Exception:
                pass
            yield chunk
    finally:
        cost = None
        if price is not None:
            try:
                cost = price(usage)
            except Exception:  # accounting must never break the audit line
                cost = None
        record(endpoint=endpoint, model=model, messages=messages, prompt=prompt,
               response_text="".join(p for p in parts if p), stream=True, usage=usage,
               cost_usd=cost,
               latency_ms=int((time.monotonic() - started) * 1000), source=source)


def _sse_docs(chunk):
    """The JSON payloads of one SSE chunk's `data: {...}` lines."""
    if isinstance(chunk, (bytes, bytearray)):
        chunk = chunk.decode("utf-8", "replace")
    if not isinstance(chunk, str):
        return
    for line in chunk.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[len("data:"):].strip()
        if not payload or payload == "[DONE]":
            continue
        yield json.loads(payload)


def _delta_text(chunk):
    """Pull the text delta out of one SSE chunk (`data: {...}`), or "" if there is none."""
    out = []
    for doc in _sse_docs(chunk):
        for ch in doc.get("choices", []):
            delta = ch.get("delta") or {}
            if delta.get("content"):
                out.append(delta["content"])
    return "".join(out)


def _chunk_usage(chunk):
    """The OpenAI-shaped `usage` object carried by an SSE chunk, or None. Gemini reports
    usageMetadata on its final streamed chunk; the vertex handler maps it through."""
    usage = None
    for doc in _sse_docs(chunk):
        if isinstance(doc.get("usage"), dict):
            usage = doc["usage"]
    return usage
