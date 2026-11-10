"""The dashboard's data and the README's tables, from reports/*.json, plus one supplier's ownership history from the
development graph (for the time scrubber)."""

import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trg.evals.run import load_pcfg, load_truth, train_topics
from trg.evals.topics import evaluate as topics_eval
from trg.graph.ask import Asker
from trg.graph.design import Design
from trg.graph.ingest import Pipeline, day
from trg.graph.store import KuzuStore
from trg.sim.model import SimModel
from trg.world.generate import load_cfg
from trg.world.services import Services

ROOT = Path(__file__).resolve().parents[1]
EPOCH = dt.date(1970, 1, 1)
LABEL = {
    "graph-pipeline": "Graph pipeline",
    "naive-prototype": "Naive prototype",
    "no-transliteration": "Without transliteration",
    "names-only-resolution": "Names-only resolution",
    "latest-state-graph": "Latest-state graph (no time)",
    "no-context-check": "Without context checks",
    "enrichment-first-result": "Enrichment takes the first result",
    "no-enrichment": "Without web enrichment",
    "llm-cypher-validated": "Model writes Cypher, checked",
    "llm-cypher-raw": "Model writes Cypher, unchecked",
    "topics-small-model": "Topics: small model only",
    "topics-llm": "Topics: model only",
}


def iso(d):
    return (EPOCH + dt.timedelta(days=int(d))).isoformat()


def story() -> dict:
    """A development supplier whose ownership changed and whose chain reaches a sanctioned party."""
    wcfg, pcfg = load_cfg(), load_pcfg()
    t, qs = load_truth()
    svc = Services(wcfg["dev_cutoff"])
    g = KuzuStore()
    pipe = Pipeline(svc, SimModel(pcfg, t, qs), Design(), g, pcfg["settings"], train_topics(t, day(wcfg["dev_cutoff"]))[0])
    rep = pipe.run(("dev",))
    review = {u for i in rep.review for u in i["candidates"]}
    sups = {u: sorted(pipe.names.get(u, set())) for u, i in pipe.info.items() if i.get("supplier_ref")}
    asker = Asker(g, None, Design(), pcfg["settings"], sups, pipe.unknown_owners, day(wcfg["start"]), review, pipe.registry_owners)
    start, end = day(wcfg["start"]), day(wcfg["dev_cutoff"])
    best = None
    for uid in sups:
        months = list(range(start, end, 30))
        hits = [bool(asker._exposure(type("A", (), {"cypher": []})(), {"c": uid, "d": d}, "LISTED_ON")[0]) for d in months]
        changes = g.run(
            "MATCH (o:Entity)-[r:RELATES_TO]->(c:Entity {uuid: $c}) WHERE r.name = 'OWNS' AND r.valid_at > $s RETURN count(*) AS n",
            {"c": uid, "s": start},
        )[0]["n"]
        score = (len(set(hits)) == 2) * 2 + (changes > 0)
        if best is None or score > best[0]:
            best = (score, uid)
    uid = best[1]
    # every entity on the supplier's chain at any time, and the facts between them
    nodes, frontier = {uid}, [uid]
    while frontier:
        x = frontier.pop()
        for r in g.run(
            "MATCH (o:Entity)-[r:RELATES_TO]->(c:Entity {uuid: $c}) WHERE r.name = 'OWNS' OR r.name = 'DIRECTOR_OF' "
            "RETURN o.uuid AS u, r.name AS n",
            {"c": x},
        ):
            if r["u"] not in nodes:
                nodes.add(r["u"])
                if r["n"] == "OWNS":
                    frontier.append(r["u"])
    facts = g.run(
        "MATCH (a:Entity)-[r:RELATES_TO]->(b:Entity) WHERE a.uuid IN $ids AND r.expired_at IS NULL AND "
        "(r.name = 'OWNS' OR r.name = 'DIRECTOR_OF' OR r.name = 'LISTED_ON' OR r.name = 'HOLDS_POSITION') "
        "RETURN a.uuid AS a, b.uuid AS b, b.name AS bname, r.name AS fact, r.pct AS pct, r.valid_at AS v, "
        "r.invalid_at AS i, r.source AS source",
        {"ids": sorted(nodes)},
    )
    ents = g.run(
        "MATCH (n:Entity) WHERE n.uuid IN $ids RETURN n.uuid AS uuid, n.name AS name, n.kind AS kind, n.country AS country",
        {"ids": sorted(nodes)},
    )
    name = pipe.info[uid]["name"]
    q = f"Is {name} linked to any sanctioned party as of {{date}}?"
    cy = asker.ask(q.format(date=wcfg["dev_cutoff"])).cypher
    g.close()
    return {
        "supplier": uid,
        "name": name,
        "start": wcfg["start"],
        "end": wcfg["dev_cutoff"],
        "question": q,
        "cypher": cy[:3],
        "entities": ents,
        "facts": [{**f, "v": iso(f["v"]) if f["v"] else wcfg["start"], "i": iso(f["i"]) if f["i"] else None} for f in facts],
    }


def pick(path: str) -> dict:
    p = ROOT / path
    if not p.exists():
        return None
    data = json.loads(p.read_text())
    return {
        "commit": data.get("commit"),
        "designs": {n: {"label": LABEL.get(n, n), **s} for n, s in data["designs"].items()},
    }


def table(run: dict) -> str:
    rows = [
        "| Design | Right | Wrong | Abstained | Resolution precision | Article precision | Gate |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in run["designs"].values():
        rows.append(
            f"| {s['label']} | {100 * s['right']:.1f}% | {100 * s['wrong']:.1f}% | {100 * s['abstained']:.1f}% | "
            f"{100 * s['er_precision']:.1f}% | {100 * s['article_precision']:.1f}% | "
            f"{'pass' if not s['gate_failures'] else 'fail'} |"
        )
    return "\n".join(rows)


def main() -> None:
    out = {
        "dev": pick("reports/dev.json"),
        "heldout": pick("reports/heldout.json"),
        "topics": {"dev": topics_eval("dev")},
        "story": story(),
    }
    if out["heldout"]:
        out["topics"]["heldout"] = topics_eval("heldout")
    (ROOT / "reports/topics.json").write_text(json.dumps(out["topics"], indent=1))
    dest = ROOT / "web/public/data/summary.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    for k in ("dev", "heldout"):
        if out[k]:
            print(f"\n### {k}\n\n{table(out[k])}")


if __name__ == "__main__":
    main()
