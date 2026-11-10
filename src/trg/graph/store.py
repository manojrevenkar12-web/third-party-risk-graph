"""Graph stores. Neo4j in production; embedded Kùzu for local runs and evaluations. Both run the same Cypher: every
query in this repository stays inside the subset both engines execute identically, and CI runs the query library
against a Neo4j 5 service to prove it."""

from __future__ import annotations

import json
import os
import tempfile
import uuid as uuidlib

from .schema import FACT_PROPS, Fact, check_fact, kuzu_ddl, neo4j_ddl


class GraphStore:
    engine = "abstract"

    def __init__(self):
        self.kinds: dict[str, str] = {}
        self.writes = 0

    def run(self, query: str, params: dict | None = None) -> list[dict]:  # pragma: no cover - interface
        raise NotImplementedError

    # writes ------------------------------------------------------------------------------------------------------
    def add_entity(self, kind: str, name: str, **props) -> str:
        uid = props.pop("uuid", None) or f"ent-{uuidlib.uuid4().hex[:12]}"
        row = {"uuid": uid, "name": name, "kind": kind, "country": None, "regno": None, "city": None, "dob": None,
               "aliases": "[]", "supplier_ref": None, "summary": None} | props
        self.run("CREATE (:Entity {uuid: $uuid, name: $name, kind: $kind, country: $country, regno: $regno, city: $city, "
                 "dob: $dob, aliases: $aliases, supplier_ref: $supplier_ref, summary: $summary})", row)
        self.kinds[uid] = kind
        self.writes += 1
        return uid

    def set_entity(self, uid: str, **props) -> None:
        for k, v in props.items():
            self.run(f"MATCH (n:Entity {{uuid: $u}}) SET n.{k} = $v", {"u": uid, "v": v})
        self.writes += 1

    def add_episode(self, source: str, ref: str, valid_at: int, created_at: int, content: str, mentions=()) -> str:
        uid = f"ep-{uuidlib.uuid4().hex[:12]}"
        self.run("CREATE (:Episodic {uuid: $uuid, source: $source, ref: $ref, valid_at: $valid_at, "
                 "created_at: $created_at, content: $content})",
                 {"uuid": uid, "source": source, "ref": ref, "valid_at": valid_at, "created_at": created_at,
                  "content": content[:2000]})
        for m in set(mentions):
            self.run("MATCH (e:Episodic {uuid: $e}), (n:Entity {uuid: $n}) CREATE (e)-[:MENTIONS]->(n)", {"e": uid, "n": m})
        self.writes += 1
        return uid

    def add_fact(self, f: Fact, created_at: int) -> str:
        check_fact(f, self.kinds)
        uid = f"fact-{uuidlib.uuid4().hex[:12]}"
        props = {k: None for k in FACT_PROPS} | {
            "uuid": uid, "name": f.name, "fact": f.fact, "pct": f.pct, "topic": f.topic, "valid_at": f.valid_at,
            "invalid_at": f.invalid_at, "created_at": created_at, "expired_at": None, "source": f.source,
            "episodes": json.dumps(list(f.episodes)), "confidence": f.confidence}
        sets = ", ".join(f"{k}: ${k}" for k in props)
        self.run(f"MATCH (a:Entity {{uuid: $a}}), (b:Entity {{uuid: $b}}) CREATE (a)-[:RELATES_TO {{{sets}}}]->(b)",
                 props | {"a": f.source_uuid, "b": f.target_uuid})
        self.writes += 1
        return uid

    def invalidate(self, fact_uuid: str, invalid_at: int, expired_at: int | None = None) -> None:
        """The fact stopped being true at `invalid_at` (valid time); optionally the graph stops believing it."""
        self.run("MATCH ()-[r:RELATES_TO {uuid: $u}]->() SET r.invalid_at = $i", {"u": fact_uuid, "i": invalid_at})
        if expired_at is not None:
            self.run("MATCH ()-[r:RELATES_TO {uuid: $u}]->() SET r.expired_at = $x", {"u": fact_uuid, "x": expired_at})
        self.writes += 1

    def add_community(self, name: str, members: list[str]) -> str:
        uid = f"com-{uuidlib.uuid4().hex[:12]}"
        self.run("CREATE (:Community {uuid: $u, name: $n, summary: $s})", {"u": uid, "n": name, "s": f"{len(members)} members"})
        for m in members:
            self.run("MATCH (c:Community {uuid: $c}), (n:Entity {uuid: $n}) CREATE (c)-[:HAS_MEMBER]->(n)", {"c": uid, "n": m})
        return uid


class KuzuStore(GraphStore):
    engine = "kuzu"

    def __init__(self, path: str | None = None):
        super().__init__()
        import kuzu

        self._dir = None
        if path is None:
            self._dir = tempfile.mkdtemp(prefix="trg-")
            path = os.path.join(self._dir, "graph")
        self.db = kuzu.Database(path)
        self.conn = kuzu.Connection(self.db)
        for q in kuzu_ddl():
            self.conn.execute(q)

    def run(self, query: str, params: dict | None = None) -> list[dict]:
        res = self.conn.execute(query, params or {})
        cols = res.get_column_names()
        out = []
        while res.has_next():
            out.append(dict(zip(cols, res.get_next(), strict=True)))
        return out

    def close(self) -> None:
        import shutil

        self.conn.close()
        self.db.close()
        if self._dir:
            shutil.rmtree(self._dir, ignore_errors=True)


class Neo4jStore(GraphStore):  # exercised in CI against a Neo4j 5 service container
    engine = "neo4j"

    def __init__(self, uri: str, user: str, password: str, database: str = "neo4j"):
        super().__init__()
        from neo4j import GraphDatabase

        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.database = database
        self.run("MATCH (n) DETACH DELETE n")
        for q in neo4j_ddl():
            self.run(q)

    def run(self, query: str, params: dict | None = None) -> list[dict]:
        records, _, keys = self.driver.execute_query(query, params or {}, database_=self.database)
        return [dict(zip(keys, r.values(), strict=True)) for r in records]

    def close(self) -> None:
        self.driver.close()


def open_store(kind: str = "kuzu") -> GraphStore:
    if kind == "neo4j":
        return Neo4jStore(os.environ["NEO4J_URI"], os.environ.get("NEO4J_USER", "neo4j"), os.environ["NEO4J_PASSWORD"])
    return KuzuStore()
