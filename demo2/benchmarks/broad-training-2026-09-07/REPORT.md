# Broad mathematical-field training experiment

The validation-selected model puts the observed publication journal in its top three for **595/991 test papers (60.0%)**, compared with **46.1%** for BM25 on the same training references.

This is a **50-journal title/abstract publication-venue benchmark**. It does not measure acceptance probability, expert suitability, full-registry hybrid accuracy or the LLM explanation stage. The original matching defaults are unchanged.

## Data and split

- Source: [OpenAlex public metadata](https://help.openalex.org/api/), collected by exact source ISSN for 2020–2025.
- Training: **8967** unique works from 2020–2023; validation: **979** from 2024; test: **991** from 2025.
- Duplicate records removed: **23**; records matching previous benchmark identities excluded: **13**; quarantined: **0**.
- Equal journal/year quotas with availability shortfalls; earliest eligible publication dates. Scope strata are analyst collection categories; OpenAlex topic subfields are machine labels.
- Metadata was observed in 2026. This publication-year split does not reconstruct historical submission-time inputs.

## Fixed learning curve

All tuning used 2024 validation macro-journal Hit@3. Each row’s selected model was locked before scoring any 2025 test paper. The largest requested 10,000-paper training point uses the actual available training count.

| Training papers | Classifier weight | Validation Hit@3 | Test Hit@3 | Test hits | Test macro-journal Hit@3 |
|---:|---:|---:|---:|---:|---:|
| 1000 | 1.00 | 51.4% | 46.4% | 460/991 | 46.2% |
| 5000 | 0.00 | 60.7% | 57.4% | 569/991 | 57.0% |
| 8967 | 0.75 | 62.5% | 60.0% | 595/991 | 59.6% |

Selected training size: **8967**, regularization alpha: **0.0001**, classifier weight: **0.75**. Weight zero uses TF-IDF journal centroids; weight one uses the linear classifier; intermediate weights fuse their ranks.

## Equal-corpus baselines

| Method | Test Hit@1 | Test Hit@3 | MRR |
|---|---:|---:|---:|
| Validation-selected model | 30.8% | 60.0% | 0.488 |
| BM25 maximum article | 22.8% | 46.1% | 0.393 |
| TF-IDF journal centroid | 29.2% | 57.4% | 0.471 |

Selected model minus BM25: **+13.9 percentage points**, paired work-bootstrap 95% interval **[+10.6, +17.0] points**. Model Hit@3 Wilson interval: **[57.0%, 63.0%]**. These intervals describe this convenience sample; they do not establish population-wide accuracy.

The BM25 baseline uses the existing BM25 implementation and maximum matching article per journal. It is a text-retrieval baseline, not the full MSC/LLM hybrid. All methods see the same selected training references and 50 candidate journals.

## Generalist and specialist strata

| Stratum | Test papers | Selected model Hit@3 | BM25 Hit@3 |
|---|---:|---:|---:|
| generalist | 253 | 17.0% | 19.0% |
| specialist or multifield | 738 | 74.8% | 55.4% |

These categories describe the collection design. They are not expert judgments of whether an individual manuscript deserves a broader venue.

## Field coverage and performance

| Collection stratum | Training papers | Test papers | Selected model Hit@3 | BM25 Hit@3 |
|---|---:|---:|---:|---:|
| algebra number theory | 858 | 120 | 70.0% | 37.5% |
| analysis pde | 882 | 100 | 73.0% | 47.0% |
| combinatorics | 465 | 80 | 77.5% | 61.3% |
| generalist | 2471 | 253 | 17.0% | 19.0% |
| geometry topology | 566 | 78 | 46.2% | 32.1% |
| mathematical physics | 688 | 60 | 56.7% | 50.0% |
| numerical applied | 851 | 80 | 90.0% | 70.0% |
| optimization | 803 | 80 | 92.5% | 83.8% |
| probability statistics | 1383 | 140 | 83.6% | 64.3% |

Per-paper machine-assigned topic subfield breakdowns are in [summary.json](runs/summary.json); these differ from journal-level collection strata.

## Per-journal audit

| Journal | Training papers | Test papers | Selected model Hit@3 |
|---|---:|---:|---:|
| Advances in Mathematics | 178 | 20 | 10.0% |
| Algebra & Number Theory | 218 | 20 | 70.0% |
| Algebraic Combinatorics | 213 | 20 | 80.0% |
| Annales Henri Lebesgue | 158 | 20 | 10.0% |
| Annales Henri Poincaré | 208 | 20 | 75.0% |
| Annales de l'Institut Fourier | 191 | 20 | 15.0% |
| Annals of Mathematics. Second Series | 126 | 20 | 40.0% |
| Calculus of Variations and Partial Differential Equations | 223 | 20 | 90.0% |
| Communications in Mathematical Physics | 240 | 20 | 45.0% |
| Communications in Partial Differential Equations | 200 | 20 | 85.0% |
| Compositio Mathematica | 232 | 20 | 50.0% |
| Discrete Mathematics | 133 | 20 | 80.0% |
| Duke Mathematical Journal | 229 | 20 | 10.0% |
| Electronic Journal of Probability | 240 | 20 | 75.0% |
| Electronic Journal of Statistics | 240 | 20 | 100.0% |
| Geometric and Functional Analysis. GAFA | 44 | 18 | 0.0% |
| Geometry & Topology | 208 | 20 | 45.0% |
| Inventiones Mathematicae | 96 | 20 | 10.0% |
| Journal de Théorie des Nombres de Bordeaux | 159 | 20 | 85.0% |
| Journal of Algebra | 178 | 20 | 60.0% |
| Journal of Algebraic Combinatorics | 60 | 20 | 70.0% |
| Journal of Combinatorial Theory. Series B | 59 | 20 | 80.0% |
| Journal of Differential Equations | 191 | 20 | 80.0% |
| Journal of Differential Geometry | 155 | 20 | 60.0% |
| Journal of Functional Analysis | 152 | 20 | 35.0% |
| Journal of Number Theory | 57 | 20 | 50.0% |
| Journal of Optimization Theory and Applications | 141 | 20 | 85.0% |
| Journal of Pure and Applied Algebra | 90 | 20 | 70.0% |
| Journal of Topology | 159 | 20 | 75.0% |
| Journal of the American Mathematical Society | 82 | 13 | 15.4% |
| Journal of the European Mathematical Society (JEMS) | 240 | 20 | 0.0% |
| Journal of the London Mathematical Society. Second Series | 240 | 20 | 20.0% |
| Journal of the Royal Statistical Society. Series B. Statistical Methodology | 222 | 20 | 95.0% |
| Linear Algebra and its Applications | 156 | 20 | 85.0% |
| Mathematical Programming. Series A. Series B | 185 | 20 | 95.0% |
| Mathematics of Operations Research | 237 | 20 | 95.0% |
| Mathematische Annalen | 219 | 20 | 15.0% |
| Numerische Mathematik | 131 | 20 | 90.0% |
| Probability Theory and Related Fields | 104 | 20 | 55.0% |
| Proceedings of the American Mathematical Society | 240 | 20 | 10.0% |
| SIAM Journal on Applied Mathematics | 240 | 20 | 85.0% |
| SIAM Journal on Numerical Analysis | 240 | 20 | 90.0% |
| SIAM Journal on Optimization | 240 | 20 | 95.0% |
| SIAM Journal on Scientific Computing | 240 | 20 | 95.0% |
| SIGMA. Symmetry, Integrability and Geometry: Methods and Applications | 240 | 20 | 50.0% |
| Stochastic Processes and their Applications | 107 | 20 | 75.0% |
| The Annals of Probability | 231 | 20 | 85.0% |
| The Annals of Statistics | 239 | 20 | 100.0% |
| The Journal of Fourier Analysis and Applications | 116 | 20 | 75.0% |
| Transactions of the American Mathematical Society | 240 | 20 | 15.0% |

## Every paper and its three recommendations

- [1000-paper model predictions](runs/test-predictions-1000.json): title, DOI/source, actual journal, actual rank and all three recommended journals.
- [5000-paper model predictions](runs/test-predictions-5000.json): title, DOI/source, actual journal, actual rank and all three recommended journals.
- [8967-paper model predictions](runs/test-predictions-8967.json): title, DOI/source, actual journal, actual rank and all three recommended journals.
- [BM25 predictions](runs/test-predictions-bm25.json).
- [Centroid predictions](runs/test-predictions-centroid.json).
- [Frozen split hashes](runs/manifest.json), [pre-training protocol](runs/protocol.json), [validation selection](runs/selection.json) and [implementation checksums](runs/implementation-sha256.json).

## Limits and next priorities

More data is useful here only to the extent demonstrated by the fixed learning curve. Publication metadata supplies a single observed venue per work; it cannot reveal all suitable alternatives or the journals that rejected a paper. Generalist journals remain difficult to distinguish from subject text alone.

Coverage depends on available abstracts and a fixed candidate list. Publisher formatting, language and publication-era effects may survive text cleaning. DOI/title/work/identical-abstract grouping does not guarantee detection of all rewritten versions, and authors can occur across splits. Future architecture or data changes need another holdout; the reported 2025 set has now been inspected.

Prioritize missing abstract coverage in sparse journals, richer pre-submission mathematical content and independently sourced editorial scope evidence. Keep such evidence separate from manuscript-specific expert labels. Do not replace the full-registry default based only on this restricted-candidate result.

See [the workflow and reproduction commands](../../BROAD_TRAINING.md). Raw caches, frozen text and model weights are local under `output/journal-training-2026-09-07/`; this report exports metrics, identifiers and predictions without bulk abstracts.
