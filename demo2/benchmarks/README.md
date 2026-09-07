# Benchmark inventory

[Home](../README.md) · [Evaluation guide](../docs/evaluation.md) · [Data inventory](../data/README.md)

These directories preserve dated experiment inputs, reports and audit records.
They measure different tasks and candidate sets; their percentages are not a
single journal-matching accuracy score. Historical publication venues provide
one observed destination, not an exhaustive list of suitable journals.

## Experiments

| Experiment | Inputs and task | Result and status |
| --- | --- | --- |
| [Broad venue training](broad-training-2026-09-07/REPORT.md) | 8,967 train / 979 validation / 991 test articles; title/abstract ranking within 50 journals | Selected model Top-3: 60.0%; BM25: 46.1%. Corpus and weights are generated locally. |
| [Public-evidence ablation](public-evidence-2026-09-07/REPORT.md) | 36 existing and 20 new targets; supplied-MSC retrieval before/after adding publisher evidence | Hybrid Top-3 improves from 2/20 to 13/20 on new targets and falls from 4/36 to 3/36 on existing targets. |
| [Focused retrieval](focused-2026-09-07/REPORT.md) | 12 development and 24 fixture validation papers; fixed hybrid/focused weights | Pilot Top-3: 0/12 → 5/12; validation: 3/24 → 2/24. Hybrid remains the default. |

Read each report's protocol, exclusions and limitations before interpreting its
metrics. Test counts in dated reports describe validation at that time, not the
current test suite. Raw JSON manifests and predictions retain their original
provenance, including historical local output paths. Those paths are not files
required from a fresh checkout.

## Reproduce or extend

For a small offline retrieval diagnostic, run from `demo2` after installation:

```sh
journal-match benchmark \
  --dataset benchmarks/focused-2026-09-07/pilot \
  --catalog-json data/catalog.example.json --msc data/msc2020.json \
  --retrieval hybrid --output-dir results/pilot-hybrid
```

Use a new output directory for each run. The focused report includes all
comparison commands. The public-evidence ablation is reproduced with
`python scripts/benchmark_public_evidence.py --output-dir results/public-evidence`.
The [training guide](../docs/training.md) covers recollecting and training the
50-journal model; live recollection cannot guarantee identical historical metrics.

For new evaluation sets, prepare:

- `cases.json`: list of unique `paper_id`, `title` and `abstract` records; optional
  duplicate identities, alternate titles and submission dates.
- `labels.json`: matching `paper_id`, `actual_journal_id`, `actual_journal` and
  optional DOI/source fields, kept separate from inference text.
- `supplied-msc.json`: matching `paper_id`, nonempty `msc_codes` and `provenance`
  for the supplied-MSC diagnostic; distinguish author codes from analyst judgments.

The [evaluation guide](../docs/evaluation.md) describes model/full-text runs,
strict temporal filtering, expert annotations, saved-ranking metrics and the
legacy harness. Small frozen fixtures and already-inspected holdouts remain
useful for regression checks; use a fresh holdout for new model selection.
