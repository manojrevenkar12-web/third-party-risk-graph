"""A simulated model provider, because this repository is measured without a provider key.

It reads what is in its prompt. What an article or page says, and what a question means, come from the truth
(that is the simulation); it then makes its tier's mistakes at the rates in config/pipeline.toml: a wrong topic, a
missed fact, a wrong share, and in Cypher a forgotten as-of filter, a relationship that is not in the schema, owner
and owned swapped, or beneficial owners read from direct owners only.
"""

from __future__ import annotations

import hashlib
import json
import random
import re

from ..graph.llm import Completion, ModelRequest, price, tokens

TOPICS = ["bribery", "fraud", "sanctions_evasion", "money_laundering", "labour_violations", "environmental", "tax_evasion"]
PAGE = re.compile(
    r"^(?P<subject>.+?), registered in (?P<city>[^,]+), is (?P<pct>\d+)% owned by (?P<owner>.+?)"
    r"(?: \((?:born (?P<born>[\d.\-]+)|(?P<ocity>[^)]+))\))?\.$"
)


def _fold(s: str) -> str:
    return s.lower()


class SimModel:
    def __init__(self, cfg: dict, truth: dict, questions: list[dict]):
        self.cfg, self.t = cfg, truth
        self.q = {q["id"]: q for q in questions}
        self.world = truth["world"]

    def complete(self, req: ModelRequest) -> Completion:
        prompt = req.system + "\n" + req.prompt()
        h = hashlib.sha256(f"{self.cfg['sim']['seed']}|{req.task}|{req.tier}|{prompt}".encode())
        r = random.Random(int.from_bytes(h.digest()[:8], "big"))
        rates = self.cfg["sim"][req.tier]
        data = getattr(self, "_" + req.task)(req, r, rates)
        out = json.dumps(data, ensure_ascii=False)
        i, o = tokens(prompt), tokens(out)
        return Completion(out, i, o, price(self.cfg["prices"], req.tier, i, o), self.cfg["latency"][req.tier])

    def _names(self, eid: str) -> list[str]:
        if eid.startswith("P"):
            return sorted(self.world["people"][eid]["variants"], key=len, reverse=True)
        c = self.world["companies"][eid]
        return [c["name"], f"{c['stem']} {c['sector']}"]

    def _as_written(self, eid: str, text: str) -> str | None:
        low = _fold(text)
        return next((n for n in self._names(eid) if _fold(n) in low), None)

    def _extract(self, req, r, rates):
        doc = req.meta["doc"]
        text = req.blocks[-1]
        out = []
        for f in self.t["documents"][doc]["facts"]:
            if r.random() < rates["missed_fact"]:
                continue
            subj = self._as_written(f["subject"], text)
            if subj is None:
                continue
            if f["type"] == "adverse":
                topic = f["topic"] if r.random() >= rates["wrong_topic"] else r.choice([t for t in TOPICS if t != f["topic"]])
                out.append({"type": "adverse", "subject": subj, "topic": topic})
            else:
                owner = self._as_written(f["owner"], text)
                pct = f["pct"] if r.random() >= rates["wrong_pct"] else min(100.0, f["pct"] + r.choice([-10, 10, 25]))
                from datetime import date, timedelta

                d = date(1970, 1, 1) + timedelta(days=f["from"])
                out.append({"type": "ownership", "subject": subj, "owner": owner, "pct": pct, "date": d.strftime("%m/%Y")})
        return {"facts": out}

    def _topic(self, req, r, rates):
        facts = self.t["documents"][req.meta["doc"]]["facts"]
        topic = next((f["topic"] for f in facts if f["type"] == "adverse"), r.choice(TOPICS))
        return {"topic": topic if r.random() >= rates["wrong_topic"] else r.choice([t for t in TOPICS if t != topic])}

    def _page(self, req, r, rates):
        text = req.blocks[-1].split("\n")[1]
        m = PAGE.match(text)
        if not m:
            return {}
        pct = int(m.group("pct"))
        if r.random() < rates["page_misread"]:
            pct = r.choice([p for p in (51, 60, 70, 75, 100) if p != pct])
        return {
            "subject": m.group("subject"),
            "city": m.group("city"),
            "pct": pct,
            "owner": m.group("owner"),
            "born": m.group("born"),
            "owner_city": m.group("ocity"),
        }

    def _intent(self, req, r, rates):
        q = self.q[req.meta["question"]]
        intent = q["intent"]
        if r.random() < rates["intent_misread"]:
            intent = r.choice(["owners", "ubo", "directors", "sanctions_exposure"])
        return {"intent": intent, "company": q.get("supplier_name"), "date": q["as_of"], "since": q.get("since")}

    def _cypher(self, req, r, rates):
        from ..graph.ask import template

        q = self.q[req.meta["question"]]
        cy, params, _ = template(q["intent"], req.meta["params"])
        cy = cy.replace("$" + "d", str(params.get("d"))).replace("$" + "since", str(params.get("since")))
        for k, v in params.items():
            if isinstance(v, str):
                cy = cy.replace("$" + k, json.dumps(v))
        if r.random() < rates["cypher_no_time"]:
            cy = re.sub(r"\s*AND r\.valid_at <= \d+ AND \(r\.invalid_at IS NULL OR r\.invalid_at > \d+\)", "", cy)
            cy = re.sub(r"all\(x IN relationships\(p\) WHERE [^)]*\)\)", "true", cy)
        if r.random() < rates["cypher_wrong_name"]:
            cy = cy.replace("r.name = 'OWNS'", "r.name = 'OWNED_BY'", 1) if "OWNS" in cy else cy.replace("r.pct", "r.share", 1)
        if r.random() < rates["cypher_direction"] and "(o:Entity)-[r:RELATES_TO]->(c:Entity" in cy:
            cy = cy.replace("(o:Entity)-[r:RELATES_TO]->(c:Entity", "(o:Entity)<-[r:RELATES_TO]-(c:Entity", 1)
        if q["intent"] in ("ubo", "sanctions_exposure", "pep_exposure") and r.random() < rates["cypher_one_hop"]:
            cy = cy.replace("*1..4", "*1..1")
        return {"cypher": cy}
