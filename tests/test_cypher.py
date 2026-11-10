"""The query library runs unchanged on Kùzu here and on Neo4j in CI (NEO4J_URI set)."""

import os

import pytest

from trg.graph.ask import chain_cypher, check_cypher, template
from trg.graph.schema import Fact, SchemaError
from trg.graph.store import KuzuStore, open_store

STORES = ["kuzu"] + (["neo4j"] if os.environ.get("NEO4J_URI") else [])


@pytest.fixture(params=STORES)
def graph(request):
    g = KuzuStore() if request.param == "kuzu" else open_store("neo4j")
    ids = {
        "sup": g.add_entity("Company", "Nordwind Logistik GmbH", country="DE", supplier_ref="SUP-1"),
        "hold": g.add_entity("Company", "Kestrel Holdings Ltd", country="CY"),
        "anna": g.add_entity("Person", "Anna Schmidt"),
        "oleg": g.add_entity("Person", "Oleg Orlov"),
        "list": g.add_entity("List", "EU 269/2014"),
    }
    # the holding owned the supplier until day 200, then Anna; Oleg owns the holding and is listed from day 150
    f1 = g.add_fact(Fact("OWNS", ids["hold"], ids["sup"], 0, "x", "registry", pct=100.0), 0)
    g.invalidate(f1, 200)
    g.add_fact(Fact("OWNS", ids["anna"], ids["sup"], 200, "x", "registry", pct=100.0), 200)
    g.add_fact(Fact("OWNS", ids["oleg"], ids["hold"], 0, "x", "registry", pct=60.0), 0)
    g.add_fact(Fact("LISTED_ON", ids["oleg"], ids["list"], 150, "x", "sanctions"), 150)
    yield g, ids
    g.close()


def rows(g, intent, **p):
    cy, params, _ = template(intent, p)
    return g.run(cy, {k: v for k, v in params.items() if "$" + k in cy})


def test_owners_as_of(graph):
    g, ids = graph
    assert {r["uuid"] for r in rows(g, "owners", c=ids["sup"], d=100)} == {ids["hold"]}
    assert {r["uuid"] for r in rows(g, "owners", c=ids["sup"], d=250)} == {ids["anna"]}


def test_chain_and_exposure(graph):
    g, ids = graph
    up = g.run(chain_cypher(160) + "RETURN DISTINCT o.uuid AS uuid", {"c": ids["sup"]})
    assert {r["uuid"] for r in up} == {ids["hold"], ids["oleg"]}
    assert {r["uuid"] for r in rows(g, "sanctions_exposure", c=ids["sup"], d=160)} == {ids["oleg"]}
    assert rows(g, "sanctions_exposure", c=ids["sup"], d=100) == []  # not yet listed
    assert rows(g, "sanctions_exposure", c=ids["sup"], d=250) == []  # sold: no longer upstream
    assert rows(g, "last_ownership_change", c=ids["sup"], d=300, start=0)[0]["day"] == 200


def test_schema_and_query_checks(graph):
    g, ids = graph
    with pytest.raises(SchemaError):
        g.add_fact(Fact("OWNS", ids["sup"], ids["anna"], 0, "x", "registry", pct=50.0), 0)  # a company cannot own a person
    with pytest.raises(SchemaError):
        g.add_fact(Fact("OWNS", ids["anna"], ids["sup"], 0, "x", "registry", pct=150.0), 0)
    ok, _, _ = template("owners", {"c": "x", "d": 1})
    assert check_cypher(ok, "owners") is None
    assert check_cypher("MATCH (n) DETACH DELETE n", "owners") == "writes to the graph"
    assert check_cypher(ok.replace("'OWNS'", "'OWNED_BY'"), "owners").startswith("unknown relationship")
    assert check_cypher("MATCH (o)-[r:RELATES_TO]->(c) WHERE r.name = 'OWNS' RETURN o.uuid", "owners") == "no as-of filter"
    one_hop = template("ubo", {"c": "x", "d": 1})[0].replace("*1..4", "*1..1")
    assert check_cypher(one_hop, "ubo") == "does not follow the whole ownership chain"


def test_api_answers_with_cypher(graph):
    from fastapi.testclient import TestClient

    from trg.api import create_app
    from trg.graph.ask import Asker
    from trg.graph.design import Design

    g, ids = graph
    g.kinds.update({ids["sup"]: "Company", ids["hold"]: "Company"})
    asker = Asker(
        g,
        None,
        Design(),
        {"max_web_age_days": 365},
        {ids["sup"]: ["Nordwind Logistik GmbH"]},
        set(),
        0,
        registry_owners={ids["sup"], ids["hold"]},
    )
    c = TestClient(create_app(g, asker))
    r = c.post("/questions", json={"text": "Is Nordwind Logistik GmbH linked to any sanctioned party as of 1970-06-10?"}).json()
    assert r["intent"] == "sanctions_exposure" and [e["name"] for e in r["entities"]] == ["Oleg Orlov"] and r["cypher"]
    assert c.get(f"/entities/{ids['sup']}/facts", params={"as_of": "1970-12-31"}).json()[0]["other"] == "Anna Schmidt"
    assert c.get("/entities/nope/facts", params={"as_of": "1970-12-31"}).status_code == 404


def test_an_old_web_page_is_not_evidence_of_exposure(graph):
    from trg.graph.ask import Answer, Asker
    from trg.graph.design import Design

    g, ids = graph
    sup2 = g.add_entity("Company", "Trident Trading Co., Ltd.", country="CN")
    g.add_fact(Fact("OWNS", ids["oleg"], sup2, 100, "page", "web", 0.7, pct=100.0), 100)  # a page from day 100
    g.kinds.update({sup2: "Company", ids["oleg"]: "Person"})
    asker = Asker(g, None, Design(), {"max_web_age_days": 365}, {sup2: ["Trident Trading"]}, set(), 0)
    hits, complete = asker._exposure(Answer("x"), {"c": sup2, "d": 200}, "LISTED_ON")
    assert hits == {ids["oleg"]} and complete  # a recent page: the listed owner counts
    hits, complete = asker._exposure(Answer("x"), {"c": sup2, "d": 900}, "LISTED_ON")
    assert hits == set() and not complete  # two years later the page proves nothing: abstain
