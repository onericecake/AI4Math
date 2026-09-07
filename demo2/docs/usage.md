# Using the matcher

[Home](../README.md) · [Catalogs](catalog.md) · [Evaluation](evaluation.md)

Run commands from `demo2` after the [quick start](../README.md#quick-start).
The installed `journal-match` command also works as `python -m journal_matcher`.

## Manuscript analysis

```sh
journal-match analyze path/to/manuscript.tex \
  --msc data/msc2020.json --catalog results/catalog.sqlite \
  --output-dir results/manuscript
```

The extractor accepts `.tex` and `.latex`, retains sections, proofs, theorem-like
environments and bibliography text, and expands local `\input`/`\include` files
in the manuscript's own directory. Includes in subdirectories are not expanded.
It does not compile TeX, expand arbitrary macros or check mathematical correctness.

The CLI proposes central results, asks for confirmation, classifies the paper,
retrieves journals, profiles their article evidence and writes recommendations.
For unattended runs, `--yes` accepts proposals. You can instead supply confirmed
values explicitly:

```sh
journal-match analyze examples/manuscript.tex \
  --msc data/msc2020.json --catalog results/catalog.sqlite \
  --central-result thm:main --primary-msc 05C35 \
  --offline --yes --output-dir results/confirmed
```

Repeat `--central-result` for several extracted result IDs and `--secondary-msc`
for additional classifications. `--central-text` supplies the central statement
when the source has no theorem environment. Codes must exist in the loaded
taxonomy. Supplying `--msc data/msc2020.json` loads the full taxonomy; omitting
it uses a limited built-in fallback and prints a coverage warning.

## Model configuration

| Setting | Behavior |
| --- | --- |
| `--offline` | Deterministic fixture model with limited keyword coverage; integration checks only |
| `OPENAI_API_KEY` | Credential used by the live model adapter |
| `--model MODEL_ID` | Explicit model choice |
| `OPENAI_MODEL` | Default when `--model` is absent; code fallback is `gpt-5.5` |

Live analysis sends extracted manuscript evidence and catalog evidence to the
configured model. Journal profiles are cached in the SQLite catalog by model
identity, prompt and supplied evidence. Offline profiles are not reused for live
analysis. A cache is not a mechanism for refreshing source metadata.

## Retrieval options

| Mode | Intended use |
| --- | --- |
| `hybrid` (default) | MSC candidates plus lexical article/scope retrieval, with distinct primary and secondary field scores |
| `focused` | Experimental field-concentration and corroborating-article features; see the [mixed validation results](../benchmarks/focused-2026-09-07/REPORT.md) |
| `legacy` | Original MSC/overlap ranking for historical comparisons |

Hybrid retrieval combines MSC candidates with the top 100 lexical/semantic
document hits. BM25 indexes titles, abstracts, optional introductions/main results,
journal names and substantive scope text. Generic registry scope boilerplate is
excluded. Representative articles are selected for query relevance with a small
year-diversity preference.

The current analysis defaults are **50 candidates** for journal profiling and
**24 candidates** for the final matching prompt. Set `--candidate-limit` and
`--final-limit` to change these. The original standalone benchmark explicitly
retains its historical 24/12 cutoffs.

Semantic retrieval is disabled unless an encoder is configured:

```sh
python -m pip install -e '.[semantic]'
journal-match analyze path/to/manuscript.tex \
  --msc data/msc2020.json --catalog results/catalog.sqlite \
  --embedding-model YOUR_SENTENCE_TRANSFORMERS_MODEL \
  --embedding-revision PINNED_MODEL_COMMIT --output-dir results/semantic
```

Selecting an encoder may download weights. Remote model code is disabled;
embeddings are cached by content and model identity. Encoder input limits may
truncate long evidence. No real-encoder accuracy result is included in this repo.
An optional `--reranker` loads weights from the [expert-label workflow](evaluation.md).
Encoders and learned rerankers require hybrid or focused retrieval.

## Reading reports

Each analysis writes `report.md` and `report.json`. The JSON contains the article
profile, up to three recommendations, cited article records, weighted score
components, limitations and `ranked_candidates` (the final shortlist).

Citation identifiers must belong to the supplied journal evidence. Unknown,
duplicate and other-journal citations are removed. A recommendation with no valid
citations is labeled `insufficient information`. Hybrid strong-fit claims require
at least three cited abstracts spanning two years, along with confidence and
level checks. These checks constrain unsupported claims; they do not calibrate
editorial suitability. The remaining explanations are model-generated.

Treat ranking scores as relative preferences. The fixed offline profiles and
hand-selected retrieval weights cannot validate novelty, significance or journal
acceptance. The [saved offline example](../examples/README.md) shows the report
format using the small bundled manuscript.

## Command reference

```sh
journal-match --help
journal-match analyze --help
journal-match catalog --help
journal-match benchmark --help
```

For the separate local title/abstract classifier, use
[`train-venues` and `recommend-venues`](training.md). It needs a collected corpus
and trained model; no model weights are bundled.
