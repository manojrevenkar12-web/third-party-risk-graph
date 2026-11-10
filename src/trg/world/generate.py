"""Generates the world: people, companies, who owned and ran what and when, sanctions, PEPs, adverse events, and
every source the platform reads (registry filings, a sanctions list, a PEP feed, the client's supplier list,
articles, web pages), each with its truth. Days are integers since 1970-01-01."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import random
import tomllib
from pathlib import Path

from .names import CITY, FORMS, PATRONYMIC, PEOPLE, SECTORS, STEMS, ascii_fold, person_variants, umlaut_out

ROOT = Path(__file__).resolve().parents[3]
EPOCH = dt.date(1970, 1, 1)
TRANSPARENT, PARTIAL_DEFAULT = {"DE", "GB", "NL", "CH"}, {"CY", "TR", "CN"}


def day(iso: str) -> int:
    return (dt.date.fromisoformat(iso) - EPOCH).days


def iso(d: int) -> str:
    return (EPOCH + dt.timedelta(days=d)).isoformat()


def rng_for(*parts) -> random.Random:
    return random.Random(int.from_bytes(hashlib.sha256("|".join(map(str, parts)).encode()).digest()[:8], "big"))


def load_cfg() -> dict:
    return tomllib.loads((ROOT / "config/world.toml").read_text())


def _pick(r, weights: dict) -> str:
    x, acc = r.random(), 0.0
    for k, w in weights.items():
        acc += w
        if x < acc:
            return k
    return next(iter(weights))


class Builder:
    def __init__(self, cfg: dict):
        self.cfg, self.r = cfg, rng_for(cfg["seed"], "world")
        self.start, self.end, self.cutoff = day(cfg["start"]), day(cfg["end"]), day(cfg["dev_cutoff"])
        self.people: dict[str, dict] = {}
        self.companies: dict[str, dict] = {}
        self.owns: list[dict] = []
        self.directs: list[dict] = []
        self.sanctions: list[dict] = []
        self.peps: list[dict] = []
        self.events: list[dict] = []

    # ---- entities --------------------------------------------------------------------------------------------
    def person(self, culture: str, given=None, family=None) -> str:
        r = self.r
        pool = PEOPLE[culture]
        pid = f"P{len(self.people) + 1:04d}"
        g, f = given or r.choice(pool["given"]), family or r.choice(pool["family"])
        dob = iso(day("1950-01-01") + r.randint(0, 40 * 365))
        p = {"id": pid, "culture": culture, "given": g, "family": f, "dob": dob,
             "nationality": pool["nat"] if r.random() < 0.85 else r.choice(["CY", "GB", "CH", "DE", "AE"]),
             "patronymic": PATRONYMIC.get(g) if culture == "ru" else None}
        p["variants"] = person_variants(p, r)
        self.people[pid] = p
        return pid

    def company(self, country: str, kind: str, stem=None, sector=None) -> str:
        r = self.r
        cid = f"C{len(self.companies) + 1:04d}"
        while True:
            s, sec = stem or r.choice(STEMS), sector or r.choice(SECTORS[country])
            name = f"{s} {sec} {FORMS[country]}"
            if stem or not any(c["name"] == name for c in self.companies.values()):
                break
        reg = None
        if country not in self.cfg["companies"]["opaque"]:
            reg = {"DE": lambda: f"HRB {r.randint(10000, 99999)}", "GB": lambda: f"{r.randint(1000000, 14999999):08d}",
                   "NL": lambda: f"{r.randint(10000000, 99999999)}", "CH": lambda: f"CHE-{r.randint(100, 999)}.{r.randint(100, 999)}.{r.randint(100, 999)}",
                   "CY": lambda: f"HE {r.randint(100000, 499999)}", "TR": lambda: f"{r.randint(100000, 999999)}",
                   "CN": lambda: f"91{r.randint(10**15, 10**16 - 1)}"}[country]()
        c = {"id": cid, "name": name, "stem": s, "sector": sec, "form": FORMS[country], "country": country, "kind": kind,
             "regno": reg, "city": r.choice(CITY[country]), "incorporated": iso(day("1995-01-01") + r.randint(0, 27 * 365))}
        self.companies[cid] = c
        return cid

    # ---- facts -------------------------------------------------------------------------------------------------
    def own(self, owner, owned, pct, frm, to=None):
        self.owns.append({"id": f"O{len(self.owns) + 1:04d}", "owner": owner, "owned": owned, "pct": round(pct, 2),
                          "valid_from": frm, "valid_to": to})

    def direct(self, person, company, frm, to=None):
        self.directs.append({"id": f"D{len(self.directs) + 1:04d}", "person": person, "company": company,
                             "valid_from": frm, "valid_to": to})

    def build(self) -> None:
        c, r = self.cfg, self.r
        cult = c["people"]["cultures"]
        for _ in range(c["people"]["count"]):
            self.person(_pick(r, cult))
        base = list(self.people.values())
        for _ in range(c["people"]["namesakes"]):
            p = r.choice(base)
            self.person(p["culture"], p["given"], p["family"])
        cc = c["companies"]
        sup_mix = {"DE": 0.42, "GB": 0.24, "NL": 0.12, "CH": 0.08, "TR": 0.07, "CN": 0.07}
        hold_mix = {"CY": 0.3, "AE": 0.25, "VG": 0.2, "NL": 0.15, "CH": 0.1}
        sups = [self.company(_pick(r, sup_mix), "supplier") for _ in range(cc["suppliers"])]
        holds = [self.company(_pick(r, hold_mix), "holding") for _ in range(cc["holdings"])]
        self.heldout_suppliers = set(r.sample(sups, cc["heldout_suppliers"]))
        for _ in range(cc["company_namesakes"]):
            t = self.companies[r.choice(sups + holds)]
            other = r.choice([k for k in SECTORS if k != t["country"] and t["sector"] in SECTORS[k]] or
                             [k for k in SECTORS if k != t["country"]])
            sec = t["sector"] if t["sector"] in SECTORS[other] else r.choice(SECTORS[other])
            self.companies[self.company(other, "other", t["stem"], sec)]["namesake_of"] = t["id"]
        persons = list(self.people)
        early = lambda: self.start - r.randint(30, 3000)
        # holdings: owned by one or two people, sometimes by another holding
        for h in holds:
            if r.random() < 0.2 and len(holds) > 1:
                parent = r.choice([x for x in holds if x != h])
                if not self._reaches(parent, h):
                    self.own(parent, h, 100.0, early())
                    continue
            if r.random() < 0.7:
                self.own(r.choice(persons), h, 100.0, early())
            else:
                a = r.choice([51.0, 60.0, 70.0, 75.0])
                p1, p2 = r.sample(persons, 2)
                self.own(p1, h, a, early())
                self.own(p2, h, 100 - a, early())
        for x in sups + holds:
            for p in r.sample(persons, r.choice([1, 1, 2])):
                self.direct(p, x, early())
        # suppliers: people directly, a holding, or a holding plus a minority person
        for s in sups:
            k = r.random()
            if k < 0.35:
                if r.random() < 0.5:
                    self.own(r.choice(persons), s, 100.0, early())
                else:
                    a = r.choice([50.0, 60.0, 74.0, 80.0])
                    p1, p2 = r.sample(persons, 2)
                    self.own(p1, s, a, early())
                    self.own(p2, s, 100 - a, early())
            elif k < 0.75:
                self.own(r.choice(holds), s, 100.0, early())
            else:
                a = r.choice([51.0, 60.0, 75.0, 90.0])
                self.own(r.choice(holds), s, a, early())
                self.own(r.choice(persons), s, 100 - a, early())
        # changes during the period
        for s in sups:
            if r.random() < cc["ownership_change"]:
                cur = [o for o in self.owns if o["owned"] == s and o["valid_to"] is None]
                o = r.choice(cur)
                d = self.start + r.randint(60, self.end - self.start - 30)
                o["valid_to"] = d
                new = r.choice(holds) if r.random() < 0.6 else r.choice(persons)
                self.own(new, s, o["pct"], d)
        for x in sups + holds:
            if r.random() < cc["director_change"]:
                cur = [o for o in self.directs if o["company"] == x and o["valid_to"] is None]
                o = r.choice(cur)
                d = self.start + r.randint(30, self.end - self.start - 30)
                o["valid_to"] = d
                self.direct(r.choice(persons), x, d)
        self._risk(sups, holds)

    def _reaches(self, a, b) -> bool:
        """True if b already owns a (directly or not), so a owning b would make a cycle."""
        frontier, seen = [a], set()
        while frontier:
            x = frontier.pop()
            if x == b:
                return True
            seen.add(x)
            frontier += [o["owner"] for o in self.owns if o["owned"] == x and o["owner"] not in seen]
        return False

    def _risk(self, sups, holds) -> None:
        c, r = self.cfg["risk"], self.r
        upstream = list({o["owner"] for o in self.owns if o["owner"].startswith("P")} |
                        {d["person"] for d in self.directs})
        others = [p for p in self.people if p not in upstream]
        chosen = r.sample(upstream, int(c["sanctioned_people"] * 0.65)) + r.sample(others, c["sanctioned_people"] - int(c["sanctioned_people"] * 0.65))
        firms = r.sample(holds, c["sanctioned_companies"])
        listed = []
        for e in chosen + firms:
            d = r.choice([self.start - r.randint(30, 900), self.start + r.randint(30, self.end - self.start - 30)])
            listed.append({"entity": e, "listed": d, "delisted": None,
                           "programme": r.choice(["RUSSIA-EO14024", "EU 269/2014", "SDGT", "GLOMAG", "UK-RUS"])})
        for s in r.sample(listed, c["delisted"]):
            s["delisted"] = max(s["listed"], self.start) + r.randint(60, 500)
            if s["delisted"] >= self.end:
                s["delisted"] = None
        self.sanctions = listed
        for p in r.sample(list(self.people), c["peps"]):
            since = self.start - r.randint(0, 2000)
            until = r.choice([None, None, self.start + r.randint(30, self.end - self.start)])
            self.peps.append({"person": p, "since": since, "until": until,
                              "position": r.choice(["Deputy Minister of Transport", "Member of Parliament", "Regional Governor",
                                                    "Head of State Procurement Agency", "Ambassador", "Mayor"]),
                              "country": self.people[p]["nationality"]})
        targets = [*sups * 3, *upstream, *holds]
        for i in range(c["adverse_events"]):
            e = r.choice(targets)
            self.events.append({"id": f"E{i + 1:04d}", "entity": e, "topic": r.choice(c["topics"]),
                                "date": self.start + r.randint(0, self.end - self.start)})

    # ---- truth queries -----------------------------------------------------------------------------------------
    def owners_at(self, x, d):
        return [o for o in self.owns if o["owned"] == x and o["valid_from"] <= d and (o["valid_to"] is None or o["valid_to"] > d)]

    def directors_at(self, x, d):
        return [o["person"] for o in self.directs if o["company"] == x and o["valid_from"] <= d and (o["valid_to"] is None or o["valid_to"] > d)]

    def sanctioned_at(self, e, d) -> bool:
        return any(s["entity"] == e and s["listed"] <= d and (s["delisted"] is None or s["delisted"] > d) for s in self.sanctions)

    def pep_at(self, p, d) -> bool:
        return any(x["person"] == p and x["since"] <= d and (x["until"] is None or x["until"] > d) for x in self.peps)

    def chain(self, x, d, depth=4, share=1.0, out=None):
        """Every upstream owner with its effective share (summed over paths)."""
        out = {} if out is None else out
        if depth == 0:
            return out
        for o in self.owners_at(x, d):
            s = share * o["pct"] / 100
            out[o["owner"]] = out.get(o["owner"], 0) + s
            self.chain(o["owner"], d, depth - 1, s, out)
        return out


# ---------------------------------------------------------------------------------------------------------------
# Sources: what the platform reads
# ---------------------------------------------------------------------------------------------------------------
def de_date(d):
    return dt.date.fromisoformat(d).strftime("%d.%m.%Y")


def registry_name(b: Builder, eid: str, country: str, r) -> dict:
    """An officer or shareholder as a registry in `country` writes it."""
    if eid.startswith("C"):
        c = b.companies[eid]
        return {"kind": "company", "name": c["name"].upper() if country == "GB" else c["name"],
                "regno": c["regno"], "country": c["country"], "city": c["city"]}
    p = b.people[eid]
    g, f = p["given"], p["family"]
    if country == "DE":
        return {"kind": "person", "name": f"{f}, {g}", "born": de_date(p["dob"]), "city": r.choice(CITY["DE"])}
    if country == "GB":
        mon = dt.date.fromisoformat(p["dob"]).strftime("%B %Y")
        full = f"{ascii_fold(f).upper()}, {ascii_fold(g)}" + (f" {p['patronymic']}" if p.get("patronymic") else "")
        return {"kind": "person", "name": full, "born": mon, "nationality": p["nationality"]}
    if country == "NL":
        return {"kind": "person", "name": f"{g[0]}. {f}", "born": p["dob"]}
    if country == "CH":
        return {"kind": "person", "name": f"{f}, {g}", "nationality": p["nationality"]}
    return {"kind": "person", "name": umlaut_out(f"{g} {f}").upper(), "nationality": p["nationality"]}


def filings(b: Builder) -> tuple[list, dict]:
    r = rng_for(b.cfg["seed"], "filings")
    opaque, partial = set(b.cfg["companies"]["opaque"]), set(b.cfg["companies"]["partial"]) | PARTIAL_DEFAULT
    out, truth = [], {}
    for c in b.companies.values():
        if c["country"] in opaque or c["kind"] == "other":
            continue
        dates = {b.start} | {o["valid_from"] for o in b.owns if o["owned"] == c["id"] and o["valid_from"] > b.start} | \
            {o["valid_to"] for o in b.owns if o["owned"] == c["id"] and o["valid_to"]} | \
            {o["valid_from"] for o in b.directs if o["company"] == c["id"] and o["valid_from"] > b.start} | \
            {o["valid_to"] for o in b.directs if o["company"] == c["id"] and o["valid_to"]}
        for d in sorted(dates):
            filed = d + r.randint(3, 25)  # registries publish after the change
            fid = f"F{len(out) + 1:05d}"
            officers, holders = [], []
            for i, p in enumerate(b.directors_at(c["id"], d)):
                m = registry_name(b, p, c["country"], r)
                m["ref"] = f"{fid}-o{i}"
                truth[m["ref"]] = p
                officers.append(m)
            if c["country"] not in partial:
                for i, o in enumerate(b.owners_at(c["id"], d)):
                    m = registry_name(b, o["owner"], c["country"], r)
                    m["ref"] = f"{fid}-s{i}"
                    truth[m["ref"]] = o["owner"]
                    if c["country"] == "GB":
                        m["band"] = "75-100%" if o["pct"] >= 75 else "50-75%" if o["pct"] > 50 else "25-50%" if o["pct"] >= 25 else "under 25%"
                    else:
                        m["pct"] = o["pct"]
                    holders.append(m)
            out.append({"id": fid, "country": c["country"], "regno": c["regno"],
                        "company": c["name"].upper() if c["country"] == "GB" else c["name"], "city": c["city"],
                        "effective": iso(d), "filed": iso(filed), "officers": officers,
                        "shareholders": holders if c["country"] not in partial else None})
            truth[fid] = c["id"]
    return out, truth


def sanctions_list(b: Builder) -> tuple[list, dict]:
    out, truth = [], {}
    for i, s in enumerate(b.sanctions):
        e = s["entity"]
        sid = f"S{i + 1:04d}"
        if e.startswith("P"):
            p = b.people[e]
            name = f"{ascii_fold(p['family']).upper()}, {ascii_fold(p['given'])}" + (f" {p['patronymic']}" if p.get("patronymic") else "")
            out.append({"id": sid, "type": "individual", "name": name, "aliases": p["variants"][1:], "dob": p["dob"],
                        "nationality": p["nationality"], "listed": iso(s["listed"]),
                        "delisted": iso(s["delisted"]) if s["delisted"] else None, "programme": s["programme"]})
        else:
            c = b.companies[e]
            out.append({"id": sid, "type": "entity", "name": c["name"].upper(), "aliases": [f"{c['stem']} {c['sector']}"],
                        "country": c["country"], "regno": c["regno"], "listed": iso(s["listed"]),
                        "delisted": iso(s["delisted"]) if s["delisted"] else None, "programme": s["programme"]})
        truth[sid] = e
    return out, truth


def pep_feed(b: Builder) -> tuple[list, dict]:
    out, truth = [], {}
    for i, x in enumerate(b.peps):
        p = b.people[x["person"]]
        pid = f"PEP{i + 1:04d}"
        out.append({"id": pid, "name": p["variants"][-1], "dob": p["dob"], "country": x["country"],
                    "position": x["position"], "since": iso(x["since"]), "until": iso(x["until"]) if x["until"] else None})
        truth[pid] = x["person"]
    return out, truth


def supplier_list(b: Builder) -> tuple[list, dict]:
    r = rng_for(b.cfg["seed"], "suppliers")
    out, truth = [], {}
    for c in b.companies.values():
        if c["kind"] != "supplier":
            continue
        name = r.choice([c["name"], f"{c['stem']} {c['sector']}", c["name"].upper(), umlaut_out(c["name"]),
                         c["name"].replace(c["form"], "").strip() + (" " + c["form"].replace(".", "") if r.random() < 0.5 else "")])
        ref = f"SUP-{len(out) + 1:04d}"
        out.append({"ref": ref, "name": name, "country": c["country"], "city": c["city"],
                    "regno": c["regno"] if r.random() < 0.6 else None,
                    "batch": "heldout" if c["id"] in b.heldout_suppliers else "dev"})
        truth[ref] = c["id"]
    return out, truth


# ---- documents ---------------------------------------------------------------------------------------------------
TOPIC_EN = {"bribery": ["paying bribes to officials", "bribery of procurement officers", "corrupt payments to win contracts"],
            "fraud": ["accounting fraud", "invoice fraud against customers", "falsifying test certificates"],
            "sanctions_evasion": ["shipping goods to a sanctioned buyer through intermediaries", "evading export controls",
                                  "re-exporting restricted components"],
            "money_laundering": ["laundering money through trade invoices", "moving funds through shell companies",
                                 "suspicious cash transfers flagged by its bank"],
            "labour_violations": ["unpaid wages at its warehouses", "unsafe working conditions", "forced overtime"],
            "environmental": ["illegal dumping of chemical waste", "air pollution breaches", "contaminating groundwater"],
            "tax_evasion": ["hiding profits in offshore accounts", "VAT carousel fraud", "underreporting income"]}
TOPIC_DE = {"bribery": ["Bestechung von Amtsträgern", "Schmiergeldzahlungen an Einkäufer"],
            "fraud": ["Bilanzbetrug", "Rechnungsbetrug"],
            "sanctions_evasion": ["Umgehung von Sanktionen über Zwischenhändler", "Verstößen gegen Exportkontrollen"],
            "money_laundering": ["Geldwäsche über Scheinfirmen", "Geldwäsche über Handelsrechnungen"],
            "labour_violations": ["unbezahlter Löhne", "gefährlicher Arbeitsbedingungen"],
            "environmental": ["illegaler Entsorgung von Chemieabfällen", "Verstößen gegen Umweltauflagen"],
            "tax_evasion": ["Steuerhinterziehung über Offshore-Konten", "Umsatzsteuerbetrugs"]}
OPEN_EN = ["Prosecutors opened an investigation into {x} over {t}.", "{x} is under scrutiny for {t}, according to court filings.",
           "Regulators fined {x} after finding evidence of {t}.", "Former employees accuse {x} of {t}."]
OPEN_DE = ["Die Staatsanwaltschaft ermittelt gegen {x} wegen {t}.", "Gegen {x} wird wegen {t} ermittelt, wie aus Gerichtsakten hervorgeht.",
           "Die Behörden verhängten ein Bußgeld gegen {x} wegen {t}."]


def person_ctx(b, p, de=False, at=None):
    """The person's age when the article was published, as newspapers give it."""
    q = b.people[p]
    born = dt.date.fromisoformat(q["dob"])
    when = dt.date.fromisoformat(iso(at)) if at is not None else dt.date(2026, 1, 1)
    age = when.year - born.year - ((when.month, when.day) < (born.month, born.day))
    return f", {age}," if not de else f" ({age})"


