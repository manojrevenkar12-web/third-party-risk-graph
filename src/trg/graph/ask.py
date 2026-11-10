"""The graph interrogation layer: an analyst's question in English or German becomes Cypher, and an answer with the
facts it rests on.

Rules read the intent, the supplier and the dates; a model reads a question only when the rules cannot. Answers
come from a library of parameterised Cypher templates that run unchanged on Neo4j and Kùzu; beneficial ownership
and exposure are computed by code over the as-of ownership chain, and an answer that passes through a company
whose owners nobody publishes says so instead of guessing. Two other designs let a model write the Cypher: raw,
or checked against the schema (read-only, known relationships and properties, the as-of filter present, the whole
ownership chain for ownership questions) with the template as the fallback.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from .llm import ModelRequest
from .resolve import company_key, fold, legal_form
from .schema import FACT_PROPS, FACTS, describe

EPOCH = dt.date(1970, 1, 1)
INTENT_RULES = [
    ("exposed_suppliers", r"which of our suppliers|welche unserer lieferanten"),
    ("ubo", r"beneficial owner|ultimately controls|wirtschaftlich berechtigt"),
    ("pep_exposure", r"\bpeps?\b|politically exposed"),
    ("sanctions_exposure", r"sanction|sanktion"),
    ("adverse_media", r"adverse media|negative news"),
    ("last_ownership_change", r"last change|latest change"),
    ("directors", r"director|\bran\b|geschaeftsfuehrer"),
    ("owners", r"owned|shareholders|gesellschafter"),
]
DATE_ISO = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
DATE_DE = re.compile(r"\b(\d{2})\.(\d{2})\.(\d{4})\b")
DATE_LONG = re.compile(r"\b(\d{1,2}) (January|February|March|April|May|June|July|August|September|October|November|December) (\d{4})\b")
TEMPORAL = "r.expired_at IS NULL AND r.valid_at <= $d AND (r.invalid_at IS NULL OR r.invalid_at > $d)"
WRITE_WORDS = re.compile(r"\b(CREATE|MERGE|SET|DELETE|DETACH|REMOVE|CALL|LOAD|DROP)\b", re.I)
PROP = re.compile(r"\b[a-z]\w*\.([a-z_]+)\b")
NAME_LIT = re.compile(r"\.name = '([A-Z_]+)'")


def day(s: str) -> int:
    return (dt.date.fromisoformat(s) - EPOCH).days


def iso(d: int) -> str:
    return (EPOCH + dt.timedelta(days=d)).isoformat()


def dates(text: str) -> list[int]:
    found = []
    for m in DATE_ISO.finditer(text):
        found.append((m.start(), day(m.group(1))))
    for m in DATE_DE.finditer(text):
        found.append((m.start(), day(f"{m.group(3)}-{m.group(2)}-{m.group(1)}")))
    for m in DATE_LONG.finditer(text):
        found.append((m.start(), (dt.datetime.strptime(m.group(0), "%d %B %Y").date() - EPOCH).days))
    return [d for _, d in sorted(found)]


def chain_cypher(d: int, hops: str = "*1..4") -> str:
    """Upstream owners of $c through OWNS facts that all hold on day d (inlined: a validated integer)."""
    d = int(d)
    return (
        f"MATCH p=(o:Entity)-[:RELATES_TO{hops}]->(c:Entity {{uuid: $c}}) WHERE all(x IN relationships(p) WHERE "
        f"x.name = 'OWNS' AND x.expired_at IS NULL AND x.valid_at <= {d} AND (x.invalid_at IS NULL OR x.invalid_at > {d})) "
    )


def template(intent: str, p: dict) -> tuple[str, dict, str]:
    """(cypher, params, what the rows are) for one intent: the single-query form a model is asked to write."""
    if intent == "owners":
        return (
            (
                f"MATCH (o:Entity)-[r:RELATES_TO]->(c:Entity {{uuid: $c}}) WHERE r.name = 'OWNS' AND {TEMPORAL} "
                "RETURN o.uuid AS uuid, r.pct AS pct, r.source AS source, r.valid_at AS since"
            ),
            p,
            "uuids",
        )
    if intent == "directors":
        return (
            (f"MATCH (o:Entity)-[r:RELATES_TO]->(c:Entity {{uuid: $c}}) WHERE r.name = 'DIRECTOR_OF' AND {TEMPORAL} RETURN o.uuid AS uuid"),
            p,
            "uuids",
        )
    if intent == "ubo":
        return (
            (
                chain_cypher(p["d"])
                .replace("WHERE all(x", "WHERE o.kind = 'Person' AND all(x")
                .replace("x.name = 'OWNS'", "x.name = 'OWNS' AND x.pct >= 25")
                + "RETURN DISTINCT o.uuid AS uuid"
            ),
            p,
            "uuids",
        )
    if intent in ("sanctions_exposure", "pep_exposure"):
        fact, kind = ("LISTED_ON", "") if intent == "sanctions_exposure" else ("HOLDS_POSITION", "o.kind = 'Person' AND ")
        d = int(p["d"])
        tail = (
            f"MATCH (o)-[r:RELATES_TO]->(:Entity) WHERE {kind}r.name = '{fact}' AND r.expired_at IS NULL "
            f"AND r.valid_at <= {d} AND (r.invalid_at IS NULL OR r.invalid_at > {d}) RETURN DISTINCT o.uuid AS uuid"
        )
        return chain_cypher(d) + tail, p, "uuids"
    if intent == "adverse_media":
        return (
            (
                "MATCH (c:Entity {uuid: $c})-[r:RELATES_TO]->(t:Entity) WHERE r.name = 'ADVERSE_MEDIA' AND "
                "r.expired_at IS NULL AND r.valid_at >= $since AND r.valid_at <= $d RETURN DISTINCT r.topic AS topic"
            ),
            p,
            "topics",
        )
    if intent == "last_ownership_change":
        return (
            (
                "MATCH (o:Entity)-[r:RELATES_TO]->(c:Entity {uuid: $c}) WHERE r.name = 'OWNS' AND r.expired_at IS NULL "
                "AND r.valid_at > $start AND r.valid_at <= $d AND (r.source = 'registry' OR r.source = 'news') "
                "RETURN max(r.valid_at) AS day"
            ),
            p,
            "day",
        )
    raise KeyError(intent)


def check_cypher(cy: str, intent: str) -> str | None:
    """None if the model's Cypher may run, else why not."""
    if WRITE_WORDS.search(cy):
        return "writes to the graph"
    for name in NAME_LIT.findall(cy):
        if name not in FACTS:
            return f"unknown relationship {name}"
    allowed = set(FACT_PROPS) | {
        "uuid",
        "name",
        "kind",
        "country",
        "regno",
        "city",
        "dob",
        "supplier_ref",
        "aliases",
        "summary",
    }
    for prop in PROP.findall(cy):
        if prop not in allowed:
            return f"unknown property {prop}"
    if intent != "adverse_media" and "invalid_at" not in cy:
        return "no as-of filter"
    if intent in ("ubo", "sanctions_exposure", "pep_exposure") and "*1..4" not in cy:
        return "does not follow the whole ownership chain"
    return None


