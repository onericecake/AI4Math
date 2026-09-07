# Mathematics Journal Matcher

Match a mathematics manuscript to potential journals using MSC2020 subject
classification, article evidence and journal profiles. This Python research demo
provides an interactive manuscript analysis workflow and a separate trainable
title/abstract model.

The matcher assumes mathematical correctness. Its scores describe subject and
audience fit; they do not establish novelty, editorial significance or acceptance
probability. Offline examples demonstrate the software, not recommendation accuracy.

## Choose a workflow

| Goal | Command | Requirements |
| --- | --- | --- |
| Try the complete workflow locally | `analyze --offline --yes` | Bundled data; no API key |
| Analyze a manuscript with model explanations | `analyze` | Catalog, MSC taxonomy and `OPENAI_API_KEY` |
| Learn publication-venue affinity | `train-venues`, then `recommend-venues` | Collected abstracts and the `training` extra |
| Measure retrieval or score saved rankings | `benchmark` or `evaluate` | Manuscript inputs and separate labels |

`analyze` uses hybrid MSC and BM25 retrieval by default. The trained venue model
is opt-in and covers the journals in its training corpus. It does not replace
the default matcher. See [usage and options](docs/usage.md).

## Quick start

Use Python 3.9 or newer. From the repository root, enter `demo2` before installing
or running commands; this directory is its own Python project.

```sh
cd demo2
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'

journal-match catalog import-json data/catalog.example.json \
  --database results/catalog.sqlite
journal-match analyze examples/manuscript.tex \
  --msc data/msc2020.json --catalog results/catalog.sqlite \
  --offline --yes --output-dir results/smoke
```

Open `results/smoke/report.md` for the readable report or
`results/smoke/report.json` for classifications, recommendations, evidence and
the final candidate shortlist. A [saved example](examples/README.md) is included.

For model analysis, configure `OPENAI_API_KEY` in your environment, omit
`--offline` and supply your manuscript path. Without `--yes`, the CLI asks you
to confirm the central result and MSC classification. `--model` overrides
`OPENAI_MODEL`; the code's fallback model is `gpt-5.5`.

## Data and measured results

The bundled registry contains **1,516 journals**, the **6,603-entry MSC2020
taxonomy** and **163 example articles**, of which **61 have abstracts**. It spans
all 63 broad MSC fields, but most journal scope summaries are registry-derived.
Registry coverage is much broader than the available article evidence.

Additional datasets and experiments are explicitly separated:

| Resource | Status and interpretation |
| --- | --- |
| [Public evidence](data/public-evidence-2026-09-07/README.md) | 60 importable publisher abstracts and six scope profiles; measured gains and regressions |
| [Venue training](docs/training.md) | Historical collection of 10,973 articles across 50 journals; manifests included, corpus and weights generated locally |
| [Venue-model benchmark](benchmarks/broad-training-2026-09-07/REPORT.md) | 595/991 historical venues in the top three (60.0%), versus 46.1% for BM25, within a fixed 50-journal set |
| [Focused retrieval experiment](benchmarks/focused-2026-09-07/REPORT.md) | Improved the development pilot but regressed on fixture validation; remains experimental |

These experiments use different candidate sets and protocols, so their scores
are not directly comparable. Start with the [benchmark index](benchmarks/README.md)
for the datasets, reproduction commands and limitations. Source attribution and
license notices are documented in the [data inventory](data/README.md).

## Project map

```text
demo2/
├── README.md             # Start here
├── pyproject.toml        # Package, dependencies and CLI entry point
├── docs/                 # Usage, catalogs, evaluation, training, development
├── src/journal_matcher/  # Implementation
├── tests/                # Offline regression tests
├── data/                 # Canonical fixtures, evidence and collection manifests
├── examples/             # Small inputs and a reproducible offline report
├── benchmarks/           # Frozen experiment inputs, reports and audit artifacts
└── scripts/              # Collection and historical benchmark helpers
```

Generated databases, caches, models and new reports belong in the ignored
`results/` directory. Keep published benchmark snapshots separate from new runs.

## Documentation

- [Use the matcher](docs/usage.md): inputs, configuration, retrieval and reports.
- [Prepare catalogs](docs/catalog.md): imports, collection, identity and provenance.
- [Evaluate and train an expert reranker](docs/evaluation.md): labels, splits and metrics.
- [Train a publication-venue model](docs/training.md): collect, train and recommend.
- [Develop the project](docs/development.md): module map, tests and known limitations.
- [Run helper scripts](scripts/README.md): current entry points and legacy reproduction.

## Tests

From `demo2`, after installing the `dev` extra:

```sh
python -m pytest
```

The suite uses local fixtures and fake model/HTTP adapters. Install
`'.[dev,training]'` to include the optional scikit-learn training tests.
Pytest explicitly selects `demo2/src` so another installed copy cannot shadow it.