def company_ctx(b, c, de=False):
    x = b.companies[c]
    return f" ({x['city']})" if de else f" of {x['city']}"


def documents(b: Builder) -> tuple[list, dict]:
    from .names import COUNTRY, COUNTRY_DE
    cfg, r = b.cfg["documents"], rng_for(b.cfg["seed"], "docs")
    docs, truth = [], {}

    def add(date, lang, text, facts, namesake=False):
        did = f"DOC{len(docs) + 1:05d}"
        docs.append({"id": did, "published": iso(date), "lang": lang, "text": text,
                     "source": r.choice(["Reuters", "Handelsblatt", "FT", "OCCRP", "Der Spiegel", "Lloyd's List", "local press"])})
        truth[did] = {"facts": facts, "namesake": namesake}

    def mention(e, de, at=None):
        if e.startswith("P"):
            v = r.choice(b.people[e]["variants"]) if not de or b.people[e]["culture"] != "ru" else b.people[e]["variants"][-2]
            return v + person_ctx(b, e, de, at)
        c = b.companies[e]
        nm = r.choice([c["name"], f"{c['stem']} {c['sector']}"])
        return nm + company_ctx(b, e, de)

    for ev in b.events:
        for k in range(r.randint(*cfg["per_event"])):
            de = r.random() < cfg["german_share"]
            d = min(ev["date"] + k * r.randint(3, 60), b.end)
            x = mention(ev["entity"], de, d)
            t = r.choice((TOPIC_DE if de else TOPIC_EN)[ev["topic"]])
            text = r.choice(OPEN_DE if de else OPEN_EN).format(x=x, t=t)
            add(d, "de" if de else "en", text,
                [{"type": "adverse", "subject": ev["entity"], "topic": ev["topic"], "event": ev["id"]}])
    # namesakes: an article about someone or something with the same name, elsewhere
    pairs = [(c["id"], c["namesake_of"]) for c in b.companies.values() if c.get("namesake_of")]
    names = {}
    for p in b.people.values():
        names.setdefault((p["given"], p["family"]), []).append(p["id"])
    pairs += [tuple(v[:2]) for v in names.values() if len(v) > 1]
    for _ in range(cfg["namesake_articles"]):
        ns, _orig = r.choice(pairs)
        de = r.random() < cfg["german_share"]
        topic = r.choice(b.cfg["risk"]["topics"])
        d = b.start + r.randint(0, b.end - b.start)
        x = mention(ns, de, d)
        t = r.choice((TOPIC_DE if de else TOPIC_EN)[topic])
        add(d, "de" if de else "en",
            r.choice(OPEN_DE if de else OPEN_EN).format(x=x, t=t),
            [{"type": "adverse", "subject": ns, "topic": topic, "event": None}], namesake=True)
    # ownership changes reported in the press
    changes = [o for o in b.owns if o["valid_from"] >= b.start]
    for o in r.sample(changes, min(cfg["ownership_articles"], len(changes))):
        de = r.random() < cfg["german_share"]
        pub = o["valid_from"] + r.randint(1, 40)
        buyer, target = mention(o["owner"], de, pub), mention(o["owned"], de, pub)
        month = dt.date.fromisoformat(iso(o["valid_from"]))
        c_buy = b.companies[o["owner"]]["country"] if o["owner"].startswith("C") else b.people[o["owner"]]["nationality"]
        if de:
            text = (f"Im {month.strftime('%m/%Y')} hat {buyer} aus {COUNTRY_DE.get(c_buy, c_buy)} "
                    f"{o['pct']:.0f} Prozent an {target} übernommen.")
        else:
            text = f"In {month.strftime('%B %Y')}, {buyer} from {COUNTRY.get(c_buy, c_buy)} acquired a {o['pct']:.0f}% stake in {target}."
        add(pub, "de" if de else "en", text,
            [{"type": "ownership", "subject": o["owned"], "owner": o["owner"], "pct": o["pct"], "from": o["valid_from"]}])
    return docs, truth


