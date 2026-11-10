"""The graph's data model: the product's most important artifact, so it is written down once, here, and enforced.

It follows Graphiti's model so the graph can be read by Graphiti tooling: `Entity` nodes, `Episodic` nodes for
every source record ingested (with `MENTIONS` edges to what they mention), `Community` nodes for corporate groups,
and facts as `RELATES_TO` edges between entities. Every fact is bi-temporal:

- valid time: `valid_at` / `invalid_at`, when the fact was true in the world (days since 1970-01-01);
- transaction time: `created_at` / `expired_at`, when the graph learned it and when the graph stopped believing it.

A question "as of D" reads facts with valid_at <= D < invalid_at that the graph had not expired.
"""

from __future__ import annotations

from dataclasses import dataclass

ENTITY_KINDS = ("Company", "Person", "List", "Position", "Topic")
FACTS = {
    # name: (source kind, target kind, required properties)
    "OWNS": (("Company", "Person"), ("Company",), ("pct",)),
    "DIRECTOR_OF": (("Person",), ("Company",), ()),
    "LISTED_ON": (("Company", "Person"), ("List",), ()),
    "HOLDS_POSITION": (("Person",), ("Position",), ()),
    "ADVERSE_MEDIA": (("Company", "Person"), ("Topic",), ("topic",)),
}
TOPICS = ("bribery", "fraud", "sanctions_evasion", "money_laundering", "labour_violations", "environmental", "tax_evasion")
SOURCES = ("registry", "sanctions", "pep", "news", "web", "client")

ENTITY_PROPS = {
    "uuid": "STRING",
    "name": "STRING",
    "kind": "STRING",
    "country": "STRING",
    "regno": "STRING",
    "city": "STRING",
    "dob": "STRING",
    "aliases": "STRING",
    "supplier_ref": "STRING",
    "summary": "STRING",
}
EPISODE_PROPS = {
    "uuid": "STRING",
    "source": "STRING",
    "ref": "STRING",
    "valid_at": "INT64",
    "created_at": "INT64",
    "content": "STRING",
}
FACT_PROPS = {
    "uuid": "STRING",
    "name": "STRING",
    "fact": "STRING",
    "pct": "DOUBLE",
    "topic": "STRING",
    "valid_at": "INT64",
    "invalid_at": "INT64",
    "created_at": "INT64",
    "expired_at": "INT64",
    "source": "STRING",
    "episodes": "STRING",
    "confidence": "DOUBLE",
}
COMMUNITY_PROPS = {"uuid": "STRING", "name": "STRING", "summary": "STRING"}

LABELS = {"Entity": ENTITY_PROPS, "Episodic": EPISODE_PROPS, "Community": COMMUNITY_PROPS}
RELS = {
    "RELATES_TO": ("Entity", "Entity", FACT_PROPS),
    "MENTIONS": ("Episodic", "Entity", {}),
    "HAS_MEMBER": ("Community", "Entity", {}),
}


class SchemaError(ValueError):
    pass


@dataclass(frozen=True)
class Fact:
    name: str
    source_uuid: str
    target_uuid: str
    valid_at: int
    fact: str
    source: str
    confidence: float = 1.0
    pct: float | None = None
    topic: str | None = None
    invalid_at: int | None = None
    episodes: tuple[str, ...] = ()


def check_fact(f: Fact, kinds: dict[str, str]) -> None:
    """Rejects a write that breaks the schema: unknown fact, wrong endpoint kinds, missing properties, bad values."""
    if f.name not in FACTS:
        raise SchemaError(f"unknown fact {f.name}")
    src, dst, required = FACTS[f.name]
    if kinds.get(f.source_uuid) not in src or kinds.get(f.target_uuid) not in dst:
        raise SchemaError(f"{f.name} cannot connect {kinds.get(f.source_uuid)} to {kinds.get(f.target_uuid)}")
    if "pct" in required and (f.pct is None or not 0 < f.pct <= 100):
        raise SchemaError(f"OWNS needs a share in (0, 100], got {f.pct}")
    if "topic" in required and f.topic not in TOPICS:
        raise SchemaError(f"unknown topic {f.topic}")
    if f.source not in SOURCES:
        raise SchemaError(f"unknown source {f.source}")
    if f.invalid_at is not None and f.invalid_at < f.valid_at:
        raise SchemaError("invalid_at before valid_at")
    if not 0 <= f.confidence <= 1:
        raise SchemaError("confidence outside [0, 1]")


def kuzu_ddl() -> list[str]:
    out = []
    for label, props in LABELS.items():
        cols = ", ".join(f"{k} {t}" for k, t in props.items())
        out.append(f"CREATE NODE TABLE IF NOT EXISTS {label}({cols}, PRIMARY KEY(uuid))")
    for rel, (a, b, props) in RELS.items():
        cols = "".join(f", {k} {t}" for k, t in props.items())
        out.append(f"CREATE REL TABLE IF NOT EXISTS {rel}(FROM {a} TO {b}{cols})")
    return out


def neo4j_ddl() -> list[str]:
    out = [f"CREATE CONSTRAINT {label.lower()}_uuid IF NOT EXISTS FOR (n:{label}) REQUIRE n.uuid IS UNIQUE" for label in LABELS]
    out += [
        "CREATE INDEX entity_name IF NOT EXISTS FOR (n:Entity) ON (n.name)",
        "CREATE INDEX entity_supplier IF NOT EXISTS FOR (n:Entity) ON (n.supplier_ref)",
        "CREATE INDEX fact_name IF NOT EXISTS FOR ()-[r:RELATES_TO]-() ON (r.name)",
        "CREATE INDEX fact_valid IF NOT EXISTS FOR ()-[r:RELATES_TO]-() ON (r.valid_at, r.invalid_at)",
    ]
    return out


def describe() -> str:
    """The schema as a model sees it when it writes Cypher."""
    facts = "; ".join(f"{k}: ({'|'.join(a)})->({'|'.join(b)})" for k, (a, b, _) in FACTS.items())
    return (
        f"Nodes: (:Entity {{{', '.join(ENTITY_PROPS)}}}) with kind in {ENTITY_KINDS}; (:Episodic); (:Community). "
        f"Facts are (:Entity)-[:RELATES_TO {{name, {', '.join(k for k in FACT_PROPS if k != 'name')}}}]->(:Entity) "
        f"with name in: {facts}. Days are integers since 1970-01-01. A fact holds on day D when "
        "valid_at <= D AND (invalid_at IS NULL OR invalid_at > D) AND expired_at IS NULL."
    )
