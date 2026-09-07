# Catalogs, collection and provenance

[Home](../README.md) · [Data inventory](../data/README.md) · [Evaluation](evaluation.md)

Run these commands from `demo2` after [installation](../README.md#quick-start).

## Inspect coverage and prepare a collection

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

## Preserve provenance and paper identities

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

## Add the published evidence batch

The [public-source batch](../data/public-evidence-2026-09-07/README.md) supplies
60 publisher abstracts and six sourced journal scope profiles. Import both files
into a fresh database to build the 223-article experimental corpus:

```sh
journal-match catalog import-json data/catalog.example.json \
  data/public-evidence-2026-09-07/catalog.additions.json \
  --database results/enriched.sqlite
```

The [ablation report](../benchmarks/public-evidence-2026-09-07/REPORT.md) records
both gains and regressions. Public policies are evidence for explanations; they
are not graded manuscript–journal suitability judgments.

For the separate 50-journal OpenAlex collection, follow [venue training](training.md).
The checked-in manifests describe a completed historical collection. Raw caches,
normalized training abstracts and trained models are not shipped in this repo.
