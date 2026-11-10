"""Builds the graph for one design and one split, asks every question of that split, and scores everything against
the truth: entity resolution, sanctions links, article facts, web enrichment and answers."""

from __future__ import annotations

import json
import time
import tomllib
from collections import Counter
from pathlib import Path

from ..graph.ask import Asker
from ..graph.design import Design
from ..graph.ingest import Pipeline, day
from ..graph.store import KuzuStore, open_store
from ..graph.topics import TopicModel
from ..sim.model import SimModel
from ..world.generate import load_cfg
from ..world.services import Services

ROOT = Path(__file__).resolve().parents[3]


def load_pcfg() -> dict:
    return tomllib.loads((ROOT / "config/pipeline.toml").read_text())


def load_truth() -> tuple[dict, list]:
    return (
        json.loads((ROOT / "data/truth/truth.json").read_text()),
        json.loads((ROOT / "data/truth/questions.json").read_text()),
    )


def train_topics(truth: dict, cutoff: int) -> tuple[TopicModel, list, list]:
    """The small topic model is trained on labelled development articles only."""
    docs = json.loads((ROOT / "data/sources/documents.json").read_text())
    texts, labels = [], []
    for d in docs:
        f = next((x for x in truth["documents"][d["id"]]["facts"] if x["type"] == "adverse"), None)
        if f and day(d["published"]) <= cutoff:
            texts.append(d["text"])
            labels.append(f["topic"])
    return TopicModel().fit(texts, labels), texts, labels


def truth_of_ref(ref: str, t: dict) -> str | None:
    kind, _, rest = ref.partition(":")
    if kind == "filing":
        return t["filings"].get(rest)
    if kind == "sanctions":
        return t["sanctions"].get(rest)
    if kind == "pep":
        return t["peps"].get(rest)
    if kind == "supplier":
        return t["suppliers"].get(rest)
    if kind == "doc":
        did, _, role = rest.partition(":")
        f = t["documents"][did]["facts"]
        return (f[0].get("owner") if role == "owner" else f[0]["subject"]) if f else None
    if kind == "web":
        pid, _, role = rest.partition(":")
        f = t["web"][pid]["facts"][0]
        return f["subject"] if role == "subject" else f["owner"]
    return None


def resolution_metrics(mentions: dict[str, list[str]], t: dict) -> tuple[dict, dict[str, str]]:
    """Pairwise precision and recall of the graph's entities against the true identities of their mentions."""
    from math import comb

    clusters, truth_clusters, owner = Counter(), Counter(), {}
    joint = Counter()
    for uid, refs in mentions.items():
        ids = [x for x in (truth_of_ref(r, t) for r in refs) if x]
        if ids:
            owner[uid] = Counter(ids).most_common(1)[0][0]
        for x in ids:
            clusters[uid] += 1
            truth_clusters[x] += 1
            joint[(uid, x)] += 1
    tp = sum(comb(n, 2) for n in joint.values())
    pred = sum(comb(n, 2) for n in clusters.values())
    true = sum(comb(n, 2) for n in truth_clusters.values())
    return {
        "precision": tp / pred if pred else 1.0,
        "recall": tp / true if true else 1.0,
        "entities": len(mentions),
        "true_entities": len(truth_clusters),
    }, owner


def adverse_truth(q: dict, t: dict, docs: list[dict]) -> list[str]:
    """Topics of articles about the supplier itself (not a namesake) published in the question's window."""
    c = t["suppliers"][q["supplier"]]
    lo, hi = day(q["since"]), day(q["as_of"])
    out = set()
    for d in docs:
        dt_ = t["documents"][d["id"]]
        if not lo <= day(d["published"]) <= hi:
            continue
        for f in dt_["facts"]:
            if f["type"] == "adverse" and f["subject"] == c:
                out.add(f["topic"])
    return sorted(out)


