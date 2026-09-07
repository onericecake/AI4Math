# Top-three journal ranking experiment — 2026-09-07

The experimental `focused` ranker increases historical-venue Top-3 hits on the
12-paper development pilot from **0/12 to 5/12**. It does **not** improve the
separate 24-paper fixture validation set: hits fall from **3/24 to 2/24**.
The default remains `hybrid`; `--retrieval focused` explicitly selects the experiment.

| Dataset | Hybrid Top-3 | Focused Top-3 | Hybrid Recall@50 | Focused Recall@50 |
| --- | ---: | ---: | ---: | ---: |
| Original development pilot, 12 papers | 0/12 (0%) | 5/12 (41.7%) | 5/12 (41.7%) | 10/12 (83.3%) |
| Additional fixture validation, 24 papers | 3/24 (12.5%) | 2/24 (8.3%) | 11/24 (45.8%) | 13/24 (54.2%) |

Every run returns three subject-only leads per paper. These are supplied-MSC
retrieval diagnostics, with title and abstract as text inputs. They do not run
an editorial LLM or estimate acceptance probability. No semantic encoder, new
reference records, trained production ranker, or publication-label lookup is used.

## What changed

The previous hybrid score largely treated any broad MSC occurrence as equivalent
coverage. With sparse article examples, a journal with only incidental activity
in a field could outrank a specialist supported by a much larger publication record.
The experiment adds these general features without journal-specific boosts:

1. **Primary and secondary field concentration.** A journal's observed field
   share is smoothed toward the equal-journal corpus background using 50 prior
   observations, then square-root transformed. Population aggregates and local
   samples retain separate denominators. Detailed MSC counts are not added to
   their own broad parents. Tiny local samples have less influence.
2. **Separate journal names from substantive evidence.** A name-only document
   contributes at most one quarter of its text score. Actual scope text retains
   full weight. Registry boilerplate remains excluded from scope evidence.
3. **Corroborating article evidence.** Journal text similarity is the larger of
   its scope/name score and 75% of its best paper score plus 25% of the fixed
   three-paper mean. Fewer than three papers leave zero slots; extra irrelevant
   papers cannot dilute the score.

With semantic retrieval disabled, the fixed weights are primary/secondary MSC
compatibility 0.12/0.03, primary/secondary field concentration 0.42/0.08, lexical
similarity 0.25, abstract support 0.02, technical depth 0.05 and audience breadth
0.03. The latter two are unknown/neutral in these diagnostics. Optional semantic
retrieval transfers 0.14 from lexical to semantic similarity; that configuration
has not been evaluated with a real encoder here.

These weights were fixed before inspecting validation outcomes and were not
retuned afterward. The final implementation reproduces the initial experiment's
rankings. The default hybrid configuration also reproduces its frozen baseline.
See [compatibility and perturbation checks](checks.json).

## Interpretation of the errors

The pilot gains are Discrete & Computational Geometry, Journal of Number Theory,
The Annals of Probability, Journal of Commutative Algebra, and Algebraic &
Geometric Topology. Four of the five recovered journals appear at rank three;
the result is a useful candidate-ranking signal, not evidence of precise editorial
placement.

On validation, the experiment recovers Journal of Operator Theory but loses SIGMA
and L'Enseignement Mathématique. Their actual venues fall to ranks 10 and 5,
respectively, behind narrower field specialists. This exposes a limitation of
field concentration: a broader journal can be an appropriate destination even
when a specialist publishes a greater fraction of papers in the subject.

See the complete [12-paper comparison](pilot-comparison.md) and
[24-paper comparison](validation-comparison.md), including each paper's three
recommendations and actual publication journal. Nothing is omitted for being a miss.

## Validation protocol and limits

The additional set was frozen before changing the ranking: shuffle eligible
bundled records using seed `20260906`, then take the first 24 distinct journals.
Eligibility requires a DOI, MSC codes and at least 200 abstract characters,
excluding the existing reprint/memorial title filters. See its
[selection manifest](validation/selection.json). The labels come from the
existing catalog; they were not freshly reverified against publishers. Article
types and languages are not independently curated, so this is a heterogeneous
fixture validation set, not a representative research-only sample.

For both methods, every target and its recognized versions are excluded globally
from reference article text, and local derived statistics are rebuilt. Publication
labels are joined only after prediction. However, the imported historical MSC
aggregates have no document-level lineage and may still include target contributions;
they also lack historical availability dates. Consequently, this is **not** a strict
temporal benchmark or an independent external test. Do not pool the development and
validation scores to claim general accuracy.

Removing titles leaves the focused pilot's three recommendations in the same order
for all 12 papers; Hit@3 remains 5/12. Shuffling article, journal and aggregate input
order also leaves all 12 complete top-100 rankings unchanged. These narrow
perturbation checks do not replace testing paraphrases, alternate classifications,
full manuscripts, or unfamiliar journals.

The runs save descriptive bootstrap intervals, but these small nonrandom samples
do not support population-level accuracy guarantees. One historically accepted
journal is also not an exhaustive list of suitable destinations.

## Run the comparisons

From `demo2`, after installing the package:

```sh
journal-match benchmark --dataset benchmarks/focused-2026-09-07/pilot --retrieval hybrid --output-dir results/pilot-hybrid
journal-match benchmark --dataset benchmarks/focused-2026-09-07/pilot --retrieval focused --output-dir results/pilot-focused
journal-match benchmark --dataset benchmarks/focused-2026-09-07/validation --retrieval hybrid --output-dir results/validation-hybrid
journal-match benchmark --dataset benchmarks/focused-2026-09-07/validation --retrieval focused --output-dir results/validation-focused
journal-match benchmark --dataset benchmarks/focused-2026-09-07/pilot --retrieval focused --without-title --output-dir results/pilot-no-title
journal-match analyze examples/manuscript.tex --catalog results/catalog.sqlite --msc data/msc2020.json --retrieval focused --offline --yes --output-dir results/focused-smoke
```

Import the catalog first for the final smoke command, as described in the
[catalog guide](../../docs/catalog.md). Use fresh benchmark output
directories. Each generated run under `results/` contains predictions, metrics,
exclusion audits and source/input fingerprints. The corpus is the unchanged
`data/catalog.example.json`.

Focused expert-label exports carry `feature_schema_version: 2`. Preserve this
field in a training dataset and use `--retrieval focused` when loading the
resulting ranker. Existing version-1 hybrid models remain supported. A mismatched
model/mode fails explicitly. No expert labels or production model were created
as part of this experiment.

## Next accuracy work

1. Collect comparable recent article evidence across specialist and broader
   journals, then curate actual scope and article-type policies. Both Crossref
   and zbMATH metadata connections timed out from this machine during this run;
   the collector remains available, but this experiment added no reference papers.
2. Obtain independent suitability judgments for alternatives in the same field,
   including broader venues. These should teach the ranker how to trade subject
   concentration against article contribution, audience and scope. Publication
   labels alone do not justify treating every alternative as a negative.
3. Freeze a new external test set before choosing a learned model or tuning
   additional weights. Compare top-three suitability and historical-venue hits,
   preserve abstentions, and report results by field and journal breadth.

This experiment supports further investigation of field-distribution features.
Its validation result does not justify promoting the focused mode to the default.
