"""When a purpose-built model beats a prompted one: adverse-media topics by the small classifier, by the model
(two tiers), and by the cascade, on articles from after the development cutoff (the classifier never saw them)."""

from __future__ import annotations

import json
import time

from ..graph.ingest import day
from ..graph.llm import ModelRequest, untrusted
from ..graph.schema import TOPICS
from ..sim.model import SimModel
from ..world.generate import load_cfg
from .run import ROOT, load_pcfg, load_truth, train_topics


def evaluate(split: str = "dev") -> dict:
    """dev: 5-fold cross-validation over development articles. heldout: trained on all development articles, tested
    on the articles published after the cutoff."""
    from ..graph.topics import TopicModel

    wcfg, pcfg = load_cfg(), load_pcfg()
    t, qs = load_truth()
    cutoff = day(wcfg["dev_cutoff"])
    model = SimModel(pcfg, t, qs)
    docs = json.loads((ROOT / "data/sources/documents.json").read_text())
    labelled = [
        (d, next(f["topic"] for f in t["documents"][d["id"]]["facts"] if f["type"] == "adverse"))
        for d in docs
        if any(f["type"] == "adverse" for f in t["documents"][d["id"]]["facts"])
    ]
    dev = [x for x in labelled if day(x[0]["published"]) <= cutoff]
    if split == "dev":
        folds = [dev[i::5] for i in range(5)]
        pairs = [
            (
                TopicModel().fit(
                    [d["text"] for f in folds if f is not fold for d, _ in f],
                    [y for f in folds if f is not fold for _, y in f],
                ),
                fold,
            )
            for fold in folds
        ]
    else:
        tm, _, _ = train_topics(t, cutoff)
        pairs = [(tm, [x for x in labelled if day(x[0]["published"]) > cutoff])]
    test = [x for _, fold in pairs for x in fold]
    out = {"split": split, "articles": len(test), "trained_on": len(dev)}
    t0 = time.perf_counter()
    small = [(tm.predict(d["text"]), y) for tm, fold in pairs for d, y in fold]
    ms = 1000 * (time.perf_counter() - t0) / len(test)
    out["small model"] = {"accuracy": sum(p == y for (p, _), y in small) / len(test), "eur_per_1000": 0.0, "ms": ms}
    for tier in ("small", "large"):
        right, eur = 0, 0.0
        for d, y in test:
            req = ModelRequest(
                "topic",
                tier,
                f'Classify the adverse-media topic. One of {list(TOPICS)}. Return JSON {{"topic": ...}}.',
                [untrusted(d["text"])],
                {"doc": d["id"]},
            )
            c = model.complete(req)
            right += (c.json() or {}).get("topic") == y
            eur += c.eur
        out[f"model ({tier})"] = {
            "accuracy": right / len(test),
            "eur_per_1000": 1000 * eur / len(test),
            "ms": 1000 * pcfg["latency"][tier],
        }
    right, eur, asked = 0, 0.0, 0
    for (d, y), ((p, conf), _) in zip(test, small, strict=True):
        if conf < pcfg["settings"]["topic_threshold"]:
            req = ModelRequest(
                "topic",
                "small",
                f'Classify the adverse-media topic. One of {list(TOPICS)}. Return JSON {{"topic": ...}}.',
                [untrusted(d["text"])],
                {"doc": d["id"]},
            )
            c = model.complete(req)
            p, eur, asked = (c.json() or {}).get("topic"), eur + c.eur, asked + 1
        right += p == y
    out["cascade"] = {
        "accuracy": right / len(test),
        "eur_per_1000": 1000 * eur / len(test),
        "ms": ms + 1000 * pcfg["latency"]["small"] * asked / len(test),
        "model_share": asked / len(test),
    }
    return out


if __name__ == "__main__":
    import sys

    print(json.dumps(evaluate(sys.argv[1] if len(sys.argv) > 1 else "dev"), indent=1))