def run(design: Design, split: str, store: str = "kuzu", pcfg: dict | None = None, question_ids: set | None = None) -> dict:
    wcfg, pcfg = load_cfg(), pcfg or load_pcfg()
    t, questions = load_truth()
    now = wcfg["dev_cutoff"] if split == "dev" else wcfg["end"]
    batches = ("dev",) if split == "dev" else ("dev", "heldout")
    svc = Services(now)
    model = SimModel(pcfg, t, questions)
    topic_model, _, _ = train_topics(t, day(wcfg["dev_cutoff"]))
    g = open_store(store) if store != "kuzu" else KuzuStore()
    t0 = time.perf_counter()
    pipe = Pipeline(svc, model, design, g, pcfg["settings"], topic_model)
    rep = pipe.run(batches)
    for u in pipe.unknown_owners:
        g.set_entity(u, summary="owners not published")
    build_s = time.perf_counter() - t0
    er, owner = resolution_metrics(pipe.mentions, t)
    # sanctions links: a listing attached to the wrong person or company
    false_links = sum(
        1
        for uid, refs in pipe.mentions.items()
        for r in refs
        if r.startswith("sanctions:") and owner.get(uid) not in (None, t["sanctions"][r.split(":")[1]])
    )
    suppliers = {u: sorted(pipe.names.get(u, set())) for u, inf in pipe.info.items() if inf.get("supplier_ref")}
    review = {u for item in rep.review for u in item["candidates"]}
    asker = Asker(g, model, design, pcfg["settings"], suppliers, pipe.unknown_owners, day(wcfg["start"]), review, pipe.registry_owners)
    docs = json.loads((ROOT / "data/sources/documents.json").read_text())
    docs = [d for d in docs if day(d["published"]) <= svc.now]
    rows = []
    t1 = time.perf_counter()
    for q in questions:
        if q["split"] != split or (question_ids and q["id"] not in question_ids):
            continue
        a = asker.ask(q["text"], q["id"])
        if q["intent"] == "adverse_media":
            want, got = adverse_truth(q, t, docs), a.topics
        elif q["intent"] == "last_ownership_change":
            want, got = q["answer"], [a.day] if a.day else []
        elif q["intent"] == "exposed_suppliers":
            want, got = q["answer"], sorted(pipe.info[u]["supplier_ref"] for u in a.uuids)
        else:
            want, got = q["answer"], sorted(owner.get(u, f"?{u}") for u in a.uuids)
        right = sorted(set(got)) == sorted(set(want))
        if q["intent"] == "exposed_suppliers":
            # a list answer is right when it names no one wrongly and every miss is a supplier it said it could not check
            unchecked = {pipe.info[u]["supplier_ref"] for u in a.refs}
            right = set(got) <= set(want) and set(want) - set(got) <= unchecked
        outcome = "right" if right else ("abstained" if not a.complete else "wrong")
        unexplained = (
            sorted(set(want) - set(got) - {pipe.info[u]["supplier_ref"] for u in a.refs}) if q["intent"] == "exposed_suppliers" else []
        )
        rows.append(
            {
                "unexplained": unexplained,
                "id": q["id"],
                "intent": q["intent"],
                "outcome": outcome,
                "route": a.route,
                "note": a.note,
                "queries": len(a.cypher),
                "want": want,
                "got": got,
                "text": q["text"],
            }
        )
    ask_s = time.perf_counter() - t1
    # article facts
    adverse = {"attached_right": 0, "wrong_entity": 0, "wrong_topic": 0, "namesake_attached": 0}
    for doc_id, sid, topic in pipe.attached:
        dtr = t["documents"][doc_id]
        f = next((x for x in dtr["facts"] if x["type"] == "adverse"), None)
        if f is None or owner.get(sid) != f["subject"]:
            adverse["namesake_attached" if dtr["namesake"] else "wrong_entity"] += 1
        elif topic != f["topic"]:
            adverse["wrong_topic"] += 1
        else:
            adverse["attached_right"] += 1
    known = set(owner.values())
    adverse["articles_about_graph_entities"] = sum(
        1 for d in docs if any(f["type"] == "adverse" and f["subject"] in known for f in t["documents"][d["id"]]["facts"])
    )
    # web enrichment
    w = t["world"]
    owns = w["owns"]
    web = {"right": 0, "wrong_owner": 0, "stale_kept": 0}
    for rec in pipe.web_writes:
        subj, own = owner.get(rec["company"]), owner.get(rec["owner"])
        ever = [o for o in owns if o["owned"] == subj and o["owner"] == own]
        if not ever:
            web["wrong_owner"] += 1
        elif rec["current"] and all(o["valid_to"] is not None and o["valid_to"] <= svc.now for o in ever):
            web["stale_kept"] += 1
        else:
            web["right"] += 1
    if hasattr(g, "close"):
        g.close()
    return {
        "design": design.name,
        "split": split,
        "rows": rows,
        "er": er,
        "false_sanctions_links": false_links,
        "review_queue": len(rep.review),
        "adverse": adverse,
        "web": web,
        "schema_errors": rep.schema_errors,
        "topic_by": rep.topic_by,
        "model_calls": rep.model_calls + asker.model_calls,
        "model_eur": rep.model_eur + asker.eur,
        "model_seconds": rep.model_seconds,
        "search_eur": svc.eur,
        "searches": rep.searches,
        "build_seconds": build_s,
        "ask_seconds": ask_s,
        "writes": g.writes,
        "topic_model_ms": 1000 * (topic_model.seconds / max(1, topic_model.calls)),
    }
