# Public metadata collection, 7 September 2026

`collection-plan.json` fixes 50 journal identities across nine mathematical
collection strata. The quota is 60 usable abstracts per journal/year for
2020–2023 and 20 per journal/year for 2024–2025: a ceiling of 14,000 records.
The larger ceiling leaves room for a 10,000-paper training sample and independent
holdouts if abstract coverage permits.

The completed collection contains **10,973 records across all 50 journals**.
`collection-summary.json` records yearly counts and every quota shortfall.
`article-manifest.json` lists each work's DOI, OpenAlex ID, journal, year,
source page checksum and observation date. It contains no bulk abstract text.
`previous-benchmark-exclusions.json` records the 56 older benchmark identities
that must be excluded from the new train/validation/test corpus.

The local raw response cache and normalized abstracts are at
`output/journal-training-2026-09-07/collection/` relative to the repository root.
They are not part of this distributable manifest. Original abstract/article
rights remain with the rights holders; a metadata license does not change them.

The source was the [OpenAlex API](https://help.openalex.org/api/), with
`primary_location.source.issn`, `publication_year`, `has_abstract`, `type` and
`is_retracted` filters, sorted by ascending publication date. Source pages are
cached before checkpoints. Each normalized record preserves the reconstructed
abstract, DOI, publication and observation dates, source identity and provenance.
It records the limitations of provider article-type labels. OpenAlex topics are
kept separate from MSC classifications and expert judgments.

Reproduction commands, experiment safeguards and model usage are documented in
[BROAD_TRAINING.md](../../BROAD_TRAINING.md). The
[benchmark report](../../benchmarks/broad-training-2026-09-07/REPORT.md) contains
the frozen learning curve and each test paper's top three recommendations.
