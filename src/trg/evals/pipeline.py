"""Every design on a split, summarised with intervals, and the gate."""

from __future__ import annotations

from collections import Counter

from ..graph.design import Design, designs
from .run import load_pcfg, run
from .stats import wilson


def summarise(res: dict) -> dict:
    rows = res["rows"]
    n = len(rows)
    c = Counter(r["outcome"] for r in rows)
    intents = sorted({r["intent"] for r in rows})
    adv = res["adverse"]
    attached = adv["attached_right"] + adv["wrong_entity"] + adv["wrong_topic"] + adv["namesake_attached"]
    return {
        "questions": n,
        "right": c["right"] / n,
        "right_ci": wilson(c["right"], n),
        "wrong": c["wrong"] / n,
        "wrong_ci": wilson(c["wrong"], n),
        "abstained": c["abstained"] / n,
        "right_when_answered": c["right"] / max(1, c["right"] + c["wrong"]),
        "by_intent": {
            i: {k: sum(1 for r in rows if r["intent"] == i and r["outcome"] == k) for k in ("right", "wrong", "abstained")} for i in intents
        },
        "model_cypher_used": sum(1 for r in rows if r["route"] == "model Cypher"),
        "er_precision": res["er"]["precision"],
        "er_recall": res["er"]["recall"],
        "false_sanctions_links": res["false_sanctions_links"],
        "review_queue": res["review_queue"],
        "articles": adv,
        "article_precision": adv["attached_right"] / max(1, attached),
        "article_recall": adv["attached_right"] / max(1, adv["articles_about_graph_entities"]),
        "web": res["web"],
        "web_precision": res["web"]["right"] / max(1, sum(res["web"].values())),
        "topic_by": res["topic_by"],
        "model_calls": res["model_calls"],
        "model_eur": res["model_eur"],
        "search_eur": res["search_eur"],
        "searches": res["searches"],
        "schema_errors": res["schema_errors"],
        "build_seconds": res["build_seconds"],
        "ask_ms_per_question": 1000 * res["ask_seconds"] / max(1, n),
        "writes": res["writes"],
        "topic_model_ms": res["topic_model_ms"],
    }


def gate(s: dict, g: dict) -> list[str]:
    fails = []
    if s["right"] < g["min_right"]:
        fails.append(f"right {s['right']:.3f} < {g['min_right']}")
    if s["wrong"] > g["max_wrong"]:
        fails.append(f"wrong {s['wrong']:.3f} > {g['max_wrong']}")
    if s["er_precision"] < g["min_er_precision"]:
        fails.append(f"resolution precision {s['er_precision']:.4f} < {g['min_er_precision']}")
    if s["false_sanctions_links"] > g["max_false_sanctions_links"]:
        fails.append(f"{s['false_sanctions_links']} sanctions listings attached to the wrong party")
    if s["article_precision"] < g["min_article_precision"]:
        fails.append(f"article precision {s['article_precision']:.3f} < {g['min_article_precision']}")
    return fails


def evaluate(split: str, only: list[str] | None = None) -> dict:
    pcfg = load_pcfg()
    out = {}
    for d in designs():
        if only and d.name not in only:
            continue
        s = summarise(run(d, split, pcfg=pcfg))
        s["gate_failures"] = gate(s, pcfg["gate"])
        out[d.name] = s
        print(
            f"{d.name:28s} right {s['right']:.3f}  wrong {s['wrong']:.3f}  abstained {s['abstained']:.3f}  "
            f"ER P {s['er_precision']:.3f}  articles P {s['article_precision']:.3f}  "
            f"{'PASS' if not s['gate_failures'] else 'FAIL'}",
            flush=True,
        )
    return out


__all__ = ["Design", "evaluate", "gate", "summarise"]
