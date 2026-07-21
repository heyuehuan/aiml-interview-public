"""the proxy caps output tokens and throttles per-key request rate."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unillm.proxy import limits  # noqa: E402


@pytest.fixture(autouse=True)
def _clean():
    limits.reset()
    yield
    limits.reset()


# --- output-token cap -------------------------------------------------------
def test_unset_max_tokens_is_pinned_to_the_cap(monkeypatch):
    monkeypatch.setattr(limits, "MAX_OUTPUT_TOKENS", 8192)
    assert limits.cap_output_tokens(None) == 8192


def test_oversized_max_tokens_is_clamped(monkeypatch):
    monkeypatch.setattr(limits, "MAX_OUTPUT_TOKENS", 8192)
    assert limits.cap_output_tokens(1_000_000) == 8192


def test_small_max_tokens_is_left_alone(monkeypatch):
    monkeypatch.setattr(limits, "MAX_OUTPUT_TOKENS", 8192)
    assert limits.cap_output_tokens(256) == 256


def test_cap_of_zero_disables_the_ceiling(monkeypatch):
    monkeypatch.setattr(limits, "MAX_OUTPUT_TOKENS", 0)
    assert limits.cap_output_tokens(None) is None
    assert limits.cap_output_tokens(1_000_000) == 1_000_000


# --- per-key rate limit -----------------------------------------------------
def test_rate_limit_blocks_after_budget(monkeypatch):
    monkeypatch.setattr(limits, "RATE_LIMIT_PER_MIN", 3)
    now = 1000.0
    assert all(limits.check_rate_limit("k", now=now) for _ in range(3))
    assert not limits.check_rate_limit("k", now=now)          # 4th within window: blocked


def test_rate_limit_is_per_key(monkeypatch):
    monkeypatch.setattr(limits, "RATE_LIMIT_PER_MIN", 1)
    assert limits.check_rate_limit("a", now=1000.0)
    assert not limits.check_rate_limit("a", now=1000.0)
    assert limits.check_rate_limit("b", now=1000.0)           # a different key is unaffected


def test_window_slides(monkeypatch):
    monkeypatch.setattr(limits, "RATE_LIMIT_PER_MIN", 2)
    assert limits.check_rate_limit("k", now=1000.0)
    assert limits.check_rate_limit("k", now=1000.0)
    assert not limits.check_rate_limit("k", now=1000.0)
    assert limits.check_rate_limit("k", now=1061.0)           # >60s later: old hits expired


def test_rate_limit_disabled_when_zero(monkeypatch):
    monkeypatch.setattr(limits, "RATE_LIMIT_PER_MIN", 0)
    assert all(limits.check_rate_limit("k", now=1000.0) for _ in range(100))
