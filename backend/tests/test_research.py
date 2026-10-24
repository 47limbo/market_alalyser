import asyncio
from types import SimpleNamespace as NS

import anthropic

from app.context import research


class FakeStream:
    def __init__(self, message):
        self.message = message

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get_final_message(self):
        return self.message


def test_deep_research_resumes_pause_turn_and_collects_sources(monkeypatch):
    result = NS(type="web_search_tool_result", content=[NS(url="https://a.com", title="A"), NS(url="https://b.com", title="B")])
    paused = NS(stop_reason="pause_turn", model="claude-opus-5-5", content=[NS(type="server_tool_use"), result])
    final = NS(stop_reason="end_turn", model="claude-opus-5-5", content=[
        NS(type="text", text="Yields fell.", citations=[NS(url="https://b.com", title="B")]),
        NS(type="text", text='```json\n{"bias": "bullish", "strength": 70, "summary": "s"}\n```', citations=None),
    ])
    calls = []

    class FakeClient:
        def __init__(self, **kw):
            self.beta = NS(messages=NS(stream=self.stream))

        def stream(self, **kw):
            calls.append(kw)
            return FakeStream(paused if len(calls) == 1 else final)

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(anthropic, "AsyncAnthropic", FakeClient)
    brief = asyncio.run(research.deep_research("NVDA", "Nvidia", "stock"))
    assert len(calls) == 2 and calls[1]["messages"][1]["role"] == "assistant"
    assert calls[0]["fallbacks"] == "default" and calls[0]["tools"][0]["type"] == "web_search_20260209"
    assert brief["bias"] == "bullish" and brief["searches"] == 1
    assert brief["sources"][0] == {"title": "B", "url": "https://b.com", "cited": True} and brief["sources"][1]["url"] == "https://a.com"
    f = research.brief_factor(brief)
    assert f.score == 0.7 and f.weight == 2.5
