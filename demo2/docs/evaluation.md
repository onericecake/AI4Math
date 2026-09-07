# Evaluation and expert reranking

[Home](../README.md) · [Benchmark results](../benchmarks/README.md) · [Catalog preparation](catalog.md)

Run these commands from `demo2` after installation. The [venue training guide](training.md)
covers the separate title/abstract model trained on observed publication venues.

## Benchmark manuscript inputs


Use a dataset directory with the `cases.json`, `labels.json` and `supplied-msc.json`
formats described in [the benchmark inventory](../benchmarks/README.md).

```sh
journal-match benchmark --dataset path/to/dataset --catalog-json results/catalog.json --output-dir results/hybrid-benchmark
journal-match benchmark --dataset path/to/dataset --catalog-json results/catalog.json --retrieval legacy --output-dir results/legacy-benchmark
journal-match benchmark --dataset path/to/dataset --catalog-json results/catalog.json --without-title --output-dir results/no-title-benchmark
journal-match benchmark --dataset path/to/dataset --catalog-json results/catalog.json --strict-temporal --cutoff 2023-12-31 --output-dir results/temporal-benchmark
```

The default is a supplied-MSC retrieval diagnostic. It reports Hit/MRR/nDCG@3,
Recall@24/50/100, coverage, corpus exclusions and a descriptive manuscript bootstrap.
Each benchmark removes every target and linked version from the reference articles
before computing derived statistics. The ordinary exploratory mode retains imported
aggregates and does not claim temporal isolation. Strict mode requires dated article
content, metadata and journal registry records, removes all imported aggregates and
undated/future scope evidence. Without `--cutoff`, every case needs `submission_date`.
The old bundled corpus lacks these dates and will largely disappear in strict mode;
that is an explicit data gap, not a reason to silently use current information.

Run the actual model stages with `--mode openai --model YOUR_MODEL_ID`; a local API
key is required. `--mode heuristic` tests the same interfaces with the smoke-test
backend. These routes save model prompts/responses and both raw and supported-only
recommendation metrics. Supported-only scoring retains `strong match` and
`plausible match`; abstentions stay in the denominator. API errors stop the run
instead of quietly dropping failed cases.

For full manuscripts, add a `manuscript_path` relative to the dataset directory and
`blinded: true` to every case, then use `--full-text`. Remove publication/author
identifiers from the files first; the declaration records that preprocessing but
cannot verify it. The pipeline extracts sections/proofs/theorems as in normal
analysis. Optional `central_result_ids` are recorded as supplied; otherwise central
result selection is automatic and is not represented as author confirmation.

Each run produces an `annotation-template.json`. It contains manuscript text,
candidate features, stable opaque work-group IDs and empty judgment fields, with
no actual publication journal or DOI label. Shuffle candidate order for human
review, annotate suitable and unsuitable venues independently, and preserve work IDs.
The export uses `submission_date` as `available_date` where supplied. After adding
verified dates and judgments, `split-corpus` also accepts this `rows` format and
assigns explicit split fields; undated groups are quarantined.

## Train and load an expert reranker

Create a JSON object with **separate nonempty** `train` and `validation` lists.
Each manuscript row needs `paper_id`, `split` matching the partition, optional
duplicate identifiers/work ID, and `candidates` copied from the annotation export.
Mark only explicitly reviewed candidates with `judged: true`, set `relevance`
between 0 and 3, and record reasons and `label_provenance`. Leave other candidates
unjudged. Do not put the same work or version into both partitions.

```sh
journal-match train-ranker path/to/graded-judgments.json --output results/ranker.json --epochs 200 --seed 0
journal-match analyze path/to/manuscript.tex --catalog results/catalog.sqlite --msc data/msc2020.json --reranker results/ranker.json --output-dir results/learned
```

Training optimizes pairwise logistic preference loss with L2 regularization and
equal weighting per manuscript. It records feature/schema versions, train/validation
fingerprints, seed and validation pairwise accuracy against the default weights.
The saved model contains inspectable JSON weights; no executable model deserialization
is used. Scores are uncalibrated relative preferences, not acceptance probabilities.

Keep the `feature_schema_version` field from the annotation export when creating
the training JSON. Version 1 is the existing hybrid feature set; version 2 is the
focused experiment and adds `primary_focus` and `secondary_focus`. Both schemas
are supported. Load a version-2 ranker with `--retrieval focused --reranker ...`;
the matcher rejects a model trained for a different retrieval mode instead of
silently changing the meaning of its features. Existing version-1 models remain
compatible with the default hybrid mode.

A historical venue alone does not provide a negative label for every other venue.
The trainer therefore refuses datasets without explicit unequal judgments. No
production reranker has been trained on the twelve-paper pilot, and no synthetic
judgments are shipped as real expert labels. Obtain the planned expert labels and
check held-out gains before selecting a learned model for production.

