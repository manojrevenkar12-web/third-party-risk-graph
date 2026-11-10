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
- **The held-out run (commit 5943bd9, `reports/heldout.json`, never rewritten).** The graph pipeline answered 79.6% of
  260 held-out questions right, 10.0% wrong and abstained on 10.4%, so it failed the gate. To read the wrong answers,
  the same commit was run once more on the held-out questions with the rows saved (deterministic; same numbers). Of
  the 26 wrong answers, 25 are "which of our suppliers were exposed" list questions, all wrong because of two
  suppliers; the 26th is an ownership-change date. Every single-supplier owner, beneficial-owner, director,
  sanctions and PEP question was right or abstained. The causes:
  1. **An old web page counted as current ownership.** A supplier in a registry that publishes no shareholders
     had one archived page naming a former owner, a sanctioned company. The chain flagged the page as stale but
     still followed it, so the supplier was reported exposed. Now a page or article older than a year is not
     followed at all, and the answer abstains (`test_an_old_web_page_is_not_evidence_of_exposure`).
  2. **A director known only by an initial.** A Dutch filing writes "W. Zhou" with a birth date; the sanctions list
     names "ZHOU, Wei" with the same birth date. Initials were matched from the short form to the long one, not the
     other way, so the listing (dated after the development cutoff) never reached the director
     (`test_someone_known_by_an_initial_is_found_by_full_name`).
  3. **A shareholder split by a later filing.** A Swiss filing gives no birth dates; after the person's entity
     picked one up elsewhere, the next filing's identical entry became a new person and looked like a change of
     ownership. Entries written identically in a company's consecutive filings are now the same person.
  These fixes were made and tested on development data afterwards and have not been run on held-out data.
