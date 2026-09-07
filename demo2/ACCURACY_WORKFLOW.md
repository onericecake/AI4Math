# Building and testing a better reference corpus

For the completed 50-journal collection and trained publication-venue model,
start with [the online-data training workflow](BROAD_TRAINING.md). It needs no
human review packet. The expert-judgment sections below describe a separate
optional workflow; publication records are never converted into those judgments.

The matcher now has a complete path from balanced metadata collection to hybrid
retrieval, expert labeling, ranker training and held-out evaluation. The bundled
163-article catalog is still a small fixture. This implementation does not claim
to have collected 20,000 papers, trained on expert judgments, or established
editorial accuracy.

Run the commands below from `demo2` after installing the package.

## 1. Inspect coverage and prepare a collection

```sh
journal-match catalog import-json data/catalog.example.json --database results/catalog.sqlite
journal-match catalog coverage --database results/catalog.sqlite --output results/coverage.json
journal-match catalog plan --source data/catalog.example.json --journals 100 --per-journal 200 --start-year 2020 --end-year 2024 --seed 0 --output results/collection-plan.json
journal-match catalog harvest-crossref results/collection-plan.json --output-dir results/collection --require-abstract
journal-match catalog import-json results/collection/catalog.json --database results/catalog.sqlite
```

The plan chooses journals by seeded round-robin across dominant broad MSC fields,
then divides each journal's quota across years. It targets at most 20,000 papers
in the example above. Inspect the saved plan before collecting. Small journals or
missing abstracts can cause quota shortfalls; the collector reports them.

The Crossref collector uses journal ISSNs, publication-date windows and cursors.
Requests are paced, retry rate-limit/transient failures with backoff, and cache
responses locally. Each page saves a normalized catalog and checkpoint. Rerun the
same command to resume. Changing the plan or abstract filter requires a new output
directory. `--mailto` optionally supplies a contact address in API requests.
Network errors leave completed pages intact. An expired cursor may require a new
collection directory; DOI normalization makes reimporting completed papers safe.