## Score saved rankings

`evaluate` computes top-k hit rate, recall, MRR, binary nDCG, recommendation
coverage and candidate recall where supplied. Each case needs a unique `paper_id`,
independently supplied `relevant_journal_ids` and ordered `ranked_journal_ids`.
Optional `candidate_journal_ids` measure candidate recall. Multiple relevant
journals are allowed; an empty ranking is an abstention and counts as a miss
when the paper has suitable labeled venues.

```sh
journal-match evaluate examples/evaluation.example.json --k 3 --output results/metrics.json
```

The [example](../examples/evaluation.example.json) uses fictional journal IDs to
check metric arithmetic. This command scores saved rankings; it does not run the
matcher, create judgments or enforce train/test separation. When scoring supported
final recommendations, retain only `strong match` and `plausible match` entries,
and report that filtering rule. The report's `ranked_candidates` contains the
final shortlist, not the complete retrieval pool.

## Reproduce the original legacy pilot

Prefer `journal-match benchmark` for new experiments. The standalone script
preserves the original pilot's legacy ranking and 24/12 cutoffs, even in a newer
checkout. It remains supported for historical comparisons.

`scripts/benchmark_published.py` compares a saved set of article inputs with independently stored publication labels. It records every model prompt and JSON response, the complete MSC pool, the 24 candidates passed to journal profiling, the final 12 candidates, and up to three recommendations. Errors stop the run rather than dropping difficult cases from the denominator.

Prepare a dataset directory containing:

- `cases.json`: a list of objects with unique `paper_id`, `title`, `abstract`, optional `arxiv_id`, and optional `alternate_titles` for duplicate screening. Source/provenance fields may be included; the model receives only title and abstract.
- `labels.json`: objects with matching `paper_id`, `actual_journal_id` (catalog ID), `actual_journal`, and optional `doi` and source links. These labels are used for global target exclusion, then joined to predictions after inference.
- `supplied-msc.json`: objects with `paper_id`, nonempty `msc_codes`, and `provenance`. Used only by the supplied-MSC diagnostic. Distinguish author-provided codes from analyst judgments.

From `demo2`, run:

```sh
python scripts/benchmark_published.py --dataset /path/to/dataset --output /path/to/new-run --mode heuristic
python scripts/benchmark_published.py --dataset /path/to/dataset --output /path/to/new-diagnostic --mode supplied-msc
python scripts/benchmark_published.py --dataset /path/to/dataset --output /path/to/new-model-run --mode openai --model YOUR_MODEL_ID
```

OpenAI mode uses the existing `OpenAIJSONModel` adapter and locally configured `OPENAI_API_KEY`. It makes model requests; it does not train or fine-tune a model. Choose and record the model explicitly. Output directories must be new, preventing accidental reuse of stale profiles. `--framework-root` selects a frozen copy of `demo2` to keep benchmarked implementation/data stable while changing the harness.

Additional diagnostic flags:

- `--without-title`: rerun on abstracts alone and compare top-three overlap.
- `--sample-only`: discard imported MSC aggregate statistics and rebuild coverage from target-excluded example articles only.
- `--primary-only`: in supplied-MSC mode, remove secondary codes to test field mixing.

The supplied-MSC mode runs the existing deterministic candidate ranker with subject codes and tokenized title/abstract; technical depth and audience breadth stay unknown. It bypasses model classification, journal profiling, and the final explanatory model. Its three outputs are **subject-only ranking leads**, not validated submission advice. The heuristic mode runs the model interface using the fixed smoke-test backend; it also cannot validate an editorial LLM.

The primary score is whether the historical publication journal occurs among the top three. A paper's actual journal is only one observed suitable destination. Missing it does not prove that every alternative is inappropriate, and finding it does not predict acceptance.

This title/abstract protocol does not test TeX extraction, proof/section processing, or author confirmation of central results. A stronger benchmark must freeze submission-time versions and reference data, keep all versions of a paper in one split, and add expert judgments of several suitable journals. Aggregate provider statistics without document lineage cannot be fully decontaminated; use the sample-only ablation to expose that limitation. Exact DOI/title/arXiv screening cannot rule out unrecognized duplicate versions or LLM pretraining memorization.

## What has actually been evaluated

The [benchmark index](../benchmarks/README.md) distinguishes the development pilot,
public-evidence ablation and publication-venue learning experiment. None provides
independent expert validation of the full manuscript-to-explanation workflow.
The 12-paper pilot has informed development; it is not an untouched test set.
No production expert reranker or real semantic-encoder evaluation is shipped.
Use fresh held-out data before changing defaults based on these results.