def web_pages(b: Builder) -> tuple[list, dict]:
    """Pages about holdings in registries that publish nothing: the only place their owners appear."""
    cfg, r = b.cfg["web"], rng_for(b.cfg["seed"], "web")
    opaque = set(b.cfg["companies"]["opaque"]) | set(b.cfg["companies"]["partial"]) | PARTIAL_DEFAULT
    pages, truth = [], {}

    def add(url, published, text, facts, kind):
        pid = f"W{len(pages) + 1:05d}"
        pages.append({"id": pid, "url": url, "published": iso(published), "text": text})
        truth[pid] = {"facts": facts, "kind": kind}

    def owner_text(owner, pct, c):
        if owner.startswith("P"):
            p = b.people[owner]
            who = f"{r.choice(p['variants'])} (born {de_date(p['dob']) if r.random() < 0.5 else p['dob'][:4]})"
        else:
            o = b.companies[owner]
            who = f"{o['name']} ({o['city']})"
        return f"{c['name']}, registered in {c['city']}, is {pct:.0f}% owned by {who}."

    for c in b.companies.values():
        if c["country"] not in opaque or c["kind"] != "holding":
            continue
        slug = c["name"].lower().replace(" ", "-").replace(".", "")
        for k in range(r.randint(*cfg["pages_per_opaque_holding"])):
            d = b.start + r.randint(0, b.end - b.start)
            cur = b.owners_at(c["id"], d)
            if not cur:
                continue
            o = r.choice(cur)
            add(f"https://{r.choice(['opencorporates-mirror.example', 'offshore-leaks.example', 'businessdirectory.example'])}/{slug}-{k}",
                d, owner_text(o["owner"], o["pct"], c),
                [{"type": "ownership", "subject": c["id"], "owner": o["owner"], "pct": o["pct"], "as_of": d}], "current")
    # stale pages: an owner who had sold by the time the question is asked
    sold = [o for o in b.owns if o["valid_to"] is not None]
    for o in r.sample(sold, min(cfg["stale_pages"], len(sold))):
        c = b.companies[o["owned"]]
        add(f"https://archive-directory.example/{c['stem'].lower()}", o["valid_to"] - r.randint(30, 300),
            owner_text(o["owner"], o["pct"], c),
            [{"type": "ownership", "subject": c["id"], "owner": o["owner"], "pct": o["pct"], "as_of": o["valid_to"] - 1}], "stale")
    # namesakes: a different company with the same name, elsewhere
    ns = [c for c in b.companies.values() if c.get("namesake_of")]
    for _ in range(cfg["namesake_pages"]):
        c = r.choice(ns)
        owner = r.choice(list(b.people))
        add(f"https://companies-register.example/{c['stem'].lower()}-{c['country'].lower()}", b.start + r.randint(0, 900),
            owner_text(owner, 100.0, c), [{"type": "ownership", "subject": c["id"], "owner": owner, "pct": 100.0}],
            "namesake")
    return pages, truth


