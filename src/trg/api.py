"""The AI layer as its own service, for the .NET backend: HTTP contracts in, answers with their Cypher and facts out.

`POST /questions` answers an analyst's question; `GET /entities/{uuid}/facts` returns an entity's facts as of a day.
The service holds no state of its own besides the graph, so it deploys and tests independently of the backend.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .graph.ask import Asker, day


class Question(BaseModel):
    text: str = Field(min_length=5, max_length=500)


class AnswerOut(BaseModel):
    intent: str | None
    as_of: str | None
    complete: bool
    note: str
    entities: list[dict]
    topics: list[str]
    day: str | None
    cypher: list[str]
    route: str


def create_app(store, asker: Asker) -> FastAPI:
    app = FastAPI(title="third-party-risk-graph")

    def names(uids):
        if not uids:
            return []
        rows = store.run(
            "MATCH (n:Entity) WHERE n.uuid IN $ids RETURN n.uuid AS uuid, n.name AS name, n.kind AS kind",
            {"ids": list(uids)},
        )
        return sorted(rows, key=lambda r: r["name"])

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "engine": store.engine, "entities": store.run("MATCH (n:Entity) RETURN count(n) AS n")[0]["n"]}

    @app.post("/questions", response_model=AnswerOut)
    def ask(q: Question) -> AnswerOut:
        a = asker.ask(q.text)
        return AnswerOut(
            intent=a.intent,
            as_of=a.as_of,
            complete=a.complete,
            note=a.note,
            entities=names(a.uuids),
            topics=a.topics,
            day=a.day,
            cypher=a.cypher[:5],
            route=a.route,
        )

    @app.get("/entities/{uid}/facts")
    def facts(uid: str, as_of: str) -> list[dict]:
        d = day(as_of)
        rows = store.run(
            "MATCH (a:Entity {uuid: $u})-[r:RELATES_TO]-(b:Entity) WHERE r.expired_at IS NULL AND "
            "r.valid_at <= $d AND (r.invalid_at IS NULL OR r.invalid_at > $d) RETURN r.name AS fact, "
            "b.name AS other, r.pct AS pct, r.topic AS topic, r.source AS source, r.valid_at AS since, "
            "r.confidence AS confidence",
            {"u": uid, "d": d},
        )
        if not rows and not store.run("MATCH (n:Entity {uuid: $u}) RETURN n.uuid AS u", {"u": uid}):
            raise HTTPException(404, "no such entity")
        return rows

    return app
