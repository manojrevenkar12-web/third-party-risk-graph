"""Builds the graph from the sources, as of a date.

1. The client's supplier list is matched to registry records.
2. Registry filings are ingested in order, one episode each. Who is an officer or shareholder is resolved, and the
   difference to the previous filing becomes facts that start (valid_at) or stop (invalid_at) on the filing's
   effective date. Company shareholders are followed up the chain.
3. Sanctions and PEP entries are linked to people and companies only on identifiers; a name match without them
   goes to the review queue.
4. Articles: a model extracts facts; code finds the quote, resolves the subject and checks the article's city or
   age against the entity before anything is written; a small model (or the model when it is unsure) sets the topic.
5. An agent researches the owners of holdings no registry describes, through web search, and writes only claims
   about the right company, with the newest page winning.
6. Corporate groups become Community nodes.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass, field

from .design import Design
from .llm import ModelRequest, untrusted
from .resolve import CompanyIndex, PersonIndex, PersonRef, company_key, fold, legal_form, parse_born, person_key
from .schema import TOPICS, Fact
from .store import GraphStore

EPOCH = dt.date(1970, 1, 1)
BANDS = {"75-100%": 75.0, "50-75%": 50.01, "25-50%": 25.0, "under 25%": 10.0}
CITIES = [
    "Hamburg",
    "Bremen",
    "Frankfurt am Main",
    "Stuttgart",
    "Leipzig",
    "London",
    "Manchester",
    "Leeds",
    "Rotterdam",
    "Amsterdam",
    "Zug",
    "Geneva",
    "Lugano",
    "Limassol",
    "Nicosia",
    "Dubai",
    "Sharjah",
    "Road Town",
    "Istanbul",
    "Izmir",
    "Shenzhen",
    "Ningbo",
]
CITY_COUNTRY = {
    "Hamburg": "DE",
    "Bremen": "DE",
    "Frankfurt am Main": "DE",
    "Stuttgart": "DE",
    "Leipzig": "DE",
    "London": "GB",
    "Manchester": "GB",
    "Leeds": "GB",
    "Rotterdam": "NL",
    "Amsterdam": "NL",
    "Zug": "CH",
    "Geneva": "CH",
    "Lugano": "CH",
    "Limassol": "CY",
    "Nicosia": "CY",
    "Dubai": "AE",
    "Sharjah": "AE",
    "Road Town": "VG",
    "Istanbul": "TR",
    "Izmir": "TR",
    "Shenzhen": "CN",
    "Ningbo": "CN",
}
AGE = re.compile(r"(?:,\s*(\d{2}),|\((\d{2})\))")
PAGE = re.compile(
    r"^(?P<subject>.+?), registered in (?P<city>[^,]+), is (?P<pct>\d+)% owned by (?P<owner>.+?)"
    r"(?: \((?:born (?P<born>[\d.\-]+)|(?P<ocity>[^)]+))\))?\.$"
)


def day(s: str) -> int:
    return (dt.date.fromisoformat(s) - EPOCH).days


@dataclass
class Report:
    review: list = field(default_factory=list)  # possible sanctions/PEP matches a person must look at
    rejected: list = field(default_factory=list)  # article or page facts not attached, with the reason
    schema_errors: int = 0
    model_calls: int = 0
    model_eur: float = 0.0
    model_seconds: float = 0.0
    topic_by: dict = field(default_factory=dict)
    searches: int = 0


class Pipeline:
    def __init__(self, services, model, design: Design, store: GraphStore, settings: dict, topic_model=None):
        self.svc, self.model, self.d, self.g, self.s = services, model, design, store, settings
        self.topic_model = topic_model
        self.people = PersonIndex(design.phonetic, design.identifiers)
        self.companies = CompanyIndex(design.phonetic, design.identifiers)
        self.mentions: dict[str, list[str]] = {}
        self.names: dict[str, set[str]] = {}
        self.info: dict[str, dict] = {}
        self.open: dict[tuple[str, str], dict[str, tuple[str, float | None]]] = {}  # (fact, company) -> {other: (fact uuid, pct)}
        self.registry_owners: set[str] = set()  # companies whose shareholders a registry publishes
        self.unknown_owners: set[str] = set()  # companies whose owners no registry publishes
        self.nodes: dict[tuple[str, str], str] = {}
        self.r = Report()
        self.now = services.now
        self.attached: list[tuple[str, str, str]] = []
        self.filed_as: dict[str, dict[tuple, str]] = {}
        self.web_writes: list[dict] = []

    # ---- entities ----------------------------------------------------------------------------------------------
    def _seen(self, uid: str, ref: str, name: str | None = None) -> None:
        self.mentions.setdefault(uid, []).append(ref)
        if name:
            self.names.setdefault(uid, set()).add(name)

    def node(self, kind: str, name: str) -> str:
        if (kind, name) not in self.nodes:
            self.nodes[(kind, name)] = self.g.add_entity(kind, name)
        return self.nodes[(kind, name)]

    def company(self, ref: str, name: str, country=None, regno=None, city=None, supplier_ref=None, registry: bool = False) -> str:
        uid = self.companies.resolve(name, country, regno, city)
        if uid is None:
            uid = self.g.add_entity("Company", name, country=country, regno=regno, city=city, supplier_ref=supplier_ref)
            self.companies.add(uid, name, country, regno, city)
            self.info[uid] = {"name": name, "country": country, "regno": regno, "city": city}
        elif registry:  # only a registry record may fill in what we know about a company
            inf = self.info[uid]
            for k, v in (("regno", regno), ("city", city)):
                if v and not inf.get(k):
                    inf[k] = v
                    self.g.set_entity(uid, **{k: v})
        if supplier_ref:
            self.g.set_entity(uid, supplier_ref=supplier_ref)
            self.info[uid]["supplier_ref"] = supplier_ref
        self._seen(uid, ref, name)
        return uid

    def person(self, ref: str, p: PersonRef, create: bool = True, min_evidence: int = 0) -> str | None:
        uid, _how = self.people.resolve(p)
        if uid is not None and min_evidence and self.d.identifiers:
            ev = PersonIndex.evidence(self.people.people[uid], p)
            if ev < min_evidence:
                return None
        if uid is None:
            if not create:
                return None
            uid = self.g.add_entity("Person", p.name, dob=p.dob, country=p.nationality)
            self.people.add(uid, p)
            self.info[uid] = {"name": p.name}
        else:
            self.people.merge_info(uid, p)
        self._seen(uid, ref, p.name)
        return uid

    def fact(self, f: Fact) -> str | None:
        try:
            return self.g.add_fact(f, self.now)
        except ValueError:
            self.r.schema_errors += 1
            return None

    # ---- 1-2: suppliers and registries -------------------------------------------------------------------------
    def suppliers(self, batches) -> list[tuple[str, str]]:
        crawl = []
        for s in self.svc.suppliers(batches):
            hits = self.svc.registry_search(s["name"], s["country"])
            pick = None
            if s.get("regno"):
                pick = next((h for h in hits if h["regno"] == s["regno"]), None)
            if pick is None:
                same = (
                    [h for h in hits if company_key(h["name"]) == company_key(s["name"])]
                    if self.d.phonetic
                    else [h for h in hits if h["name"] == s["name"]]
                )
                if self.d.identifiers:
                    same = [h for h in same if h["city"] == s["city"]] or same
                pick = same[0] if len(same) == 1 or (same and not self.d.identifiers) else None
            if pick is None:
                uid = self.company(f"supplier:{s['ref']}", s["name"], s["country"], s.get("regno"), s["city"], s["ref"])
                continue
            uid = self.company(f"supplier:{s['ref']}", pick["name"], pick["country"], pick["regno"], pick["city"], s["ref"], registry=True)
            self.names[uid].add(s["name"])
            crawl.append((pick["country"], pick["regno"]))
        return crawl

    def registries(self, crawl: list[tuple[str, str]]) -> None:
        done, depth = set(), {c: 0 for c in crawl}
        queue = list(crawl)
        while queue:
            key = queue.pop(0)
            if key in done:
                continue
            done.add(key)
            for f in self.svc.registry_filings(*key):
                for nxt in self._filing(f):
                    if nxt not in done and depth[key] < self.s["crawl_depth"]:
                        depth.setdefault(nxt, depth[key] + 1)
                        queue.append(nxt)

    def _filing(self, f: dict) -> list[tuple[str, str]]:
        cid = self.company(f"filing:{f['id']}", f["company"], f["country"], f["regno"], f["city"], registry=True)
        eff = day(f["effective"])
        nxt, officers, holders = [], {}, {}
        # the same registry writes the same person the same way in the company's next filing
        seen = self.filed_as.setdefault(cid, {})
        for m in f["officers"]:
            born = parse_born(m.get("born"))
            key = (m["name"], m.get("born"), m.get("nationality"))
            if key in seen:
                pid = seen[key]
                self._seen(pid, f"filing:{m['ref']}", m["name"])
            else:
                pid = seen[key] = self.person(f"filing:{m['ref']}", PersonRef(m["name"], nationality=m.get("nationality"), **born))
            officers[pid] = None
        if f["shareholders"] is not None:
            self.registry_owners.add(cid)
            for m in f["shareholders"]:
                pct = m.get("pct") or BANDS.get(m.get("band", ""), 10.0)
                if m["kind"] == "company":
                    oid = self.company(f"filing:{m['ref']}", m["name"], m["country"], m.get("regno"), m.get("city"), registry=True)
                    if m.get("regno"):
                        nxt.append((m["country"], m["regno"]))
                    else:
                        self.unknown_owners.add(oid)
                else:
                    key = (m["name"], m.get("born"), m.get("nationality"))
                    if key in seen:
                        oid = seen[key]
                        self._seen(oid, f"filing:{m['ref']}", m["name"])
                    else:
                        ref = PersonRef(m["name"], nationality=m.get("nationality"), **parse_born(m.get("born")))
                        oid = seen[key] = self.person(f"filing:{m['ref']}", ref)
                holders[oid] = pct
        else:
            self.unknown_owners.add(cid)
        ep = self.g.add_episode("registry", f["id"], eff, self.now, json.dumps(f, ensure_ascii=False), [cid, *officers, *holders])
        self._diff("DIRECTOR_OF", cid, officers, eff, ep, f["company"])
        if f["shareholders"] is not None:
            self._diff("OWNS", cid, holders, eff, ep, f["company"])
        return nxt

    def _diff(self, name: str, cid: str, now_: dict, eff: int, ep: str, cname: str) -> None:
        cur = self.open.setdefault((name, cid), {})
        for other in list(cur):
            fid, pct = cur[other]
            if other not in now_ or (name == "OWNS" and abs((now_[other] or 0) - (pct or 0)) > 0.01):
                if self.d.temporal:
                    self.g.invalidate(fid, eff)
                else:
                    self.g.invalidate(fid, 0, self.now)  # the latest-state graph forgets
                del cur[other]
        for other, pct in now_.items():
            if other in cur:
                continue
            src, dst = (other, cid)
            text = f"{self.info[other]['name']} {'owns ' + format(pct, '.0f') + '% of' if name == 'OWNS' else 'is director of'} {cname}"
            fid = self.fact(
                Fact(
                    name,
                    src,
                    dst,
                    eff if self.d.temporal else 0,
                    text,
                    "registry",
                    1.0,
                    pct=pct if name == "OWNS" else None,
                    episodes=(ep,),
                )
            )
            if fid:
                cur[other] = (fid, pct)

    # ---- 3: sanctions and PEPs ---------------------------------------------------------------------------------
    def lists(self) -> None:
        for s in self.svc.sanctions_list():
            prog = self.node("List", s["programme"])
            if s["type"] == "entity":
                eid = self.companies.resolve(s["name"], s.get("country"), s.get("regno"))
                if eid is None:
                    for a in s["aliases"]:
                        eid = eid or self.companies.resolve(a, s.get("country"), None)
                if eid is None:
                    eid = self.company(f"sanctions:{s['id']}", s["name"], s.get("country"), s.get("regno"))
                else:
                    self._seen(eid, f"sanctions:{s['id']}", s["name"])
            else:
                eid = None
            ids = [eid] if eid else self._screen(f"sanctions:{s['id']}", [s["name"], *s["aliases"]], s.get("dob"), s.get("nationality"))
            for eid in ids:
                ep = self.g.add_episode("sanctions", s["id"], day(s["listed"]), self.now, json.dumps(s), [eid, prog])
                self.fact(
                    Fact(
                        "LISTED_ON",
                        eid,
                        prog,
                        day(s["listed"]),
                        f"{s['name']} listed under {s['programme']}",
                        "sanctions",
                        1.0,
                        invalid_at=day(s["delisted"]) if s["delisted"] else None,
                        episodes=(ep,),
                    )
                )
        for p in self.svc.pep_feed():
            pos = self.node("Position", f"{p['position']} ({p['country']})")
            for pid in self._screen(f"pep:{p['id']}", [p["name"]], p.get("dob"), p.get("country")):
                ep = self.g.add_episode("pep", p["id"], day(p["since"]), self.now, json.dumps(p), [pid, pos])
                self.fact(
                    Fact(
                        "HOLDS_POSITION",
                        pid,
                        pos,
                        day(p["since"]),
                        f"{p['name']}: {p['position']}",
                        "pep",
                        1.0,
                        invalid_at=day(p["until"]) if p["until"] else None,
                        episodes=(ep,),
                    )
                )

    def _screen(self, ref: str, names: list[str], dob: str | None, nat: str | None) -> list[str]:
        """A listed person is linked to every person in the graph whose birth date (or at least its year) agrees.
        A name match without a birth date on our side goes to the review queue; nothing is linked for it."""
        born = parse_born(dob)
        cands: dict[str, object] = {}
        for n in names:
            for c in self.people.candidates(PersonRef(n, nationality=nat, **born)):
                cands[c.uuid] = c
        p = PersonRef(names[0], nationality=nat, **born)
        if not self.d.identifiers:
            if cands:
                uid = sorted(cands)[0]
                self._seen(uid, ref, names[0])
                return [uid]
        ok = [c for c in cands.values() if not PersonIndex.conflict(c, p) and PersonIndex.evidence(c, p) >= 1]
        unproven = [c for c in cands.values() if not PersonIndex.conflict(c, p) and PersonIndex.evidence(c, p) == 0]
        if unproven:
            self.r.review.append({"ref": ref, "name": names[0], "candidates": [c.uuid for c in unproven]})
        for c in ok:
            self._seen(c.uuid, ref, names[0])
            self.people.merge_info(c.uuid, p)
        if ok or unproven:
            return [c.uuid for c in ok]
        return [self.person(ref, p)]

    # ---- 4: articles -------------------------------------------------------------------------------------------
    def _ask(self, req: ModelRequest) -> dict | None:
        out = self.model.complete(req)
        self.r.model_calls += 1
        self.r.model_eur += out.eur
        self.r.model_seconds += out.seconds
        return out.json()

    def _gazetteer(self) -> None:
        self.gaz_c, self.gaz_p = {}, {}
        for uid, names in self.names.items():
            kind = self.g.kinds.get(uid)
            for n in names:
                if kind == "Company":
                    k = company_key(n)
                    if len(k) > 3:
                        self.gaz_c.setdefault(k, set()).add(uid)
                elif kind == "Person":
                    self.gaz_p.setdefault(person_key(n, self.d.phonetic), set()).add(uid)

    def _subject(self, mention: str, text: str, published: int) -> tuple[str | None, str]:
        """The entity an article means by `mention`, or None with the reason."""
        mk_c, mk_p = company_key(mention), person_key(mention, self.d.phonetic)
        cands = set()
        for k, ids in self.gaz_c.items():
            if mk_c == k or (mk_c and set(k.split()) <= set(mk_c.split())):
                cands |= ids
        cands |= self.gaz_p.get(mk_p, set())
        if not cands:
            return None, "not in the graph"
        if not self.d.context_check:
            return sorted(cands)[0], "name"
        city = next((c for c in CITIES if c in text), None)
        m = AGE.search(text)
        age = int(m.group(1) or m.group(2)) if m else None
        keep = []
        for c in cands:
            if self.g.kinds[c] == "Company":
                ec = self.info[c].get("city")
                if city and ec and city != ec:
                    continue
                if city and not ec:
                    continue
                keep.append(c)
            else:
                year = self.people.people[c].year if c in self.people.people else None
                if age is not None and year is not None:
                    born = int(year)
                    pub = (EPOCH + dt.timedelta(days=published)).year
                    if not (pub - age - 1 <= born <= pub - age):
                        continue
                elif age is not None:
                    continue
                keep.append(c)
        if len(keep) == 1:
            return keep[0], "context agrees"
        return None, "namesake: context disagrees" if not keep else "ambiguous"

    def _topic(self, text: str, model_topic: str | None) -> str | None:
        mode = self.d.topics
        if mode == "llm" or self.topic_model is None:
            self.r.topic_by["model"] = self.r.topic_by.get("model", 0) + 1
            return model_topic
        t, p = self.topic_model.predict(text)
        if mode == "small" or p >= self.s["topic_threshold"]:
            self.r.topic_by["small model"] = self.r.topic_by.get("small model", 0) + 1
            return t
        self.r.topic_by["model (small model unsure)"] = self.r.topic_by.get("model (small model unsure)", 0) + 1
        out = self._ask(
            ModelRequest(
                "topic",
                self.d.tier,
                f'Classify the adverse-media topic. One of {list(TOPICS)}. Return JSON {{"topic": ...}}.',
                [untrusted(text)],
                {"doc": self._doc},
            )
        )
        return (out or {}).get("topic")

    def articles(self) -> None:
        self._gazetteer()
        system = (
            'Extract facts from the article. Return JSON {"facts": [{"type": "adverse"|"ownership", '
            '"subject": exact name as written, "topic": one of '
            + str(list(TOPICS))
            + ', "owner": exact name as written, "pct": number, "date": "MM/YYYY"}]}. Only what the text says.'
        )
        for doc in sorted(self.svc.all_news(), key=lambda d: d["published"]):
            self._doc = doc["id"]
            out = self._ask(ModelRequest("extract", self.d.tier, system, [untrusted(doc["text"])], {"doc": doc["id"]}))
            pub = day(doc["published"])
            for f in (out or {}).get("facts", []):
                subj = f.get("subject") or ""
                if not subj or fold(subj) not in fold(doc["text"]):
                    self.r.rejected.append((doc["id"], "subject not in the text"))
                    continue
                sid, why = self._subject(subj, doc["text"], pub)
                if sid is None:
                    self.r.rejected.append((doc["id"], why))
                    continue
                self._seen(sid, f"doc:{doc['id']}")
                if f.get("type") == "adverse":
                    topic = self._topic(doc["text"], f.get("topic"))
                    if topic not in TOPICS:
                        self.r.rejected.append((doc["id"], "no valid topic"))
                        continue
                    t = self.node("Topic", topic)
                    ep = self.g.add_episode("news", doc["id"], pub, self.now, doc["text"], [sid, t])
                    if self.fact(Fact("ADVERSE_MEDIA", sid, t, pub, doc["text"][:300], "news", 0.9, topic=topic, episodes=(ep,))):
                        self.attached.append((doc["id"], sid, topic))
                elif f.get("type") == "ownership":
                    self._news_ownership(doc, f, sid, pub)

    def _news_ownership(self, doc, f, sid, pub) -> None:
        if sid in self.registry_owners or self.g.kinds.get(sid) != "Company":
            return  # a registry publishes this company's shareholders: the registry decides
        owner = f.get("owner") or ""
        pct = f.get("pct")
        if not owner or fold(owner) not in fold(doc["text"]) or not isinstance(pct, (int, float)) or f"{pct:.0f}" not in doc["text"]:
            self.r.rejected.append((doc["id"], "ownership claim not in the text"))
            return
        oid, why = self._subject(owner, doc["text"], pub)
        if oid is None and why == "not in the graph":
            oid = self._new_from_article(owner, doc["text"], pub, f"doc:{doc['id']}:owner")
        if oid is None:
            self.r.rejected.append((doc["id"], f"owner: {why}"))
            return
        when = pub
        m = re.match(r"(\d{2})/(\d{4})", f.get("date") or "")
        if m:
            when = day(f"{m.group(2)}-{m.group(1)}-01")
        ep = self.g.add_episode("news", doc["id"], pub, self.now, doc["text"], [sid, oid])
        self._web_owner(sid, oid, float(pct), when, "news", self.s["news_ownership_confidence"], ep, doc["text"])

    def _new_from_article(self, name: str, text: str, pub: int, ref: str) -> str | None:
        """An owner the graph has never seen: a person with the birth year the article's age implies, or a company in
        the city the article names."""
        after = text[fold(text).find(fold(name)) + len(name) :][:40]
        m = AGE.match(after)
        if m:
            age = int(m.group(1) or m.group(2))
            year = (EPOCH + dt.timedelta(days=pub)).year - age
            return self.person(ref, PersonRef(name, year=str(year)))
        city = next((c for c in CITIES if after.startswith(f" ({c})") or after.startswith(f" of {c}")), None)
        if city:
            return self.company(ref, name, CITY_COUNTRY.get(city), None, city)
        return None

    # ---- 5: enrichment -----------------------------------------------------------------------------------------
    def enrich(self) -> None:
        if self.d.enrichment == "off":
            return
        targets = [c for c in self.unknown_owners if c not in self.registry_owners]
        for cid in sorted(targets, key=lambda c: self.info[c]["name"]):
            inf = self.info[cid]
            queries = [inf["name"], f"{inf['name']} {inf.get('city') or ''}".strip(), f"{inf['name']} owner"]
            claims = []
            for q in queries[: self.s["max_searches_per_holding"]]:
                self.r.searches += 1
                for page in self.svc.web_search(q):
                    claim = self._read_page(page)
                    if claim is None:
                        continue
                    if self.d.enrichment == "first_result":
                        claims = [claim]
                        break
                    f1, f2 = legal_form(claim["subject"]), legal_form(inf["name"])
                    if company_key(claim["subject"]) != company_key(inf["name"]) or (f1 and f2 and f1 != f2):
                        self.r.rejected.append((page["id"], "page about another company"))
                        continue
                    if (inf.get("city") and claim["city"] != inf["city"]) or (
                        not inf.get("city") and inf.get("country") and CITY_COUNTRY.get(claim["city"]) != inf["country"]
                    ):
                        self.r.rejected.append((page["id"], "namesake: registered elsewhere"))
                        continue
                    claims.append(claim)
                if claims and (self.d.enrichment == "first_result" or len(claims) >= self.s["min_page_agreement"]):
                    if self.d.enrichment == "first_result":
                        break
            if not claims:
                continue
            claims = list({c["page"]: c for c in claims}.values())
            claims.sort(key=lambda c: c["published"])
            latest = claims[-1]["published"]
            for c in claims:
                ep = self.g.add_episode("web", c["page"], day(c["published"]), self.now, c["text"], [cid])
                oid = self._page_owner(c)
                if oid is None:
                    continue
                self._seen(cid, f"web:{c['page']}:subject")
                stale = c["published"] < latest and any(x["owner"] != c["owner"] for x in claims if x["published"] == latest)
                inv = day(latest) if stale and self.d.enrichment == "gated" else None
                self._web_owner(
                    cid,
                    oid,
                    c["pct"],
                    day(c["published"]),
                    "web",
                    self.s["web_ownership_confidence"],
                    ep,
                    c["text"],
                    invalid_at=inv,
                )

    def _read_page(self, page: dict) -> dict | None:
        out = self._ask(
            ModelRequest(
                "page",
                self.d.tier,
                'Read the page. Return JSON {"subject", "city", "pct", "owner", "born", "owner_city"} exactly as written.',
                [untrusted(page["text"])],
                {"page": page["id"]},
            )
        )
        if not out or not out.get("subject") or not out.get("owner"):
            return None
        for k in ("subject", "owner", "city"):
            if out.get(k) and fold(str(out[k])) not in fold(page["text"]):
                self.r.rejected.append((page["id"], f"{k} not in the page"))
                return None
        try:
            pct = float(out.get("pct"))
        except (TypeError, ValueError):
            return None
        return {
            "page": page["id"],
            "published": page["published"],
            "text": page["text"],
            "subject": out["subject"],
            "city": out.get("city"),
            "owner": out["owner"],
            "born": out.get("born"),
            "owner_city": out.get("owner_city"),
            "pct": pct,
        }

    def _page_owner(self, c: dict) -> str | None:
        ref = f"web:{c['page']}:owner"
        if c.get("owner_city") or any(x in c["owner"] for x in (" Ltd", " LLC", " AG", " GmbH", " B.V.")):
            return self.company(ref, c["owner"], None, None, c.get("owner_city"))
        return self.person(ref, PersonRef(c["owner"], **parse_born(c.get("born"))))

    def _web_owner(self, cid, oid, pct, valid_at, source, conf, ep, text, invalid_at=None) -> None:
        cur = self.open.setdefault(("OWNS", cid), {})
        if oid in cur:
            return
        if not self.d.temporal:
            valid_at, invalid_at = 0, None
        if invalid_at is not None and invalid_at < valid_at:
            invalid_at = valid_at
        fid = self.fact(Fact("OWNS", oid, cid, valid_at, text[:300], source, conf, pct=pct, invalid_at=invalid_at, episodes=(ep,)))
        if fid and invalid_at is None:
            cur[oid] = (fid, pct)
        if fid:
            self.unknown_owners.discard(cid)
            if source == "web":
                self.web_writes.append({"company": cid, "owner": oid, "current": invalid_at is None})

    # ---- 6: communities ----------------------------------------------------------------------------------------
    def communities(self) -> int:
        rows = self.g.run(
            "MATCH (a:Entity)-[r:RELATES_TO]->(b:Entity) WHERE r.name = 'OWNS' AND r.invalid_at IS NULL "
            "AND r.expired_at IS NULL RETURN a.uuid AS a, b.uuid AS b"
        )
        parent: dict[str, str] = {}

        def find(x):
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for row in rows:
            parent[find(row["a"])] = find(row["b"])
        groups: dict[str, list[str]] = {}
        for x in parent:
            groups.setdefault(find(x), []).append(x)
        n = 0
        for members in groups.values():
            if len(members) > 2:
                head = max(members, key=lambda m: len(self.mentions.get(m, [])))
                self.g.add_community(f"{self.info.get(head, {}).get('name', head)} group", members)
                n += 1
        return n

    def run(self, batches=("dev",)) -> Report:
        self.registries(self.suppliers(batches))
        self.lists()
        self.articles()
        self.enrich()
        self.communities()
        return self.r
