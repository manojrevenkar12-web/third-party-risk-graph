# Skills for this codebase

Repeatable tasks, written so a person or a coding agent can do them the same way each time.

## Add a fact type
1. Add it to `FACTS` in `src/trg/graph/schema.py` with its endpoint kinds and required properties; explain why in the
   commit.
2. Write it only through `GraphStore.add_fact`, with `valid_at` from the source and `invalid_at` when the source says
   it ended.
3. Add the as-of template in `src/trg/graph/ask.py` and a case to `tests/test_cypher.py` (runs on Kùzu and Neo4j).
4. Add its metric to `src/trg/evals/run.py` before the pipeline writes it at scale.

## Add a source
1. A client in `src/trg/world/services.py` (simulation) or a real client behind the same method names.
2. Every record becomes an `Episodic` node; every fact it supports lists the episode.
3. Mentions resolve through `PersonIndex` / `CompanyIndex`; never write a fact on a name match alone.

## Add a question type
1. A rule in `INTENT_RULES` (English and German), a template, and the answer's completeness rule (when to abstain).
2. Questions and true answers in the world generator; the scorer in `evals/run.py`.

## Change a threshold
Only in `config/pipeline.toml`, with the development metric before and after in the commit message.
