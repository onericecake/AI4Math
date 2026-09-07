# Published-paper benchmarking

The [public-evidence ablation](public-evidence-2026-09-07/REPORT.md) adds
60 online-collected reference records and evaluates 20 new published papers,
with global exclusion of all 56 old/new targets. It reports both improvements
on the sampled journals and regressions on the earlier set.

The [2026-09-07 top-three experiment](focused-2026-09-07/REPORT.md) ships a frozen
12-paper development pilot, 24 additional fixture validation papers, per-paper
predictions and both positive and negative results for `--retrieval focused`.

For the new hybrid retriever, model/full-text runs, strict temporal filtering and
expert-label exports, use `journal-match benchmark` as documented in
[the accuracy workflow](../ACCURACY_WORKFLOW.md). The standalone script below
preserves the original pilot's legacy ranking and 24/12 cutoffs, including when
run against a newer checkout.

`../scripts/benchmark_published.py` compares a saved set of article inputs with independently stored publication labels. It records every model prompt and JSON response, the complete MSC pool, the 24 candidates passed to journal profiling, the final 12 candidates, and up to three recommendations. Errors stop the run rather than dropping difficult cases from the denominator.

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
