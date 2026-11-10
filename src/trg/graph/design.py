"""The pipeline's switches: the full pipeline has all of them on; each ablation turns one off; the naive pipeline is
what a quick prototype does."""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Design:
    name: str = "graph-pipeline"
    phonetic: bool = True  # transliteration-aware name keys
    identifiers: bool = True  # registry numbers, birth dates, cities and ages decide; a name alone does not
    temporal: bool = True  # facts keep valid_at / invalid_at; off: the graph keeps only the latest state
    context_check: bool = True  # an article or page is attached to an entity only if its city or age agrees
    topics: str = "cascade"  # small | llm | cascade (small model, model when it is unsure)
    enrichment: str = "gated"  # gated | first_result | off
    cypher: str = "templates"  # templates | llm_validated | llm_raw
    tier: str = "small"

    def but(self, name: str, **kw) -> Design:
        return replace(self, name=name, **kw)


def naive() -> Design:
    return Design(
        name="naive-prototype",
        phonetic=False,
        identifiers=False,
        temporal=False,
        context_check=False,
        topics="llm",
        enrichment="first_result",
        cypher="llm_raw",
        tier="large",
    )


def designs() -> list[Design]:
    d = Design()
    return [
        d,
        naive(),
        d.but("no-transliteration", phonetic=False),
        d.but("names-only-resolution", identifiers=False),
        d.but("latest-state-graph", temporal=False),
        d.but("no-context-check", context_check=False),
        d.but("enrichment-first-result", enrichment="first_result"),
        d.but("no-enrichment", enrichment="off"),
        d.but("llm-cypher-validated", cypher="llm_validated"),
        d.but("llm-cypher-raw", cypher="llm_raw"),
        d.but("topics-small-model", topics="small"),
        d.but("topics-llm", topics="llm"),
    ]
