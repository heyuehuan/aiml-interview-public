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
  * Append-only, one line per call, `O_APPEND` writes — the stream is never rewritten,
    and nothing candidate-reachable can reach this path.
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
        fh.write(line)


def record(*, endpoint, model, messages=None, prompt=None, response_text=None,
           usage=None, stream=False, latency_ms=None, error=None):
    """Append one completion to the active session's transcript. Never raises."""
    try:
        entry = {
            "ts": _now_iso(),
            "session_id": active_session_id(),
            "endpoint": endpoint,
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


async def tee_stream(chunks, *, endpoint, model, messages=None, prompt=None, started):
    """Wrap a streaming response so the transcript still captures what was said.

    Yields every chunk through untouched, accumulating the assistant deltas, and writes a
    single transcript line when the stream ends. A parse failure on one chunk costs us
    that fragment of the transcript, never the candidate's stream."""
    parts = []
    try:
        async for chunk in chunks:
            try:
                parts.append(_delta_text(chunk))
            except Exception:
                pass
            yield chunk
    finally:
        record(endpoint=endpoint, model=model, messages=messages, prompt=prompt,
               response_text="".join(p for p in parts if p), stream=True,
               latency_ms=int((time.monotonic() - started) * 1000))


def _delta_text(chunk):
    """Pull the text delta out of one SSE chunk (`data: {...}`), or "" if there is none."""
    if isinstance(chunk, (bytes, bytearray)):
        chunk = chunk.decode("utf-8", "replace")
    if not isinstance(chunk, str):
        return ""
    out = []
    for line in chunk.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[len("data:"):].strip()
        if not payload or payload == "[DONE]":
            continue
        doc = json.loads(payload)
        for ch in doc.get("choices", []):
            delta = ch.get("delta") or {}
            if delta.get("content"):
                out.append(delta["content"])
    return "".join(out)
