# Held-out exposure

What anyone working on this repository has seen of the held-out data (the later supplier batch, everything dated
after 2025-12-31, the held-out questions), and when.

- **World regenerations before any evaluation.** The world was regenerated and re-pinned four times while the pipeline
  was being written, each before any evaluation had run: ages in articles as of the publication date; web pages for
  holdings in registries that publish officers but not shareholders; registered cities for company shareholders in
  filings; Turkish dotless i in folded names. No held-out answer was looked at.
- **Topic comparison, once, during development.** `trg.evals.topics` was first written to test on articles published
  after the cutoff and was run once that way (the classifier got all 37 right, the small model tier 34). It was then
  changed to five-fold cross-validation on development articles. No pipeline setting changed because of it.
