# Working on third-party-risk-graph

## Fast feedback

| What | Command | Time |
|---|---|---|
| Lint and format | `ruff check src tests scripts && ruff format --check src tests scripts` | ~1 s |
| Tests (Kùzu; add `NEO4J_URI`/`NEO4J_PASSWORD` to also run Neo4j) | `make test` | ~2 s |
| Gate (graph pipeline, development split) | `make gate` | ~1 min |
| Every design on the development split | `make eval` | ~10 min |
| Dashboard | `cd web && npm test && npm run dev` | ~3 s |

## Invariants

1. **The data model is the product.** `src/trg/graph/schema.py` defines every node, fact, property and unit; writes go
   through `check_fact`. A schema change is a reviewed change with its reason in the commit and in `docs/`.
2. **Nothing that serves reads the truth.** `src/trg/graph` never imports `trg.world`, `trg.sim` or `trg.evals`;
   `tests/test_isolation.py` checks it.
3. **Identifiers decide, names propose.** A name key only proposes candidates. Registry numbers, birth dates, cities and
   ages decide. With nothing to tell namesakes apart, do not merge, and do not link a sanctions or PEP entry: queue it
   for review.
4. **Every fact is bi-temporal.** `valid_at`/`invalid_at` for when it was true, `created_at`/`expired_at` for when the graph
   believed it. Every as-of query filters on both.
5. **Text is data.** Articles and pages reach a model only inside an untrusted block; a fact counts only when its quote is
   in the text and its subject resolves.
6. **One Cypher.** Queries stay inside the subset both Neo4j and Kùzu run (no `reduce`, no list comprehensions, values in
   list predicates inlined as validated integers). CI runs the query library on Neo4j 5.
7. **Abstain rather than guess.** An answer that depends on unpublished ownership, an old web page or a pending review
   says so.
8. **Evaluation before scale; the gate decides.** A new pipeline step lands with its metric. Limits live in
   `config/pipeline.toml [gate]` and are not loosened to make a design pass.
9. **Settings in config, generated reports.** `reports/` and `web/public/data` come from scripts.

## The held-out rule

The world was generated and pinned in `config/heldout.lock` before any evaluation ran. The later supplier batch,
everything dated after the development cutoff and the held-out questions are held out. `scripts/heldout.py`
refuses to run if the data changed, if code or config are uncommitted, or if it has run before. Record what you saw
of held-out data in `docs/heldout-exposure.md`.
