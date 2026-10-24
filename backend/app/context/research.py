"""Deep research: Claude searches the web and reads the stories, then writes a cited brief on the asset.

Optional. Needs ANTHROPIC_API_KEY in .env and the `anthropic` package. Each run makes several web searches
and costs money on your Anthropic account, so it only runs when you press Deep research.
"""

import json
import os
import re
from datetime import datetime, timezone

from .factor import Factor, clamp

MODEL = os.environ.get("MA_RESEARCH_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("MA_RESEARCH_EFFORT", "high")  # low | medium | high | xhigh | max
MAX_SEARCHES = 10

PROMPT = """Today is {today}. I am deciding whether to go long or short {name} ({ticker}, a {kind}) on an intraday to
multi-day horizon. Search the web for what matters for that decision right now, and read the primary sources where you can:

- Company or asset news from the last few days, and how the price reacted.
- Earnings (stocks): the next report date and time, the last reported EPS and revenue against estimates, guidance changes.
- Rates and yields: where the 2-year and 10-year Treasury yields are and which way they are moving.
- The Fed: the date of the next FOMC decision, what is priced in, and recent Fed speakers.
- Economic data due in the next week (CPI, PCE, jobs, GDP) and how the last prints surprised.
- Politics and policy: tariffs, export controls, regulation, budget or shutdown news, elections, that touch this asset.
{extra}
I am not asking you to recommend a trade. Weigh the evidence and finish with ONE JSON object in a ```json block, nothing after it:
{{
  "bias": "bullish" | "bearish" | "neutral",
  "strength": 0-100 (how strongly the evidence leans that way),
  "summary": "two or three sentences",
  "bull_case": ["short points"],
  "bear_case": ["short points"],
  "catalysts": [{{"date": "YYYY-MM-DD or text", "event": "...", "why_it_matters": "..."}}],
  "next_earnings": "YYYY-MM-DD and time, or null",
  "rates_and_fed": "one or two sentences",
  "politics": "one or two sentences, or null",
  "event_risk_next_3_days": true | false
}}"""

CRYPTO_EXTRA = "- Crypto specific: ETF flows, regulation, exchange or protocol news, large liquidations, funding rates.\n"


class ResearchUnavailable(RuntimeError):
    pass


def available() -> bool:
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def parse_brief(text: str) -> dict:
    """The JSON object at the end of Claude's answer."""
    blocks = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    raw = blocks[-1] if blocks else text[text.find("{"): text.rfind("}") + 1]
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ResearchUnavailable("Claude's answer did not end with a readable brief") from exc


def collect_sources(content) -> list[dict]:
    """Every page Claude cited, then every search result it saw, without duplicates."""
    seen, out = set(), []

    def add(url, title):
        if url and url not in seen:
            seen.add(url)
            out.append({"title": title or url, "url": url})

    for block in content:
        for c in getattr(block, "citations", None) or []:
            add(getattr(c, "url", None), getattr(c, "title", None))
    cited = len(out)
    for block in content:
        if block.type == "web_search_tool_result" and isinstance(block.content, list):
            for r in block.content:
                add(getattr(r, "url", None), getattr(r, "title", None))
    for s in out[:cited]:
        s["cited"] = True
    return out


def brief_factor(brief: dict) -> Factor:
    sign = {"bullish": 1, "bearish": -1}.get(brief.get("bias"), 0)
    strength = clamp(float(brief.get("strength") or 0) / 100, 0, 1)
    return Factor(
        "research", "Deep research", f"Claude's read: {brief.get('bias', 'neutral')}",
        brief.get("summary", ""), score=sign * strength, weight=2.5,
        risk=0.5 if brief.get("event_risk_next_3_days") else 0.0, sources=brief.get("sources", [])[:8])


async def deep_research(ticker: str, name: str, kind: str) -> dict:
    if not available():
        raise ResearchUnavailable("Add ANTHROPIC_API_KEY to .env (and restart) to turn on Deep research.")
    import anthropic

    client = anthropic.AsyncAnthropic(timeout=600)
    today = datetime.now(timezone.utc).strftime("%A %d %B %Y")
    prompt = PROMPT.format(today=today, name=name, ticker=ticker, kind=kind, extra=CRYPTO_EXTRA if kind == "crypto" else "")
    messages = [{"role": "user", "content": prompt}]
    content = []
    try:
        for _ in range(5):
            # stream so a long search-and-read turn never hits a request timeout
            async with client.beta.messages.stream(
                model=MODEL,
                max_tokens=16000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",  # if the model declines, the API retries on the model Anthropic picks for that case
                output_config={"effort": EFFORT},
                tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": MAX_SEARCHES}],
                messages=messages,
            ) as stream:
                response = await stream.get_final_message()
            content += list(response.content)
            if response.stop_reason != "pause_turn":
                break
            # a long server-side search turn paused: send it back so Claude carries on
            messages = [messages[0], {"role": "assistant", "content": response.content}]
    except anthropic.APIError as exc:
        raise ResearchUnavailable(f"Claude API error: {exc}") from exc

    if response.stop_reason == "refusal":
        raise ResearchUnavailable("Claude declined this research request.")
    text = "".join(b.text for b in response.content if b.type == "text")
    brief = parse_brief(text)
    brief["sources"] = collect_sources(content)
    brief["model"] = response.model
    brief["searches"] = sum(b.type == "server_tool_use" for b in content)
    brief["created"] = int(datetime.now(timezone.utc).timestamp() * 1000)
    return brief
