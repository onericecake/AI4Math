# Mathematics Journal Matcher

This is a small working model for matching an unpublished mathematics article
to journals. It extracts a LaTeX manuscript, proposes the central result,
classifies the article with MSC2020, describes contribution and technical
level, and recommends three journals from a field-local catalog.

It does not check proof correctness, estimate acceptance probability, or claim
that a journal will accept a paper.

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