# ---- questions -----------------------------------------------------------------------------------------------------
INTENTS = ["owners", "ubo", "directors", "sanctions_exposure", "pep_exposure", "adverse_media", "last_ownership_change",
           "exposed_suppliers"]


def self_question(b, r, split, intent, pool, by_id, i):
    if split == "dev":
        d = b.start + r.randint(30, b.cutoff - b.start)
    else:
        d = r.choice([b.start + r.randint(30, b.end - b.start), b.cutoff + r.randint(1, b.end - b.cutoff)])
    c = r.choice(pool)
    q = {"id": f"Q{split[0].upper()}{i + 1:04d}", "split": split, "intent": intent, "as_of": iso(d),
         "supplier": by_id[c]["ref"], "supplier_name": by_id[c]["name"]}
    if intent == "owners":
        q["answer"] = sorted(o["owner"] for o in b.owners_at(c, d))
    elif intent == "ubo":
        q["answer"] = sorted(k for k, v in b.chain(c, d).items() if k.startswith("P") and v >= 0.25 - 1e-9)
    elif intent == "directors":
        q["answer"] = sorted(b.directors_at(c, d))
    elif intent == "sanctions_exposure":
        parties = set(b.chain(c, d)) | set(b.directors_at(c, d)) | {c}
        q["answer"] = sorted(p for p in parties if b.sanctioned_at(p, d))
    elif intent == "pep_exposure":
        parties = set(b.chain(c, d)) | set(b.directors_at(c, d))
        q["answer"] = sorted(p for p in parties if p.startswith("P") and b.pep_at(p, d))
    elif intent == "adverse_media":
        since = d - 365
        q["since"] = iso(since)
        q["answer"] = sorted({e["topic"] for e in b.events if e["entity"] == c and since <= e["date"] <= d})
    elif intent == "last_ownership_change":
        ch = [o["valid_from"] for o in b.owns if o["owned"] == c and b.start <= o["valid_from"] <= d]
        q["answer"] = [iso(max(ch))] if ch else []
    elif intent == "exposed_suppliers":
        q.pop("supplier"), q.pop("supplier_name")
        batch = [x for x in by_id if split == "heldout" or x not in b.heldout_suppliers]
        exp = []
        for x in batch:
            parties = set(b.chain(x, d)) | set(b.directors_at(x, d)) | {x}
            if any(b.sanctioned_at(p, d) for p in parties):
                exp.append(by_id[x]["ref"])
        q["answer"] = sorted(exp)
    q["text"] = phrase(r, q)
    return q


