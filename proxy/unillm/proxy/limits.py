"""Cost / DoS guards for the proxy.

Two cheap, independent guards on top of the model gate and per-session key:

  * a hard ceiling on output tokens per call, so one request can't run up an
    unbounded generation bill regardless of what the candidate asks for;
  * a per-key rolling request budget, so a hammering loop can't drive cost/load.

Both are in-process: the proxy runs a single uvicorn worker (proxy_cli.py), so a
module-level dict is the authoritative rate-limit state. Thresholds are read from the
module constants below (env-configurable at import; 0 disables either guard) — tests
override the constants directly.
"""
from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional

# Hard ceiling on output tokens per completion, whatever the request asks for. Bounds
# the cost and latency a single call can incur; an unset or larger max_tokens is
# clamped to this. 0 disables the cap.
MAX_OUTPUT_TOKENS = int(os.getenv("UNILLM_MAX_OUTPUT_TOKENS", "8192"))

# Per-key request budget over a rolling 60s window. 0 disables throttling. The default
# is generous for a single interactive candidate but stops a runaway loop.
RATE_LIMIT_PER_MIN = int(os.getenv("UNILLM_RATE_LIMIT_PER_MIN", "60"))
_WINDOW_S = 60.0

_hits: Dict[str, Deque[float]] = defaultdict(deque)
_lock = threading.Lock()


def cap_output_tokens(max_tokens: Optional[int]) -> Optional[int]:
    """Clamp a request's max_tokens to MAX_OUTPUT_TOKENS. An unset (None) value is
    pinned to the cap so a caller can't opt out of the ceiling by omitting it."""
    if MAX_OUTPUT_TOKENS <= 0:
        return max_tokens
    if max_tokens is None or max_tokens > MAX_OUTPUT_TOKENS:
        return MAX_OUTPUT_TOKENS
    return max_tokens


def check_rate_limit(key: str, *, now: Optional[float] = None) -> bool:
    """Record a request for ``key`` and report whether it is within budget.

    Returns True if the call is allowed (and counts it), False if ``key`` already made
    RATE_LIMIT_PER_MIN calls in the last 60s. A False result does NOT count the call, so
    a throttled client that backs off recovers as its window slides."""
    if RATE_LIMIT_PER_MIN <= 0:
        return True
    now = time.monotonic() if now is None else now
    cutoff = now - _WINDOW_S
    with _lock:
        dq = _hits[key]
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= RATE_LIMIT_PER_MIN:
            return False
        dq.append(now)
        return True


def reset() -> None:
    """Clear all rate-limit state (test helper)."""
    with _lock:
        _hits.clear()
