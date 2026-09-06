# Review: mathematics journal matcher

Reviewed 2026-09-06 against the linked public `demo2` and its local working copy.
The public `catalog.py` and `pipeline.py` matched the local versions at the start
of this review. Existing local work elsewhere in the repository was preserved.

## Assessment

The demo is a useful foundation: extracting manuscript structure, confirming the
main result, using the MSC hierarchy, restricting journal names to a catalog,
and producing field-local explanations are sensible components. Assuming all
mathematics is correct removes proof checking from the task. It still leaves
novelty, significance, audience, and editorial expectations to assess.

The present system is a subject-and-audience recommender with heuristic technical
level matching. It is not yet a validated predictor of appropriate submission
venues. Editorial merit and suitability are distinct considerations in the
[AMS guidelines for journal editors](https://www.ams.org/sec-guidelines-jrl-editors).
Technical sophistication alone should not stand in for either one.

I would define the target as an evidence-supported set of reasonable submission
options, conditioned on author priorities, rather than a unique correct journal.
A published venue can be one positive label without making every alternative
incorrect. Historical choices can also reflect author preferences and earlier
submission decisions that the dataset does not observe.

## What the bundled data actually supports

Direct counts from `data/catalog.example.json`:

| Item | Count |
| --- | ---: |
| Journal records | 1,516 |
| Example articles | 163 |
| Journals with any example article | 115 |
| Articles with nonempty abstracts | 61 |
| Articles with DOI metadata | 149 |
| Scope summaries beginning “Indexed mathematics journal.” | 1,513 |
| Journals with supplied technical level or audience breadth | 0 |

The articles span 2020–2026. Only 22 are from 2025–2026. The snapshot therefore
contains much more registry coverage than comparable-paper evidence. An MSC
coverage sentence is not an independently verified editorial scope statement.
Increasing model size cannot recover evidence absent from the input.

For a serious pilot, I would start with one or two subfields and roughly 20–40
plausible journals, with a reasonably representative sample of recent papers for
each. These are proposed pilot sizes, not empirically established thresholds.
Include broad mathematics journals alongside specialist venues. Choose a window
appropriate to publication volume and report the dates and coverage explicitly.

## Changes implemented in this review

1. **Correct MSC specificity.** Previously, `prefix == code` made `05` an
   “exact-subfield” match whenever a broad field appeared explicitly in the query.
   Since the pipeline includes broad fields, high-volume broad venues could
   displace exact matches. Specificity now depends on the matched code's depth.
   Zero-count statistics are excluded.
2. **Rank before cutting the pool.** Previously, SQL limited each MSC lookup by
   article volume before lexical or level scoring. The matcher now scores all
   MSC candidates before selecting the model-profile shortlist. This removes
   that particular volume cutoff; it does not establish optimal ranking weights.
3. **Count distinct articles.** An article with `05C35` and `05C80` previously
   contributed twice to `05C` and `05`. Parent coverage now counts the paper once,
   preventing derived shares above one.
4. **Preserve aggregate statistics on merges.** Rebuilding statistics from a
   newly imported article sample previously deleted the entire aggregate table.
   Source provenance now distinguishes imported aggregates from locally derived
   counts. The latter can be rebuilt without erasing the former.
5. **Use consistent evidence.** Representative papers are selected using the
   same MSC prefix as the winning statistic, instead of an arbitrary longest
   matching code. The actual evidence prefix appears in the profile prompt.
6. **Make caches reproducible.** A journal profile cache now checks a digest of
   its prompt, supplied evidence, and model identity. Changing models, switching
   offline/live modes, or updating evidence triggers regeneration. This is a
   local evidence cache, not a live scope-refresh mechanism.
7. **Validate identifiers and limit unsupported claims.** Unknown, duplicate,
   and other-journal article citations are removed. A recommendation without
   valid citations is explicitly insufficient. Strong-fit claims require cited
   abstract evidence, a high-confidence field profile, and matching technical
   level. These are necessary checks, not proof of suitability; the remaining
   natural-language reasons are still model-generated and need assessment.
8. **Expose evidence and scoring.** Reports include journal websites, cited
   article titles and source links, weighted score components, and the final
   candidate shortlist. Readable sample size, rather than a registry aggregate,
   contributes to the available-evidence score. Scores are marked uncalibrated.
9. **Validate classification and isolate offline evidence.** Codes must exist
   in the loaded taxonomy, and names come from that taxonomy. Author corrections
   replace stale broad fields. Offline keyword checks inspect manuscript text
   rather than also searching taxonomy options. Word boundaries prevent `graph`
   from matching the `BIBLIOGRAPHY` heading. Invented central-result IDs are
   rejected even when the manuscript contains no theorem environments.
   Confirmed theorem statements are carried into the final matching prompt;
   previously that stage could receive an empty central-results list despite
   the author having selected a theorem.
10. **Add evaluation and regression coverage.** The `evaluate` command scores
    externally labeled rankings with multiple suitable venues per manuscript.
    Regression tests cover the preceding failure modes. Pytest explicitly loads
    `demo2/src`, avoiding the separate package copy at the repository root.

## What I would build next

### 1. Compare contributions with actual neighboring papers

Retrieve papers using the title, abstract, central theorem statements, MSC codes,
methods, and references. Start with a reproducible lexical retrieval baseline;
compare it with mathematical text embeddings on a held-out set before adopting
them. Aggregate evidence at the journal level using a bounded number of relevant
papers per journal so sheer publication volume does not dominate.

For each neighboring result, record a comparison the author can inspect:

- Mathematical objects and problem addressed.
- Hypotheses and conclusion of the supplied central result.
- Claimed improvement over a specifically identified prior theorem.
- Whether the method is new, adapted, or a direct application.
- Breadth of consequences and the research audiences they reach.
- What the supplied texts do not establish.

Novelty should remain unknown where the literature evidence is incomplete.
Keep technical difficulty, novelty, and significance as separate attributes.
A difficult specialized argument and a simple important theorem can warrant
very different editorial judgments. Neither should be ranked by difficulty
alone. Field-specific expert comparisons would help calibrate these judgments.

### 2. Represent editorial requirements explicitly

Add dated, sourced journal policies and distinguish observed facts from model
inferences: research versus survey articles, length restrictions, scope,
language, access options, and any author-specified budget constraints. Apply
known incompatibilities before ranking. Unknown policy data should trigger a
targeted check, not be treated as satisfying a requirement.

Assess editorial ambition using contribution comparisons and expert labels.
Do not reduce it to citation counts or technical jargon. Ask authors whether
they prioritize a broad audience, a close specialist fit, or an ambitious first
submission, then explain how that changes the shortlist. Avoid describing any
option as a guaranteed or statistically safe acceptance without suitable data.

### 3. Establish a benchmark that tests the intended task

Build a time-split benchmark of manuscript versions available before their
eventual publication. Freeze the journal corpus, policies, and cached profiles
to the information available before each evaluation date. Remove the same
paper's DOI matches, arXiv versions, title variants, and near duplicates from
retrieval and comparable-paper evidence. Exclude publication headers and explicit
destination labels from the query; keep legitimate cited research available.

Use historical publication destinations as weak labels for an initial retrieval
check. For the main benchmark, have subject experts independently judge several
reasonable venues per paper and record disagreements. Hide author identities
and historical destination while obtaining relevance judgments. Generalization
to unpublished work needs this expert evaluation; reproducing publication labels
alone is an incomplete proxy.

Measure candidate recall separately from final recommendation ranking. Then
report top-k hit rate, recall, MRR, and nDCG, broken down by subfield and journal
coverage. Include macro averages so populous fields do not dominate. Also assess
citation validity, unsupported explanation claims, abstention coverage, and how
often classification changes under paraphrases of the same contribution.

Compare MSC-only, lexical, current heuristic, and any embedding/reranker variants.
Tune weights on development cases only and reserve a final untouched test set.
The implemented evaluator computes basic ranking metrics; it does not create
these datasets, enforce temporal isolation, or perform the expert evaluation.

### 4. Improve evidence handling as the corpus grows

The current query is token overlap over a small sample, not semantic theorem
similarity. Primary and secondary MSC matches should receive distinct, validated
weights, while retaining a route for interdisciplinary and broad-audience venues.
Sparse samples should prompt targeted retrieval or abstention rather than a
confident generic journal profile. No fixed arbitrary sample cutoff can establish
that a journal never publishes a particular topic.

Normalize DOI URL variants and persist cross-provider aliases across database
sessions. Record source and retrieval dates for individual fields and articles.
Keep a balanced recent evidence sample instead of simply selecting the latest
few records. Add bounded, visible manuscript truncation and improve multi-file
LaTeX handling: the current extractor is deliberately incomplete and excludes
includes in subdirectories. These remain follow-up work.

## Validation and limits

The expanded local test suite and full-catalog offline CLI smoke test pass.
The smoke test imports all 1,516 journals and 163 article records, classifies the
included graph manuscript, and writes inspectable JSON and Markdown reports.
The evaluation example uses fictional labels to verify arithmetic only.

No paid live-model run, expert-labeled accuracy evaluation, real acceptance
prediction, or live editorial-policy verification was performed. The offline
model still contains fixed demonstration profiles and must not be used for
substantive recommendations. These changes fix demonstrable implementation
errors and improve auditability; they do not establish an accuracy improvement
on real unpublished mathematics papers.
