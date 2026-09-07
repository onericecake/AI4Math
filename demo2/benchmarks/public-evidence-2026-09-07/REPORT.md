# Public evidence ablation — 2026-09-07

We collected **60 real articles with publisher abstracts across six journals**, plus six updated scope profiles and ten public editorial-policy statements. The catalog grows from **163 to 223 articles**, and from **61 to 121 nonempty abstracts**. No human review packet, private reviewer data, fabricated expert labels or model training was used.

The added data improves historical-venue retrieval on the newly sampled journals but slightly worsens the existing benchmark. The default ranking and frozen example catalog remain unchanged. The additions are an experimental importable corpus.

## Results

All runs use identical fixed weights within each retrieval strategy. The only before/after change is reference articles and public journal metadata.

| Dataset | Retrieval | Top-three hits before | Top-three hits after | Candidate recall at 50 before → after |
|---|---|---:|---:|---:|
| Existing 36 papers | hybrid (default) | 4/36 (11.1%) | 3/36 (8.3%) | 50.0% → 47.2% |
| Existing 36 papers | focused (experimental) | 7/36 (19.4%) | 6/36 (16.7%) | 63.9% → 63.9% |
| New 20 papers | hybrid (default) | 2/20 (10.0%) | 13/20 (65.0%) | 30.0% → 100.0% |
| New 20 papers | focused (experimental) | 1/20 (5.0%) | 9/20 (45.0%) | 35.0% → 95.0% |

Every paper has three saved leads. See the full [new-paper comparison](new20-comparison.md), [existing-paper comparison](existing36-comparison.md), [metrics](summary.json) and [manifest](manifest.json).

The old-set hybrid regression is p04. Focused loses p07 and p08 and gains v01. These movements are retained, rather than selecting a favorable subset. Additional reference articles can raise a journal's lexical score and displace a previously recovered venue. The benchmark alone cannot decide whether those alternative venues would also be suitable.

## Collection and evaluation design

- Sources: Annales Henri Lebesgue, Annales de l'Institut Fourier, Algebraic Combinatorics, SIGMA, Journal de théorie des nombres de Bordeaux and Journal de l'École polytechnique — Mathématiques. Each contributes five displayed eligible research articles from 2021 and five from 2024. See [sampling, licensing and the 60 article sources](../../data/public-evidence-2026-09-07/README.md).
- The existing dataset is the earlier 12-paper pilot plus 24 fixture papers. It has already informed development and is not an untouched test set.
- The new diagnostic uses **every collected 2024 paper with usable publisher MSC codes: 20 papers, five each from AIF, ALCO, JEP and JTNB**. Selection happened before scoring. AHL and SIGMA pages did not supply MSC codes, so their papers are reference data only in this diagnostic.
- All **56 targets** are excluded together from every reference pool, using connected DOI/title/arXiv identities. Local derived statistics are rebuilt after exclusion. The before reference pool has 133 eligible articles; after has 173. Thus **40 of the 60 additions** can serve as references in these experiments; the other 20 are held-out targets. There are no overlaps between the new batch and the earlier 36 targets.
- All catalog candidate venues remain available; retrieval is not restricted to the six collected journals. The input includes title, abstract and supplied MSC codes. The publication journal is joined to predictions after retrieval.
- Publisher code order is used as the query primary/secondary order for the new diagnostic; the publisher pages do not establish those roles. Two codes absent from MSC2020 are quarantined, with the original strings retained.
- Public scope and referee guidance is passed to journal profiling/matching prompts with provenance. No live LLM was called here, so these results do not measure the effect of the new editorial-guidance prompts. Scope text and article metadata do affect deterministic retrieval.

## What this establishes

Richer reference data substantially improves retrieval for the sampled journals. The gain on the new set should not be presented as a general 65% journal-matching accuracy: this is a small convenience sample, with deliberate coverage of the same journals as the new reference data.

The evaluation is retrospective, not a reconstruction of historical submissions. Current scopes, current publisher abstracts and undated imported aggregate MSC counts remain. Those aggregates have no document lineage, so we cannot guarantee they exclude the evaluated works. The new individual reference records are excluded by identity, but the entire catalog is not proven free of historical label information.

An accepted journal is one observed destination. Its inclusion does not imply future acceptance; its omission does not imply every recommended alternative is inappropriate. Public editorial guidance is useful evidence, but it is **not an independent manuscript–journal suitability judgment**. No unlabeled journal was converted into a negative training example.

## Implementation and validation

- Journal-wide `scope_breadth` is kept separate from field-local `audience_breadth`; technical level and audience remain unknown unless independently supported.
- Dated `editorial_evidence` survives import/export and reaches both MSC and lexical candidate routes. Strict historical cutoffs remove unavailable policy evidence and scope classifications.
- Representative articles retain author and license attribution through retrieval and report output.
- The complete demo2 suite passed: **70 tests**. This includes rights/provenance checks, target-version exclusion, taxonomy validation, both candidate routes and policy-date filtering.
- A real CLI import produced a 1,516-journal, 223-article SQLite catalog, and the offline example manuscript completed end to end. The offline run checks integration only.

Reproduce all eight runs from `demo2`, without network or model access:

```sh
python scripts/benchmark_public_evidence.py --output-dir /path/to/a/new-run
```

The command writes the merged catalog, coverage audit, frozen input datasets, predictions, candidate evidence and manifests. Existing output directories are refused. The input additions and ranking weights are fixed; no fitting or benchmark-guided weight selection occurs.

## Next online-only improvement

Expand across probability, analysis, computational mathematics and optimization venues using the same per-journal/year collection rules, rather than selecting neighbors of known misses. Acquire author-licensed introductions and main-result statements where available, with version and license tracking, so editorial criteria can be compared with the contribution itself. Keep a fresh journal/year-stratified evaluation set out of retrieval and training. Public scope policies should guide explanations and evidence requirements; they should not become synthetic expert labels or automatic boosts for broad journals.
