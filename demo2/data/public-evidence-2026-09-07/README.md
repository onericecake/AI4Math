# Public journal evidence collected 2026-09-07

60 additional articles with publisher abstracts, 10 per journal: five from 2021 and five from 2024. 40 articles have usable publisher MSC codes. This adds 60 unique works to the original catalog (163 → 223 articles; 61 → 121 nonempty abstracts). No expert annotation or user data collection is required to use this batch.

The six journals were selected for accessible publisher content and contrasting scopes. This is a small convenience sample, not an estimate of journal subject frequencies. Three are categorized as generalist, two as specialist and one as multi-field, based on the cited public scopes. These categories are assistant interpretations of publisher guidance, not expert assessments of manuscripts.

## Files

- `catalog.additions.json`: importable article and journal updates, with collection provenance.
- `articles.json`: the same 60 records, with DOI, authors, abstracts, dates, licenses and source hashes.
- `journals.json`: six scope profiles and ten sourced policy statements. Technical level and field-local audience remain unknown.
- `manifest.json`: archive URLs, sampling rule, selected DOIs, temporal policy and quarantined classifications.

## Use the data

From `demo2`, using the existing CLI:

```sh
PYTHONPATH=src python -m journal_matcher catalog import-json \
  data/catalog.example.json data/public-evidence-2026-09-07/catalog.additions.json \
  --database data/journal_catalog.enriched.sqlite
PYTHONPATH=src python -m journal_matcher analyze /path/to/manuscript.tex \
  --catalog data/journal_catalog.enriched.sqlite --msc data/msc2020.json \
  --output-dir /path/to/new-report
```

The frozen example catalog and ranking defaults are unchanged. The [ablation report](../../benchmarks/public-evidence-2026-09-07/REPORT.md) includes a regression on the earlier benchmark; use this as an experimental corpus, not a demonstrated universal accuracy upgrade.

## Editorial sources

