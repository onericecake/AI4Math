# Learning from public publication records

[Home](../README.md) · [Collection manifest](../data/broad-training-2026-09-07/README.md) · [Measured results](../benchmarks/broad-training-2026-09-07/REPORT.md)

The `train-venues` and `recommend-venues` commands provide a trained, offline
title/abstract matcher. The September 2026 experiment collected **10,973 articles
from 50 journals** using OpenAlex. Training and prediction run locally without
reviewer data or an API key. The original `analyze` workflow remains available
and its defaults are unchanged.

The model learns **observed publication venues**. Another journal may also have
been suitable. Scores do not estimate acceptance probability, importance, novelty
or editorial selectivity, even when the mathematics is correct. The model's
candidate list contains 50 journals, not all 1,516 journals in the example registry.

## Collect and train

**The training corpus and model weights are not included.** The repository ships
collection manifests and frozen benchmark results. Run collection and training
below to build your own model; recollecting a live service can change the data
and will not guarantee the published metrics.

Run from `demo2`, with this package installed in your Python environment:

```sh
python -m pip install -e '.[training,dev]'
journal-match catalog harvest-openalex data/broad-training-2026-09-07/collection-plan.json --output-dir results/venue-training/collection
journal-match train-venues results/venue-training/collection/catalog.json --exclude data/broad-training-2026-09-07/previous-benchmark-exclusions.json --output-dir results/venue-training/experiment
```

The collector is resumable and caches source pages. A changed collection plan
requires a new output directory. It uses exact journal ISSNs, publication-year
filters and cursor pagination. Articles need a DOI and at least 35 abstract words;
explicit corrections, editorials and retractions are filtered. Provider article
types are not individual peer-review verification. Selection takes the earliest
eligible dates within each journal/year, without citation-based sampling.
Missing abstracts and smaller publication volumes cause reported quota shortfalls.
See the [OpenAlex API](https://help.openalex.org/api/),
[filters](https://help.openalex.org/api/filtering/) and
[pagination documentation](https://help.openalex.org/api/paging/).

The fixed plan spans generalist mathematics, algebra/number theory, combinatorics,
geometry/topology, analysis/PDE, probability/statistics, numerical/applied
mathematics, optimization and mathematical physics. These are collection strata,
not manuscript suitability labels. Per-paper OpenAlex topic subfields are saved
for diagnostic breakdowns; they are never converted to invented MSC codes.

After deduplication and previous-benchmark exclusions, this run has **8,967 training
articles (2020–2023), 979 validation articles (2024) and 991 test articles (2025)**.
The requested 10,000 training point uses all 8,967 available training records;
it does not borrow papers from either holdout.

Training uses nested journal/year-balanced samples of 1,000, 5,000 and up to 10,000
articles. A TF-IDF vocabulary and IDF are fitted on each training sample only.
A class-balanced linear classifier and journal text centroids are combined by
reciprocal ranks. Regularization and the combination weight are selected using
validation macro-journal Hit@3, then the model choice is locked before test scoring.
All three predeclared learning-curve models are evaluated once on the same test.
BM25 maximum-article scores and centroid similarity provide equal-corpus baselines.

Only title and abstract enter the text model. Source IDs, author identities,
citation counts, actual journal labels, topic labels and MSC codes are excluded.
Explicit candidate journal names, links, DOI strings and obvious publisher
boilerplate are removed from both training and query text.

## Recommend three journals

```sh
journal-match recommend-venues examples/manuscript.tex --venue-model results/venue-training/experiment/model --output results/venue-training/recommendations.json
```

A JSON input with `title` and `abstract` also works. No LLM call is made.
The result gives the three journal names, identifiers and official links, plus
the model's coverage and interpretation. An input with no vocabulary overlap
produces an error instead of arbitrary recommendations. Word overlap alone
does not establish that an unfamiliar subject is covered, so read the candidate
list in `model/model.json` when working outside the sampled mathematical fields.

Models use checksummed JSON and numeric NPZ arrays, loaded with
`allow_pickle=False`. Install the `training` extra to load them. The saved model
does not contain training abstracts. Raw metadata caches and the frozen local
snapshot are generated under `results/venue-training/` by the commands above.
Abstract rights remain with their original rights holders, distinct from
OpenAlex's metadata license.

The experiment also writes `training-catalog.json`, containing only the selected
training references, for optional import into the existing hybrid matcher:

```sh
journal-match catalog import-json data/catalog.example.json results/venue-training/experiment/training-catalog.json --database results/venue-training/hybrid.sqlite
```

This is a separate experiment: trained-model results do not establish an
improvement for the full-registry hybrid or its later LLM explanation stage.
For evaluation, remove all test papers from **every** imported catalog.

## Audit and interpretation

`frozen/manifest.json` records source/split hashes and exclusion counts;
`protocol.json` records the experiment choices before training;
`selection.json` locks the validation-selected model; `summary.json` reports
Hit@1, Hit@3, MRR, macro-journal Hit@3, uncertainty and breakdowns by journal,
collection stratum, scope group and machine-assigned topic subfield.
`test-predictions-*.json` lists each paper's three recommendations alongside its
actual journal. Rerunning an unchanged completed experiment returns its saved
results; changed inputs or protocols require a new directory.

DOI, title, preprint aliases when present, OpenAlex work identities and identical
blinded abstracts connect duplicate records. One representative of each group
goes to the latest split required by its versions. Conflicting venue labels are
quarantined. These checks do not exhaustively detect near-duplicate papers with
different identities and rewritten abstracts, and the split is not author-disjoint.

This is a publication-year holdout using metadata observed in 2026 and published
abstracts. It is not a reconstruction of what was available at submission time.
Balanced quotas reduce volume imbalance but cannot remove missing-abstract,
publisher, language or convenience-sampling biases. Descriptive confidence
intervals do not establish performance across all mathematical fields.

Results are recorded in the [benchmark report](../benchmarks/broad-training-2026-09-07/REPORT.md).