PHRASES = {
    "owners": ["Who owned {n} on {d}?", "List the shareholders of {n} as of {d}.", "Wer waren die Gesellschafter von {n} am {g}?"],
    "ubo": ["Who are the beneficial owners of {n} above 25% as of {d}?", "Who ultimately controls {n} (as of {d})?",
            "Wer sind die wirtschaftlich Berechtigten der {n} zum {g}?"],
    "directors": ["Who were the directors of {n} on {d}?", "Who ran {n} as of {d}?", "Wer war Geschäftsführer der {n} am {g}?"],
    "sanctions_exposure": ["Is {n} linked to any sanctioned party as of {d}?",
                           "Any sanctions exposure for {n} on {d}, through owners or directors?",
                           "Gibt es Sanktionsbezüge bei {n} zum {g}?"],
    "pep_exposure": ["Are there PEPs among the owners or directors of {n} as of {d}?",
                     "Is {n} connected to a politically exposed person on {d}?"],
    "adverse_media": ["What adverse media came up for {n} between {s} and {d}?", "Negative news on {n} from {s} to {d}?"],
    "last_ownership_change": ["When did the ownership of {n} last change before {d}?", "Latest change of shareholders at {n} up to {d}?"],
    "exposed_suppliers": ["Which of our suppliers were exposed to sanctioned parties on {d}?",
                          "Welche unserer Lieferanten hatten am {g} Sanktionsbezüge?"],
}


