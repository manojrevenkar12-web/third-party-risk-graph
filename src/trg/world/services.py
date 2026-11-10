"""The external services the platform calls, as of a date: a company registry, a sanctions list, a PEP feed, a news
API and a web search API. Each call is counted and priced; nothing returns what was published after `now`."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .generate import ROOT, day
from .names import ascii_fold

TOKEN = re.compile(r"[a-z0-9]+")
PRICE = {"registry": 0.0, "news": 0.002, "web": 0.008}  # EUR per call (web search priced like a hosted search API)


def toks(s: str) -> set[str]:
    return set(TOKEN.findall(ascii_fold(s).lower())) - {"gmbh", "ltd", "llc", "ag", "bv", "b", "v", "co", "the", "of"}


class Services:
    def __init__(self, now: str, root: Path = ROOT):
        self.now = day(now)
        src = {k: json.loads((root / f"data/sources/{k}.json").read_text())
               for k in ("filings", "sanctions", "peps", "suppliers", "documents", "web")}
        truth = json.loads((root / "data/truth/truth.json").read_text())
        self._filings = [f for f in src["filings"] if day(f["filed"]) <= self.now]
        self._sanctions = src["sanctions"]
        self._peps = src["peps"]
        self._docs = [d for d in src["documents"] if day(d["published"]) <= self.now]
        self._web = [w for w in src["web"] if day(w["published"]) <= self.now]
        self.suppliers_all = src["suppliers"]
        # the registry's index: every company it knows (namesakes included), without owners
        self._index = [{"country": c["country"], "regno": c["regno"], "name": c["name"], "city": c["city"]}
                       for c in truth["world"]["companies"].values() if c["regno"]]
        self.calls: dict[str, int] = {}

    def _count(self, kind: str) -> None:
        self.calls[kind] = self.calls.get(kind, 0) + 1

    @property
    def eur(self) -> float:
        return sum(PRICE.get(k.split(".")[0], 0) * n for k, n in self.calls.items())

    # registry
    def registry_search(self, name: str, country: str | None = None) -> list[dict]:
        self._count("registry.search")
        q = toks(name)
        hits = [(len(q & toks(c["name"])), c) for c in self._index if not country or c["country"] == country]
        hits = [h for h in hits if h[0] > 0]
        hits.sort(key=lambda h: -h[0])
        return [dict(c) for _, c in hits[:10]]

    def registry_filings(self, country: str, regno: str) -> list[dict]:
        self._count("registry.filings")
        return sorted((dict(f) for f in self._filings if f["country"] == country and f["regno"] == regno),
                      key=lambda f: (f["effective"], f["filed"]))

    # lists
    def sanctions_list(self) -> list[dict]:
        self._count("registry.sanctions")
        out = []
        for s in self._sanctions:
            if day(s["listed"]) > self.now:
                continue
            s = dict(s)
            if s["delisted"] and day(s["delisted"]) > self.now:
                s["delisted"] = None
            out.append(s)
        return out

    def pep_feed(self) -> list[dict]:
        self._count("registry.peps")
        out = []
        for p in self._peps:
            if day(p["since"]) > self.now:
                continue
            p = dict(p)
            if p["until"] and day(p["until"]) > self.now:
                p["until"] = None
            out.append(p)
        return out

    def suppliers(self, batches: tuple[str, ...]) -> list[dict]:
        return [dict(s) for s in self.suppliers_all if s["batch"] in batches]

    # search
    def news_search(self, query: str) -> list[dict]:
        self._count("news.search")
        q = toks(query)
        return [dict(d) for d in self._docs if q and q <= toks(d["text"])]

    def all_news(self) -> list[dict]:
        self._count("news.feed")
        return [dict(d) for d in self._docs]

    def web_search(self, query: str, k: int = 5) -> list[dict]:
        self._count("web.search")
        q = toks(query)
        hits = [(len(q & toks(w["text"] + " " + w["url"])), w) for w in self._web]
        hits = [h for h in hits if h[0] >= max(1, len(q) - 1)]
        hits.sort(key=lambda h: (-h[0], h[1]["published"]))
        return [dict(w) for _, w in hits[:k]]
