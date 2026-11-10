"""The model interface, prices, and how untrusted text reaches a model.

Articles and web pages are data: they reach a model inside an untrusted block, and nothing a model returns about
them is written to the graph until code has found it in the text and resolved it to an entity.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

OPEN, CLOSE = "<<document>>", "<</document>>"


def tokens(text: str) -> int:
    return max(1, len(text) // 4)


@dataclass
class ModelRequest:
    task: str
    tier: str
    system: str
    blocks: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)  # never sent to a provider; the simulated model reads its oracle here

    def prompt(self) -> str:
        return "\n\n".join(self.blocks)


@dataclass
class Completion:
    text: str
    in_tokens: int
    out_tokens: int
    eur: float
    seconds: float

    def json(self) -> dict | None:
        try:
            v = json.loads(self.text)
        except (json.JSONDecodeError, TypeError):
            return None
        return v if isinstance(v, dict) else None


def untrusted(text: str) -> str:
    return f"{OPEN}\n{text}\n{CLOSE}"


def price(prices: dict, tier: str, i: int, o: int) -> float:
    p = prices[tier]
    return (i * p["in_per_mtok"] + o * p["out_per_mtok"]) / 1_000_000


class AnthropicClient:  # pragma: no cover - needs a key and the network
    def __init__(self, models: dict, prices: dict):
        import anthropic

        self.client, self.models, self.prices = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"]), models, prices

    def complete(self, req: ModelRequest) -> Completion:
        import time

        t = time.perf_counter()
        msg = self.client.messages.create(
            model=self.models["anthropic"][req.tier],
            max_tokens=600,
            system=req.system,
            messages=[{"role": "user", "content": req.prompt() + "\n\nAnswer with one JSON object."}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "text", None))
        i, o = msg.usage.input_tokens, msg.usage.output_tokens
        return Completion(text, i, o, price(self.prices, req.tier, i, o), time.perf_counter() - t)


class GeminiClient:  # pragma: no cover - needs a key and the network
    def __init__(self, models: dict, prices: dict):
        from google import genai

        self.client, self.models, self.prices = genai.Client(api_key=os.environ["GEMINI_API_KEY"]), models, prices

    def complete(self, req: ModelRequest) -> Completion:
        import time

        t = time.perf_counter()
        r = self.client.models.generate_content(
            model=self.models["gemini"][req.tier],
            contents=req.system + "\n\n" + req.prompt(),
            config={"response_mime_type": "application/json"},
        )
        u = r.usage_metadata
        return Completion(
            r.text,
            u.prompt_token_count,
            u.candidates_token_count,
            price(self.prices, req.tier, u.prompt_token_count, u.candidates_token_count),
            time.perf_counter() - t,
        )