def phrase(r, q) -> str:
    d = q["as_of"]
    long = dt.date.fromisoformat(d).strftime("%d %B %Y").lstrip("0")
    t = r.choice(PHRASES[q["intent"]])
    return t.format(n=q.get("supplier_name", ""), d=r.choice([d, long]), g=de_date(d), s=q.get("since", ""))


def questions(b: Builder, sup_list: list, sup_truth: dict) -> list:
    r = rng_for(b.cfg["seed"], "questions")
    out = []
    by_id = {sup_truth[s["ref"]]: s for s in sup_list}
    for split, n in (("dev", b.cfg["questions"]["dev"]), ("heldout", b.cfg["questions"]["heldout"])):
        pool = [c for c in by_id if (c in b.heldout_suppliers) == (split == "heldout")] or list(by_id)
        for i in range(n):
            intent = r.choice(INTENTS)
            want_hit = intent in ("adverse_media", "last_ownership_change", "sanctions_exposure", "pep_exposure") and r.random() < 0.5
            for _try in range(60):
                q = self_question(b, r, split, intent, pool, by_id, i)
                if not want_hit or q["answer"]:
                    break
            out.append(q)
    return out


def build_all(out: Path = ROOT / "data") -> list[Path]:
    cfg = load_cfg()
    b = Builder(cfg)
    b.build()
    src, truth = {}, {}
    src["filings"], truth["filings"] = filings(b)
    src["sanctions"], truth["sanctions"] = sanctions_list(b)
    src["peps"], truth["peps"] = pep_feed(b)
    src["suppliers"], truth["suppliers"] = supplier_list(b)
    src["documents"], truth["documents"] = documents(b)
    src["web"], truth["web"] = web_pages(b)
    qs = questions(b, src["suppliers"], truth["suppliers"])
    truth["world"] = {"people": b.people, "companies": b.companies, "owns": b.owns, "directs": b.directs,
                      "sanctions": b.sanctions, "peps": b.peps, "events": b.events,
                      "heldout_suppliers": sorted(b.heldout_suppliers)}
    files = []
    for name, obj in src.items():
        files.append(out / "sources" / f"{name}.json")
    for f, obj in zip(files, src.values(), strict=True):
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(obj, ensure_ascii=False, indent=0))
    t = out / "truth" / "truth.json"
    t.parent.mkdir(parents=True, exist_ok=True)
    t.write_text(json.dumps(truth, ensure_ascii=False))
    qf = out / "truth" / "questions.json"
    qf.write_text(json.dumps(qs, ensure_ascii=False, indent=0))
    return [*files, t, qf]
