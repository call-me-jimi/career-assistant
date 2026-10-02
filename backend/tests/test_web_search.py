"""Web search only adds context, so a failing search must not stop a session."""
from __future__ import annotations

import sys
import types

from backend.tools.web_search import tavily_search


def test_search_error_returns_no_results(monkeypatch):
    class FailingClient:
        def __init__(self, api_key):
            pass

        def search(self, **kwargs):
            raise ConnectionError("tavily unreachable")

    monkeypatch.setenv("TAVILY_API_KEY", "x")
    monkeypatch.setitem(sys.modules, "tavily", types.SimpleNamespace(TavilyClient=FailingClient))

    assert tavily_search("salary data scientist berlin") == []
