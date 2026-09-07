# Helper scripts

[Home](../README.md) · [Evaluation](../docs/evaluation.md) · [Venue training](../docs/training.md)

Run from `demo2` after installing the package. Prefer the `journal-match` CLI
for normal analysis, catalog management, training and new benchmark runs.

| Script | Purpose |
| --- | --- |
| [benchmark_public_evidence.py](benchmark_public_evidence.py) | Reproduce the eight frozen before/after evidence ablation runs without network or model access |
| [benchmark_published.py](benchmark_published.py) | Preserve the original legacy pilot protocol and 24/12 cutoffs; intentionally retained for historical comparisons |
| [collect_broad_training.py](collect_broad_training.py) | Convenience wrapper for the fixed OpenAlex plan; equivalent collection is available through `catalog harvest-openalex` |
| [report_venue_experiment.py](report_venue_experiment.py) | Export metrics, identities and predictions from a completed local training experiment |

```sh
python scripts/benchmark_public_evidence.py --output-dir results/public-evidence
python scripts/collect_broad_training.py --output results/venue-training/collection
python scripts/report_venue_experiment.py results/venue-training/experiment \
  --output results/venue-training/report
```

Collection needs network access; the report exporter needs a completed
[`train-venues` run](../docs/training.md). Benchmark run directories must be new.
The [legacy benchmark guide](../docs/evaluation.md#reproduce-the-original-legacy-pilot)
documents its separate modes and input requirements.