Crossref supplies deposited metadata, including abstracts when available. It does
not supply the detailed MSC classifications required for this application; merge
normalized zbMATH/arXiv/curated records with those fields using `import-json`.
Do not assign every paper the broad fields of its journal. The collector preserves
the provider's generic `journal-article` type and records that the research subtype
was not independently verified. Curate surveys, editorials and other article types
before making strong editorial judgments. See the [Crossref API guidance](https://www.crossref.org/documentation/retrieve-metadata/rest-api/tips-for-using-the-crossref-rest-api/)
and [zbMATH's official API client](https://github.com/zbMATHOpen/zbRestApiClient).

## 2. Preserve provenance and paper identities

Normalized catalog JSON retains the existing `journals`, `articles` and optional
`journal_msc_stats` lists. Additional record fields survive import/export in
SQLite. Useful article fields are:

```json
{
  "article_id": "your-stable-id",
  "journal_id": "catalog-journal-id",
  "title": "Paper title",
  "abstract": "Paper abstract",
  "doi": "10.example/identifier",
  "arxiv_id": "2101.12345v1",
  "alternate_titles": ["Earlier title"],
  "msc_codes": ["05C35"],
  "available_date": "2021-01-15",
  "metadata_available_date": "2021-01-15",
  "source_url": "https://example.org/paper",
  "source": "source-name",
  "license": [],
  "introduction": "Optional extracted introduction",
  "central_results": [{"statement": "Optional central theorem statement"}]
}
```

`available_date` describes when this text/version was available, while
`metadata_available_date` describes when the supplied metadata was observed.
A newly harvested abstract is not assumed to be identical to one from five years
ago. Partial dates are interpreted conservatively as the last day of their interval.
Keep journal `registry_available_date` and `scope_available_date` too. Real aims
and scope, article-type policies, technical-level labels and audience labels must
be independently sourced; generic MSC registry descriptions are ignored as scope
text by the new retriever.

The database merges DOI and arXiv identities, including records bridged by a later
DOI/preprint link. It preserves aliases, readable abstracts and existing MSCs when
a new provider has no classifications. Explicit nonempty MSC corrections replace
old assignments. Identical titles alone do not merge database records, since
distinct works can share a title. Evaluation applies more conservative title/alias
grouping to keep possible duplicate targets out of reference data.

```sh
journal-match catalog export --database results/catalog.sqlite --output results/catalog.json
journal-match split-corpus results/catalog.json --train-end 2022-12-31 --validation-end 2023-12-31 --output results/splits.json
```

All connected versions go to the latest split required by any version; groups with
unknown availability dates are quarantined. This splitter does not create relevance
judgments, verify the provenance dates or guarantee author-disjoint evaluation.

## 3. Run hybrid matching

```sh
journal-match analyze examples/manuscript.tex --catalog results/catalog.sqlite --msc data/msc2020.json --offline --yes --output-dir results/smoke
```

Omit `--offline` and configure `OPENAI_API_KEY` for substantive model profiling.
The offline backend remains a fixed smoke-test fixture. The hybrid retriever works
without it: it takes the union of MSC candidates and the top 100 lexical/semantic
document hits, scores primary and secondary fields separately, then ranks journals.
BM25 indexes article titles/abstracts, optional introductions/main results, journal
names and substantive scope text. Representative articles are chosen for query
relevance, with a small year-diversity preference; they are not simply the latest
eight records.

Semantic retrieval is optional and **disabled unless an encoder is configured**:

```sh
python -m pip install -e '.[semantic]'
journal-match analyze path/to/manuscript.tex --catalog results/catalog.sqlite --msc data/msc2020.json --embedding-model YOUR_SENTENCE_TRANSFORMERS_MODEL --embedding-revision PINNED_MODEL_COMMIT --output-dir results/semantic
```

The model can be downloaded when selected. Use a pinned revision; arbitrary remote
model code is disabled. Embeddings are cached by content and model identity.
Changing an abstract or model invalidates its cache entry. Transformer input limits
can truncate long extracted evidence; choose and evaluate the encoder for your
manuscript lengths. See the [Sentence Transformers similarity documentation](https://www.sbert.net/docs/sentence_transformer/usage/semantic_textual_similarity.html).

Use `--retrieval legacy` to reproduce the previous MSC/overlap ranker, or change
`--candidate-limit 50 --final-limit 24` explicitly. Hybrid strong-fit claims require
at least three cited abstracts spanning two years as well as the existing level
and confidence checks. This is an evidence floor, not calibrated editorial accuracy.

An additional **experimental** mode is available with `--retrieval focused`.
It uses smoothed journal-level primary/secondary field shares, gives less weight
to journal-name matches, and rewards corroborating article matches. Its fixed
weights were evaluated without training on publication labels. The 12-paper pilot
improved from 0/12 to 5/12 historical-venue Top-3 hits, but a separate 24-paper
fixture validation set fell from 3/24 to 2/24. Consequently, `hybrid` remains the
default. The [experiment report](benchmarks/focused-2026-09-07/REPORT.md) includes
both datasets, all three predictions per paper, and reproduction commands.

## 4. Benchmark without giving publication labels to the model

Use a dataset directory with the `cases.json`, `labels.json` and `supplied-msc.json`
formats described in [benchmarks/README.md](benchmarks/README.md).

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

## 5. Train and load a reranker

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

## Current validation limits

The 12-paper pilot is a development regression set, not an independent accuracy
test. With the unchanged small corpus and semantic embeddings disabled, the new
retriever improves historical-venue Recall@50 from 3/12 to 5/12; Top-3 remains 0/12.
This demonstrates better candidate retention without establishing editorial success.
The bulk collector and encoder cache are covered by deterministic fixtures, but
Crossref timed out from the development machine, and no real embedding weights or
live OpenAI run were available. The 20,000-record plan is ready; collection and
expert annotation remain necessary.

## Online-collected evidence update

The [2026-09-07 public-source batch](data/public-evidence-2026-09-07/README.md)
provides 60 actual publisher abstracts and six sourced journal scope profiles.
It can be imported with the existing catalog CLI; collection does not depend on
user-supplied annotations. Public editorial policies are not graded expert
labels, and publication outcomes must not be substituted for those labels in
`train-ranker`. The [data ablation](benchmarks/public-evidence-2026-09-07/REPORT.md)
includes both gains and regressions, with unchanged ranking weights.
