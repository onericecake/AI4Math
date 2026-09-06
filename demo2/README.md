# Mathematics Journal Matcher

This is a small working model for matching an unpublished mathematics article
to journals. It extracts a LaTeX manuscript, proposes the central result,
classifies the article with MSC2020, describes contribution and technical
level, and recommends three journals from a field-local catalog.

It assumes mathematical correctness. Its heuristic scores describe subject and
audience fit; they do not establish novelty, editorial significance, or acceptance
probability. See [REVIEW.md](REVIEW.md) for the code review and proposed evaluation
design.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

With an API key, the matcher uses the OpenAI model configured by
`OPENAI_MODEL` (default `gpt-5.5`). The deterministic `--offline` mode is
available for local smoke tests and CI.

## Import the all-field catalog

The bundled fixtures contain the complete 6,603-entry MSC2020 hierarchy and
1,516 active mathematics journal records spanning all 63 broad MSC fields.
They also include recent MSC-tagged article metadata and journal-level field
statistics. The catalog is a testing snapshot, not a live editorial database.
Only 163 example articles across 115 journals are bundled, and only 61 have
abstracts. Most scope summaries are generated from MSC coverage. Broad registry
coverage therefore does not imply enough evidence to judge every journal's
editorial expectations.

```bash
journal-match catalog import-json data/catalog.example.json \
  --database /tmp/journal-catalog.sqlite
```

Multiple normalized source files can be merged in one import. Journals are
deduplicated by ISSN-L and articles by DOI when those identifiers are present:

```bash
journal-match catalog import-json path/to/zbmath.json path/to/openalex.json \
  --database /tmp/journal-catalog.sqlite
```

Keep the source notices in `data/MSC2020-LICENSE.txt` and
`data/JOURNAL-CATALOG-NOTICE.txt` with the fixtures.

## Analyze an article

The matcher accepts LaTeX source (`.tex` or `.latex`), including local
`\\input`/`\\include` files. It retains section and proof evidence and ranks
journals using subject, audience, technical-level, and evidence signals. It
intentionally does not require a full TeX compiler.

```bash
journal-match analyze examples/manuscript.tex \
  --msc data/msc2020.json \
  --catalog /tmp/journal-catalog.sqlite \
  --offline --yes \
  --output-dir results
```

Without `--yes`, the tool asks the author to confirm the proposed central
result and MSC classification. For substantive model analysis, omit
`--offline` and set `OPENAI_API_KEY`.

## Reproduce the linked-paper smoke test

Download the arXiv source archive corresponding to
[arXiv:2608.18255](https://arxiv.org/abs/2608.18255), then run:

```bash
journal-match catalog import-json data/catalog.example.json \
  --database /tmp/journal-catalog.sqlite
journal-match analyze /path/to/ruling_polynomial_26.tex \
  --msc data/msc2020.json \
  --catalog /tmp/journal-catalog.sqlite \
  --offline --yes \
  --output-dir results/arxiv-2608.18255
```

The included smoke-test output is in
`examples/arxiv-2608.18255.report.md` and
`examples/arxiv-2608.18255.report.json`.

## Tests

```bash
PYTHONPATH=src python -m pytest -q
```

Run these commands from `demo2`. The pytest configuration explicitly selects
this directory's `src`, avoiding the separate package copy in the parent repo.

## Retrieval and evidence safeguards

- Broad MSC matches remain broad even when an ancestor appears explicitly in
  the query. The full matching pool is scored before selecting up to 24 journals
  for model profiling and up to 12 for the final explanation prompt.
- Each local article is counted once per MSC prefix. Imported aggregate
  statistics are preserved when additional small article samples are merged.
  Statistics in legacy databases have unknown provenance and are preserved as
  imported; use a fresh import to reconstruct local derived statistics.
- Journal profile caches depend on model identity, prompt, and supplied evidence.
  Offline profiles are not reused as live model profiles.
- Recommendations can cite only articles supplied for that journal. Reports
  include their titles and source links, the weighted score components, and the
  final candidate shortlist in JSON (`ranked_candidates`).
- A recommendation without valid article citations is labeled `insufficient
  information`. Weak field-profile evidence cannot justify `strong match` or
  `closely aligned`. These are evidence checks, not calibrated quality judgments.
- MSC codes must exist in the loaded taxonomy; author corrections update broad
  fields so old classifications do not continue contributing candidates.

The ranking weights remain hand-selected. The offline model has deliberately
limited keyword coverage and fixed demonstration profiles; use it only to test
the workflow. It cannot demonstrate editorial matching accuracy.

## Evaluate saved rankings

Create a JSON object with a `cases` list. Each case needs a unique `paper_id`,
`relevant_journal_ids` supplied independently by reviewers, and ordered
`ranked_journal_ids`. Optional `candidate_journal_ids` measure retrieval recall.
Allow multiple relevant journals for one manuscript. An empty ranking is an
abstention and counts as a miss for a paper with suitable labeled venues.

```bash
PYTHONPATH=src python -m journal_matcher evaluate \
  examples/evaluation.example.json --k 3 --output results/metrics.json
```

This computes top-k hit rate, recall, MRR, binary nDCG, recommendation coverage,
and candidate recall where supplied. The example is entirely synthetic and
validates metric calculations only. The evaluator scores saved rankings; it does
not run the matcher, create relevance labels, or enforce separation between
training and evaluation data. When scoring final recommendations, omit entries
labeled `insufficient information` from `ranked_journal_ids` and report that
filtering rule with the results. The report's `ranked_candidates` field can supply
the final shortlist IDs for candidate recall; it is not the full retrieval pool.
