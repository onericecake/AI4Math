# Examples

[Home](../README.md) · [Usage](../docs/usage.md) · [Evaluation](../docs/evaluation.md)

| File | Purpose |
| --- | --- |
| [manuscript.tex](manuscript.tex) | Deliberately small, synthetic graph-theory manuscript for extraction and CLI checks |
| [offline-report/report.md](offline-report/report.md) | Readable output from the current offline workflow |
| [offline-report/report.json](offline-report/report.json) | The same output with scores, article evidence and the final candidate shortlist |
| [evaluation.example.json](evaluation.example.json) | Fictional journal labels and an abstention for checking metric arithmetic |

## Reproduce the report

From `demo2`, after installation, use a fresh catalog path:

```sh
journal-match catalog import-json data/catalog.example.json --database results/example-catalog.sqlite
journal-match analyze examples/manuscript.tex \
  --msc data/msc2020.json --catalog results/example-catalog.sqlite \
  --offline --yes --output-dir results/example-report
```

The checked-in report uses the default hybrid retrieval and its 50/24 limits.
The offline model has fixed demonstration profiles. Its explanations and scores
are software fixtures, not editorial advice or measured accuracy. The manuscript
itself is intentionally underspecified and makes no substantive mathematical claim.

The older `arxiv-2608.18255.report.*` files were removed because they used an
outdated report/evidence format and required an external source archive. The
example here ships its input and reproduces without a download or API key.

To refresh the snapshot after a behavior change, run the commands above, inspect
the report, and copy both output files into `examples/offline-report/`.