@dataclass
class Answer:
    intent: str | None
    uuids: list[str] = field(default_factory=list)
    refs: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    day: str | None = None
    complete: bool = True
    supplier: str | None = None
    as_of: str | None = None
    cypher: list[str] = field(default_factory=list)
    route: str = "template"
    note: str = ""


class Asker:
    def __init__(
        self,
        store,
        model,
        design,
        settings: dict,
        suppliers: dict[str, list[str]],
        unknown_owners: set[str],
        history_start: int,
        under_review: set[str] = frozenset(),
        registry_owners: set[str] = frozenset(),
    ):
        self.review = set(under_review)
        self.published = set(registry_owners)  # companies whose shareholders a registry publishes
        self.g, self.model, self.d, self.s = store, model, design, settings
        self.suppliers = suppliers  # uuid -> names (registry and client spellings)
        self.unknown = unknown_owners
        self.start = history_start
        self.model_calls = 0
        self.eur = 0.0

    def _run(self, a: Answer, cy: str, params: dict) -> list[dict]:
        a.cypher.append(cy)
        return self.g.run(cy, params)

    # ---- reading the question ------------------------------------------------------------------------------------
    def parse(self, text: str, qid: str | None = None) -> dict:
        low = fold(text)
        intent = next((k for k, rx in INTENT_RULES if re.search(rx, low)), None)
        ds = dates(text)
        qk = set(company_key(text).split())
        found: dict[str, int] = {}
        for uid, names in self.suppliers.items():
            for n in names:
                k = set(company_key(n).split())
                if k and k <= qk:
                    found[uid] = max(found.get(uid, 0), len(k))
        top = [u for u, s in found.items() if s == max(found.values())] if found else []
        if len(top) > 1:  # the same name for several suppliers: the legal form written in the question decides
            form = legal_form(text.split("(")[0].split(" am ")[0].split(" zum ")[0].split(" on ")[0].split(" as ")[0])
            top = [u for u in top if any(legal_form(n) == form for n in self.suppliers[u])] if form else top
        best = top[0] if len(top) == 1 else None
        self.ambiguous = len(top) > 1
        out = {
            "intent": intent,
            "c": best,
            "d": ds[-1] if ds else None,
            "since": ds[0] if len(ds) > 1 else None,
            "by": "rules",
        }
        if self.ambiguous:
            out["by"] = "rules"
            return out
        if intent is None or out["d"] is None or (intent != "exposed_suppliers" and best is None):
            req = ModelRequest(
                "intent",
                self.d.tier,
                'Read the analyst\'s question. Return JSON {"intent", "company", "date", "since"}.',
                [text],
                {"question": qid},
            )
            res = self.model.complete(req)
            self.model_calls += 1
            self.eur += res.eur
            m = res.json() or {}
            out["intent"] = out["intent"] or m.get("intent")
            if out["d"] is None and m.get("date"):
                out["d"] = day(m["date"])
            if out["c"] is None and m.get("company"):
                mk = set(company_key(m["company"]).split())
                out["c"] = next((u for u, ns in self.suppliers.items() if any(set(company_key(n).split()) == mk for n in ns)), None)
            out["by"] = "model"
        return out

    # ---- answering -----------------------------------------------------------------------------------------------
    def ask(self, text: str, qid: str | None = None) -> Answer:
        p = self.parse(text, qid)
        a = Answer(p["intent"], supplier=p["c"], as_of=iso(p["d"]) if p["d"] is not None else None)
        if p["intent"] is None or p["d"] is None or (p["intent"] != "exposed_suppliers" and p["c"] is None):
            a.complete = False
            a.note = "several suppliers have this name; say which one" if self.ambiguous else "could not read the question"
            return a
        params = {
            "c": p["c"],
            "d": p["d"],
            "since": p["since"] if p["since"] is not None else p["d"] - 365,
            "start": self.start,
        }
        if self.d.cypher != "templates" and p["intent"] != "exposed_suppliers":
            done = self._model_cypher(a, p["intent"], params, qid)
            if done:
                return a
        getattr(self, "_" + p["intent"])(a, params)
        return a

    def _model_cypher(self, a: Answer, intent: str, params: dict, qid) -> bool:
        req = ModelRequest(
            "cypher",
            self.d.tier,
            "Write one read-only Cypher query. " + describe(),
            [f"intent: {intent}", f"parameters: c={params['c']}, d={params['d']}"],
            {"question": qid, "params": params},
        )
        res = self.model.complete(req)
        self.model_calls += 1
        self.eur += res.eur
        cy = (res.json() or {}).get("cypher", "")
        if self.d.cypher == "llm_validated":
            why = check_cypher(cy, intent)
            if why:
                a.note = f"model Cypher refused ({why}); template used"
                return False
        try:
            rows = self._run(a, cy, {k: v for k, v in params.items() if "$" + k in cy})
        except Exception as e:
            a.note = f"model Cypher failed ({type(e).__name__}); template used"
            return False
        a.route = "model Cypher"
        kind = template(intent, params)[2]
        if kind == "uuids":
            a.uuids = sorted({r["uuid"] for r in rows if r.get("uuid")})
        elif kind == "topics":
            a.topics = sorted({r["topic"] for r in rows if r.get("topic")})
        else:
            v = rows[0]["day"] if rows else None
            a.day = iso(v) if v is not None else None
        return True

    def _rows(self, a, intent, params):
        cy, pr, _ = template(intent, params)
        return self._run(a, cy, {k: v for k, v in pr.items() if "$" + k in cy})

    def _stale(self, rows, d) -> bool:
        """Ownership read from a web page or article more than `max_web_age_days` before the date asked about."""
        return any(r["source"] in ("web", "news") and d - r["since"] > self.s["max_web_age_days"] for r in rows)

    def _owners(self, a, params):
        rows = self._rows(a, "owners", params)
        a.uuids = sorted({r["uuid"] for r in rows})
        if not a.uuids and params["c"] not in self.published:
            a.complete, a.note = False, "no registry or page names the owners"
        elif rows and any(r["source"] in ("web", "news") for r in rows) and sum(r["pct"] or 0 for r in rows) < 99:
            a.complete, a.note = False, "the sources name owners of only part of the shares"
        elif self._stale(rows, params["d"]):
            a.complete, a.note = False, "the only source for these owners is an old web page or article"

    def _directors(self, a, params):
        a.uuids = sorted({r["uuid"] for r in self._rows(a, "directors", params)})

    def _chain(self, a, c, d) -> tuple[dict[str, float], bool]:
        """Effective shares of every upstream owner on day d, and whether the chain is fully known."""
        share, complete, frontier = {}, True, [(c, 1.0, 0)]
        while frontier:
            x, s, depth = frontier.pop()
            if depth >= 4:
                continue
            rows = self._run(a, template("owners", {})[0], {"c": x, "d": d})
            if not rows and self.g.kinds.get(x) == "Company" and x not in self.published:
                complete = False
            if self._stale(rows, d):
                complete = False
                # an old page is not evidence of who owns the company today: do not follow it
                rows = [r for r in rows if not (r["source"] in ("web", "news") and d - r["since"] > self.s["max_web_age_days"])]
            if rows and any(r["source"] in ("web", "news") for r in rows) and sum(r["pct"] or 0 for r in rows) < 99:
                complete = False  # a page named some owners; the rest of the shares are unaccounted for
            for r in rows:
                e = s * (r["pct"] or 0) / 100
                share[r["uuid"]] = share.get(r["uuid"], 0) + e
                if self.g.kinds.get(r["uuid"]) == "Company":
                    frontier.append((r["uuid"], e, depth + 1))
        return share, complete

    def _ubo(self, a, params):
        share, complete = self._chain(a, params["c"], params["d"])
        a.uuids = sorted(u for u, s in share.items() if self.g.kinds.get(u) == "Person" and s >= 0.25 - 1e-9)
        if not complete:
            a.complete, a.note = False, "part of the ownership chain is not published"

    def _exposure(self, a, params, fact):
        share, complete = self._chain(a, params["c"], params["d"])
        parties = set(share) | {r["uuid"] for r in self._rows(a, "directors", params)}
        if fact == "LISTED_ON":
            parties.add(params["c"])
        if not parties:
            return set(), complete
        d = int(params["d"])
        rows = self._run(
            a,
            "MATCH (o:Entity)-[r:RELATES_TO]->(:Entity) WHERE o.uuid IN $ids AND r.name = $f AND "
            f"r.expired_at IS NULL AND r.valid_at <= {d} AND (r.invalid_at IS NULL OR r.invalid_at > {d}) "
            "RETURN DISTINCT o.uuid AS uuid",
            {"ids": sorted(parties), "f": fact},
        )
        if fact == "LISTED_ON" and parties & self.review:
            complete = False  # a possible list match on someone in the chain is waiting for a person
        return {r["uuid"] for r in rows}, complete

    def _sanctions_exposure(self, a, params):
        hits, complete = self._exposure(a, params, "LISTED_ON")
        a.uuids = sorted(hits)
        if not complete and not hits:
            a.complete, a.note = False, "no sanctioned party found, but part of the ownership chain is not published"

    def _pep_exposure(self, a, params):
        hits, complete = self._exposure(a, params, "HOLDS_POSITION")
        a.uuids = sorted(hits)
        if not complete and not hits:
            a.complete, a.note = False, "no PEP found, but part of the ownership chain is not published"

    def _adverse_media(self, a, params):
        a.topics = sorted({r["topic"] for r in self._rows(a, "adverse_media", params)})

    def _last_ownership_change(self, a, params):
        rows = self._rows(a, "last_ownership_change", params)
        v = rows[0]["day"] if rows else None
        a.day = iso(v) if v is not None else None
        if params["c"] not in self.published:
            a.complete, a.note = False, "the registry does not publish shareholders; only press reports, to the month"

    def _exposed_suppliers(self, a, params):
        incomplete = []
        for uid in sorted(self.suppliers):
            sub = Answer("sanctions_exposure")
            hits, complete = self._exposure(sub, {**params, "c": uid}, "LISTED_ON")
            a.cypher += sub.cypher[-1:]
            if hits:
                a.uuids.append(uid)
            elif not complete:
                incomplete.append(uid)
        a.refs = incomplete
        if incomplete:
            a.note = f"{len(incomplete)} suppliers have ownership that is not fully published"