| Journal | Scope category (assistant coding) | Official source |
|---|---|---|
| Annales Henri Lebesgue | generalist | [Scope](https://annales.lebesgue.fr/index.php/AHL/about) |
| Annales de l'Institut Fourier | generalist | [Scope](https://aif.centre-mersenne.org/) |
| Algebraic Combinatorics | specialist | [Scope](https://alco.centre-mersenne.org/) |
| SIGMA. Symmetry, Integrability and Geometry: Methods and Applications | multi-field | [Scope](https://sigma-journal.com/about.html) |
| Journal de Théorie des Nombres de Bordeaux | specialist | [Scope](https://jtnb.centre-mersenne.org/) |
| Journal de l'École Polytechnique -- Mathématiques | generalist | [Scope](https://jep.centre-mersenne.org/) |

For example, [AHL explicitly emphasizes significance and clear exposition for a broad readership](https://annales.lebesgue.fr/index.php/AHL/about), while [Algebraic Combinatorics requires an interaction between algebra and combinatorics](https://alco.centre-mersenne.org/). [JEP referee guidance asks about clarity, originality and interest](https://jep.centre-mersenne.org/page/instructions-for-referees_en/). These give the model concrete editorial criteria, without claiming a reviewer has assessed the input paper.

## Rights, extraction and quality

Article abstracts are reproduced as publisher text, including English/French versions when displayed. Web extraction removes HTML and navigation and retains displayed mathematical notation; it can leave imperfect TeX typography. They are not AI-written summaries. Author credit and license URLs accompany every article and are preserved in representative-article JSON and report attribution.

ALCO, AHL, JEP and SIGMA articles are CC BY 4.0; AIF and JTNB article pages state CC BY-ND 4.0. See each record’s `license_source_url`, `license_url` and authors. AHL licensing is stated in its [FAQ](https://annales.lebesgue.fr/index.php/AHL/about/faq); SIGMA licensing is in its [journal policy](https://sigma-journal.com/about.html). Scope statements are short attributed paraphrases, not verbatim copies of the journal websites.

Publisher classifications are preserved in `publisher_msc_codes`; only codes present in the bundled MSC2020 taxonomy enter `msc_codes`. `14F05` (JEP 140) and `38A35` (JEP 252) are quarantined without guessing replacements. Publisher code ordering is retained but does not establish a primary/secondary distinction. Missing MSC codes on AHL and SIGMA pages remain missing.

Current metadata and policy observation dates are 2026-09-07, even for older articles. AHL article availability uses conservative year-end dates because those pages did not supply an exact publication date. All other pages supply online publication dates. This batch must not be backdated in historical evaluation.

## Article attribution and source index

| DOI | Authors | Title | License |
|---|---|---|
| [10.3842/sigma.2021.109](https://sigma-journal.com/2021/109/) | Lino Grama ^{a} and Ailton R. Oliveira ^{b} | Scalar Curvatures of Invariant Almost Hermitian Structures on Generalized Flag Manifolds | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) |
| [10.3842/sigma.2021.110](https://sigma-journal.com/2021/110/) | Satoru Urano | A Composite Order Generalization of Modular Moonshine | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) |
| [10.3842/sigma.2021.111](https://sigma-journal.com/2021/111/) | Mikhail D. Minin and Andrei G. Pronko | Boundary One-Point Function of the Rational Six-Vertex Model with Partial Domain Wall Boundary Conditions: Explicit Formulas and Scaling Properties | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) |
| [10.3842/sigma.2021.112](https://sigma-journal.com/2021/112/) | Nikolai Kitanine and Giridhar Kulkarni | Form Factors of the Heisenberg Spin Chain in the Thermodynamic Limit: Dealing with Complex Bethe Roots | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) |
| [10.3842/sigma.2021.113](https://sigma-journal.com/2021/113/) | Zhengye Zhou | Orthogonal Polynomial Stochastic Duality Functions for Multi-Species SEP(2j) and Multi-Species IRW | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) |
| [10.3842/sigma.2024.111](https://sigma-journal.com/2024/111/) | Hitoshi Fujioka | Harmonic Metrics for Higgs Bundles of Rank 3 in the Hitchin Section | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) |
| [10.3842/sigma.2024.112](https://sigma-journal.com/2024/112/) | Tom Bridgeland | Tau Functions from Joyce Structures | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) |
| [10.3842/sigma.2024.113](https://sigma-journal.com/2024/113/) | Rei Inoue ^{a}, Atsuo Kuniba ^{b}, Xiaoyue Sun ^{c}, Yuji Terashima ^{d} and Junya Yagi ^{e} | Solutions of Tetrahedron Equation from Quantum Cluster Algebra Associated with Symmetric Butterfly Quiver | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) |
| [10.3842/sigma.2024.114](https://sigma-journal.com/2024/114/) | Philip Arathoon ^{a} and Marine Fontaine ^{b} | Real Forms of Holomorphic Hamiltonian Systems | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) |
| [10.3842/sigma.2024.115](https://sigma-journal.com/2024/115/) | Wanxia Wang and Shilin Yang | On the Higher-Rank Askey-Wilson Algebras | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) |
| [10.5802/ahl.194](https://ahl.centre-mersenne.org/item/AHL_2024__7__69_0/) | Charles, Laurent | Landau levels on a compact manifold | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) |
| [10.5802/ahl.195](https://ahl.centre-mersenne.org/item/AHL_2024__7__123_0/) | Drewitz, Alexander; Heydenreich, Markus; Mailler, Cécile | Voronoi cells in random split trees | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) |
| [10.5802/ahl.196](https://ahl.centre-mersenne.org/item/AHL_2024__7__161_0/) | Mathieu, Pierre; Tokushige, Yuki | Besov spaces and random walks on a hyperbolic group: boundary traces and reflecting extensions of Dirichlet forms | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) |
| [10.5802/ahl.197](https://ahl.centre-mersenne.org/item/AHL_2024__7__1_0/) | Campana, Frédéric; Darondeau, Lionel; Demailly, Jean-Pierre; Rousseau, Erwan | On the existence of logarithmic and orbifold jet differentials | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) |
| [10.5802/ahl.198](https://ahl.centre-mersenne.org/item/AHL_2024__7__207_0/) | Aulicino, David; Benirschke, Frederik; Norton, Chaya | A Zero Lyapunov Exponent in Genus $3$ Implies the Eierlegende Wollmilchsau | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) |
| [10.5802/ahl.66](https://ahl.centre-mersenne.org/item/AHL_2021__4__1_0/) | Berestycki, Nathanaël; Cerf, Raphaël | The random walk penalised by its range in dimensions $d\ge 3$ | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) |
| [10.5802/ahl.67](https://ahl.centre-mersenne.org/item/AHL_2021__4__81_0/) | Guillarmou, Colin; Hilgert, Joachim; Weich, Tobias | High frequency limits for invariant Ruelle densities | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) |
| [10.5802/ahl.68](https://ahl.centre-mersenne.org/item/AHL_2021__4__121_0/) | Gusakova, Anna; Thäle, Christoph | The volume of simplices in high-dimensional Poisson–Delaunay tessellations | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) |
| [10.5802/ahl.69](https://ahl.centre-mersenne.org/item/AHL_2021__4__155_0/) | Cattaneo, Alberto; Contreras, Ivan | Split Canonical Relations | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) |
| [10.5802/ahl.70](https://ahl.centre-mersenne.org/item/AHL_2021__4__187_0/) | Athreya, Jayadev; Lalley, Steve; Sapir, Jenya; Wroten, Matthew | Local geometry of random geodesics on negatively curved surfaces | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) |
| [10.5802/aif.3348](https://aif.centre-mersenne.org/articles/10.5802/aif.3348/) | Lavy, Omer; Olivier, Baptiste | Fixed-point spectrum for group actions by affine isometries on $L_{p}$-spaces | [CC-BY-ND-4.0](https://creativecommons.org/licenses/by-nd/4.0/) |
| [10.5802/aif.3392](https://aif.centre-mersenne.org/articles/10.5802/aif.3392/) | Jha, Somnath; Majumdar, Dipramit; Shekhar, Sudhanshu | $p^r$-Selmer companion modular forms | [CC-BY-ND-4.0](https://creativecommons.org/licenses/by-nd/4.0/) |
| [10.5802/aif.3393](https://aif.centre-mersenne.org/articles/10.5802/aif.3393/) | Bertrand, Jérôme; Ketterer, Christian; Mondello, Ilaria; Richard, Thomas | Stratified spaces and synthetic Ricci curvature bounds | [CC-BY-ND-4.0](https://creativecommons.org/licenses/by-nd/4.0/) |
| [10.5802/aif.3399](https://aif.centre-mersenne.org/articles/10.5802/aif.3399/) | Paulsen, Matthias | On the rationality of quadric surface bundles | [CC-BY-ND-4.0](https://creativecommons.org/licenses/by-nd/4.0/) |
| [10.5802/aif.3402](https://aif.centre-mersenne.org/articles/10.5802/aif.3402/) | Nivoche, Stéphanie | Transcendental versions in ${{\protect \mathbb{C}}}^n$ of the Nagata conjecture | [CC-BY-ND-4.0](https://creativecommons.org/licenses/by-nd/4.0/) |
| [10.5802/aif.3573](https://aif.centre-mersenne.org/articles/10.5802/aif.3573/) | Sawahara, Masatomo | Cylinders in canonical del Pezzo fibrations | [CC-BY-ND-4.0](https://creativecommons.org/licenses/by-nd/4.0/) |
| [10.5802/aif.3575](https://aif.centre-mersenne.org/articles/10.5802/aif.3575/) | Randrianantoanina, Narcisse | Triple operator version of the Golden-Thompson inequality for traces on von Neumann algebras | [CC-BY-ND-4.0](https://creativecommons.org/licenses/by-nd/4.0/) |
| [10.5802/aif.3579](https://aif.centre-mersenne.org/articles/10.5802/aif.3579/) | Klimeš, Martin | Wild monodromy of the Fifth Painlevé equation and its action on wild character variety: an approach of confluence | [CC-BY-ND-4.0](https://creativecommons.org/licenses/by-nd/4.0/) |
| [10.5802/aif.3582](https://aif.centre-mersenne.org/articles/10.5802/aif.3582/) | Biswas, Kingshook | Circumcenter extension of Moebius maps to $\mathrm{CAT}(-1)$ spaces | [CC-BY-ND-4.0](https://creativecommons.org/licenses/by-nd/4.0/) |
| [10.5802/aif.3583](https://aif.centre-mersenne.org/articles/10.5802/aif.3583/) | Aranha, Dhyan; Pstrągowski, Piotr | The Intrinsic Normal Cone for Artin Stacks | [CC-BY-ND-4.0](https://creativecommons.org/licenses/by-nd/4.0/) |
| [10.5802/alco.149](https://alco.centre-mersenne.org/articles/10.5802/alco.149/) | Eberhard, Sean; Garzoni, Daniele | Random generation with cycle type restrictions | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) |
| [10.5802/alco.150](https://alco.centre-mersenne.org/articles/10.5802/alco.150/) | Paget, Rowena; Wildon, Mark | Plethysms of symmetric functions and representations of $\protect \mathrm{SL}_2({\protect \bf C})$ | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) |
| [10.5802/alco.151](https://alco.centre-mersenne.org/articles/10.5802/alco.151/) | Lutz, Bob | Higher discrete homotopy groups of graphs | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) |
| [10.5802/alco.152](https://alco.centre-mersenne.org/articles/10.5802/alco.152/) | Blume, Mark; Hille, Lutz | Quivers and moduli spaces of pointed curves of genus zero | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) |
| [10.5802/alco.153](https://alco.centre-mersenne.org/articles/10.5802/alco.153/) | Chan, Aaron; Wong, William | Irreducible representations of the symmetric groups from slash homologies of $p$-complexes | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) |
| [10.5802/alco.324](https://alco.centre-mersenne.org/articles/10.5802/alco.324/) | Iverson, Joseph W.; Mixon, Dustin G. | Doubly transitive lines II: Almost simple symmetries | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) |
| [10.5802/alco.325](https://alco.centre-mersenne.org/articles/10.5802/alco.325/) | Cooper, Susan M.; El Khoury, Sabine; Faridi, Sara; Mayes-Tang, Sarah; Morey, Susan; Şega, Liana M.; Spiroff, Sandra | Simplicial resolutions of powers of square-free monomial ideals | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) |
| [10.5802/alco.327](https://alco.centre-mersenne.org/articles/10.5802/alco.327/) | Ren, Yue | On intersections and stable intersections of tropical hypersurfaces | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) |
| [10.5802/alco.328](https://alco.centre-mersenne.org/articles/10.5802/alco.328/) | Wu, Kuang-Yu | Toric varieties with ample tangent bundle | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) |
| [10.5802/alco.329](https://alco.centre-mersenne.org/articles/10.5802/alco.329/) | Corteel, Sylvie; Josuat-Vergès, Matthieu; Vanden Wyngaerd, Anna | Combinatorics of the Delta conjecture at $q=-1$ | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) |
| [10.5802/jep.139](https://jep.centre-mersenne.org/articles/10.5802/jep.139/) | Serena Guarino Lo Bianco; Domenico Angelo La Manna; Bozhidar Velichkov | A two-phase problem with Robin conditions on the free boundary | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) |
| [10.5802/jep.140](https://jep.centre-mersenne.org/articles/10.5802/jep.140/) | Andrea D’Agnolo; Masaki Kashiwara | On a topological counterpart of regularization for holonomic $\protect \mathscr{D}$-modules | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) |
| [10.5802/jep.141](https://jep.centre-mersenne.org/articles/10.5802/jep.141/) | Daniel Álvarez-Gavela; Kiyoshi Igusa | A Legendrian Turaev torsion via generating families | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) |
| [10.5802/jep.142](https://jep.centre-mersenne.org/articles/10.5802/jep.142/) | Naruki Masuda; Hugh Thomas; Andy Tonks; Bruno Vallette | The diagonal of the associahedra | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) |
| [10.5802/jep.143](https://jep.centre-mersenne.org/articles/10.5802/jep.143/) | Carlos E. Arreche; Thomas Dreyfus; Julien Roques | Differential transcendence criteria for second-order linear difference equations and elliptic hypergeometric functions | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) |
| [10.5802/jep.249](https://jep.centre-mersenne.org/articles/10.5802/jep.249/) | Stéphane Fischler; Tanguy Rivoal | Values of $E$-functions are not Liouville numbers | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) |
| [10.5802/jep.250](https://jep.centre-mersenne.org/articles/10.5802/jep.250/) | Beniamin Bogosel; Dorin Bucur | On the polygonal Faber-Krahn inequality | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) |
| [10.5802/jep.251](https://jep.centre-mersenne.org/articles/10.5802/jep.251/) | Marta Pieropan; Damaris Schindler | Hyperbola method on toric varieties | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) |
| [10.5802/jep.252](https://jep.centre-mersenne.org/articles/10.5802/jep.252/) | Marie-Claude Arnaud; Jacques Fejoz | Invariant submanifolds of conformal symplectic dynamics | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) |
| [10.5802/jep.253](https://jep.centre-mersenne.org/articles/10.5802/jep.253/) | Ning Guo; Fei Liu | Purity and quasi-split torsors over Prüfer bases | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) |
| [10.5802/jtnb.1149](https://jtnb.centre-mersenne.org/articles/10.5802/jtnb.1149/) | Peng Gao; Liangyi Zhao | Moments and One level density of certain unitary families of Hecke $L$-functions | [CC-BY-ND-4.0](https://creativecommons.org/licenses/by-nd/4.0/) |
| [10.5802/jtnb.1150](https://jtnb.centre-mersenne.org/articles/10.5802/jtnb.1150/) | Rony A. Bitan; Ralf Köhl; Claudia Schoemann | The twisted forms of a semisimple group over an $\protect \mathbb{F}_q$-curve | [CC-BY-ND-4.0](https://creativecommons.org/licenses/by-nd/4.0/) |
| [10.5802/jtnb.1151](https://jtnb.centre-mersenne.org/articles/10.5802/jtnb.1151/) | Cody Gunton | Semistable abelian varieties and maximal torsion 1-crystalline submodules | [CC-BY-ND-4.0](https://creativecommons.org/licenses/by-nd/4.0/) |
| [10.5802/jtnb.1152](https://jtnb.centre-mersenne.org/articles/10.5802/jtnb.1152/) | Jyothsnaa Sivaraman | Primitive roots for Pjateckii-Šapiro primes | [CC-BY-ND-4.0](https://creativecommons.org/licenses/by-nd/4.0/) |
| [10.5802/jtnb.1153](https://jtnb.centre-mersenne.org/articles/10.5802/jtnb.1153/) | Alina Carmen Cojocaru; Nathan Jones | Degree bounds for projective division fields associated to elliptic modules with a trivial endomorphism ring | [CC-BY-ND-4.0](https://creativecommons.org/licenses/by-nd/4.0/) |
| [10.5802/jtnb.1272](https://jtnb.centre-mersenne.org/articles/10.5802/jtnb.1272/) | Andrés Sarrazola-Alzate | A Beilinson–Bernstein Theorem for Twisted Arithmetic Differential Operators on the Formal Flag Variety | [CC-BY-ND-4.0](https://creativecommons.org/licenses/by-nd/4.0/) |
| [10.5802/jtnb.1273](https://jtnb.centre-mersenne.org/articles/10.5802/jtnb.1273/) | Andrew Keisling; Dylan Pentland | Extensions of mod $p$ representations of division algebras | [CC-BY-ND-4.0](https://creativecommons.org/licenses/by-nd/4.0/) |
| [10.5802/jtnb.1274](https://jtnb.centre-mersenne.org/articles/10.5802/jtnb.1274/) | Alexandre Lartaux | Sur la fonction Delta de Hooley associée à des caractères | [CC-BY-ND-4.0](https://creativecommons.org/licenses/by-nd/4.0/) |
| [10.5802/jtnb.1275](https://jtnb.centre-mersenne.org/articles/10.5802/jtnb.1275/) | Alexander Gorodnik; Amos Nevo | On discrepancy, intrinsic Diophantine approximation, and spectral gaps | [CC-BY-ND-4.0](https://creativecommons.org/licenses/by-nd/4.0/) |
| [10.5802/jtnb.1276](https://jtnb.centre-mersenne.org/articles/10.5802/jtnb.1276/) | Éric Saias | Étude du graphe divisoriel 5 | [CC-BY-ND-4.0](https://creativecommons.org/licenses/by-nd/4.0/) |
