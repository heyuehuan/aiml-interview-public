"""the config model_list is the model gate — unknown models must be rejected."""
import os
import sys

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unillm.proxy import proxy_server  # noqa: E402


def test_unknown_model_is_rejected_with_400():
    with pytest.raises(HTTPException) as exc:
        proxy_server._get_handler_for_model("gemini-9000-ultra")
    assert exc.value.status_code == 400


def test_configured_model_uses_its_handler(monkeypatch):
    sentinel = object()
    monkeypatch.setitem(proxy_server.vertex_handlers, "gemini-test", sentinel)
    assert proxy_server._get_handler_for_model("gemini-test") is sentinel
