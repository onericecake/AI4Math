# Development

[Home](../README.md) · [Usage](usage.md) · [Benchmark inventory](../benchmarks/README.md)

## Environment and checks

Work from `demo2`. Install `'.[dev]'` into an isolated environment; add `training`
for the optional venue-model tests. The `semantic` extra is only needed for real
Sentence Transformers encoders.

```sh
python -m pip install -e '.[dev,training]'
python -m pytest
```

Tests use local fixtures and fake model/HTTP adapters. They cover extraction,
catalog merges, retrieval, citation safeguards, benchmark target exclusion,
chronological splits, resumable collection and model persistence. Passing them
does not establish editorial accuracy. Run the [README smoke test](../README.md#quick-start)
when changing the CLI or report output.

## Module map

All implementation modules live in `src/journal_matcher/`.

| Modules | Responsibility |
| --- | --- |
| `cli.py`, `__main__.py` | Command parsing and workflow entry points |
| `latex_extract.py`, `msc.py`, `schemas.py` | Manuscript extraction, taxonomy and data records |
| `pipeline.py`, `prompts.py`, `llm.py`, `report.py` | Analysis, model calls, evidence validation and reports |
| `catalog.py`, `corpus.py` | SQLite storage, provenance, work identities and temporal splitting |
| `retrieval.py`, `rerank.py` | BM25/optional embeddings, journal ranking and expert-trained weights |
| `harvest.py`, `openalex_harvest.py` | Collection plans, normalized metadata and resumable provider requests |
| `evaluation.py`, `experiments.py` | Ranking metrics and manuscript benchmark runs |
| `venue_learning.py`, `venue_experiment.py` | Local text models and frozen publication-venue experiments |

Keep the research helpers in [scripts](../scripts/README.md) separate from the
package entry points. Tests of the legacy harness remain useful because it
deliberately reproduces older ranking cutoffs.

## Data and artifact conventions

- Use `data/catalog.example.json` and `data/msc2020.json` as the canonical bundled
  fixtures. The former `journal_catalog.sample.json` and `msc2020.sample.json`
  names duplicated those complete files and have been removed.
- Write generated catalogs, caches, models and new runs to `results/`.
- Keep checked-in benchmark inputs, metrics, predictions and provenance together.
  Identical audit files in separate runs intentionally keep each run self-contained.
- Preserve source/license notices and per-article attribution with redistributed data.
- Update guides and [example output](../examples/README.md) when interfaces change.
  Check relative Markdown links after moving documents.

The old `REVIEW.md` mixed completed fixes with proposed work and has been retired.
Current behavior is documented in these guides; implementation history remains in Git.
The old external-paper report was replaced by a reproducible report for the bundled
manuscript. Historical benchmark scores remain in their dated reports.

## Known limitations and remaining work

The default catalog has sparse readable article evidence and mostly generated
scope descriptions. Imported aggregate counts have no complete document lineage;
exploratory benchmarks cannot guarantee temporal isolation. Strict temporal
filtering requires verified availability dates that many bundled records lack.

The TeX extractor handles only part of the language and skips includes outside
the main file's directory. Long manuscript/model inputs can be truncated. No
proof checker, novelty assessment or calibrated editorial-quality model is present.

Useful next work is richer dated manuscript and journal evidence, independent
expert judgments of multiple reasonable venues, and a fresh held-out evaluation
before selecting new ranking defaults. Current publication-venue results are a
limited proxy; they do not measure the full explanation workflow or acceptance.
