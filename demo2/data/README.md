# Data inventory

[Home](../README.md) · [Catalog guide](../docs/catalog.md) · [Benchmarks](../benchmarks/README.md)

## Bundled fixtures

| File | Contents | Purpose |
| --- | --- | --- |
| [catalog.example.json](catalog.example.json) | 1,516 journals, 163 articles and MSC coverage statistics | Canonical importable test catalog |
| [msc2020.json](msc2020.json) | 6,603 taxonomy entries across 63 broad fields | Complete MSC2020 classification hierarchy |
| [JOURNAL-CATALOG-NOTICE.txt](JOURNAL-CATALOG-NOTICE.txt) | Source and snapshot notice | Keep with the catalog |
| [MSC2020-LICENSE.txt](MSC2020-LICENSE.txt) | MSC source attribution and license notice | Keep with the taxonomy |

The base catalog was retrieved on 2026-09-01. Only 115 journals have example
articles, and only 61 of the 163 articles have abstracts. Most scope summaries
are derived from MSC coverage. This is a frozen testing snapshot; neither active
journal status nor current editorial policies are refreshed automatically.

The former `journal_catalog.sample.json` and `msc2020.sample.json` were byte-for-byte
duplicates of the canonical files and have been removed. Update external commands
that still refer to those names.

## Additional collections

| Directory | Included | Generated separately |
| --- | --- | --- |
| [public-evidence-2026-09-07](public-evidence-2026-09-07/README.md) | 60 publisher abstracts, six scope profiles, ten policy statements, attribution and an importable catalog addition | Local merged SQLite database |
| [broad-training-2026-09-07](broad-training-2026-09-07/README.md) | Fixed 50-journal collection plan, 10,973-record identity manifest, counts and prior benchmark exclusions | Raw response cache, normalized training corpus and trained model |

The public-evidence `articles.json` and `journals.json` expose the records also
packaged in `catalog.additions.json`; both views are retained for auditing and
are used by the benchmark tooling. Article attribution and license URLs remain
with each record. The broad-training manifest contains identities and provenance,
not bulk abstracts; [collect and train](../docs/training.md) to build a local model.

## Working data

From `demo2`:

```sh
journal-match catalog import-json data/catalog.example.json --database results/catalog.sqlite
journal-match catalog counts --database results/catalog.sqlite
journal-match catalog coverage --database results/catalog.sqlite --output results/coverage.json
```

Keep generated databases, caches and model files under the ignored `results/`
directory. Collection snapshots record what was observed at a particular time;
recollection can change contents and benchmark outcomes. See [catalog provenance](../docs/catalog.md)
for merging and date handling, and the dated [benchmark reports](../benchmarks/README.md)
for the measurements associated with these collections.
