# Proof Loop: a small workflow for difficult mathematics

## Purpose

Proof Loop is a minimal harness for exploring a mathematical problem, recording useful progress, and subjecting complete candidate arguments to an independent model check. Its first aim is to reduce repeated work. Lower cost and better proofs are hypotheses to measure, not promises.

The design takes Xean's separation of exploration, durable mathematical notes, dependencies, and verification as inspiration. It takes Rethlas's generator/checker loop, targeted repair, and selective context as inspiration. The current runner uses one solver route at a time and a fresh checker call for each candidate. It omits parallel solvers, schedulers, databases, and formal proof translation.

Sources: [Xean philosophy](https://github.com/chaoxu/xean/blob/main/docs/philosophy.md), [Xean solver guide](https://github.com/chaoxu/xean/blob/main/docs/solver.md), [Rethlas](https://github.com/yexf308/Rethlas).

## Input and output

Input is one Markdown file containing the exact problem, definitions, permitted assumptions, and completion criteria. The file bytes are hashed at run start. The harness never silently changes the task during a run. An optional shared file library lets later problems retrieve relevant earlier claims and solutions.

Each run writes `state.json`, `report.md`, and immutable argument and response artifacts. The state records routes, exact obligations, versioned argument attempts, blockers, decisions, candidate proofs, checker findings, and token usage. A completed proof is labeled **model checked**. This means an independent model found no gap in the supplied argument; it is not a formal certificate or a guarantee of correctness. Computational examples are evidence, not proof. A future Lean integration could add a distinct **formally checked** label.

## Workflow

1. Fix the target from the problem file.
2. Open one route and ask the solver for a bounded round: a complete candidate proof, an exact obligation, a new argument version, or a structured blocker and next test.
3. Record obligations and arguments by ID. Reject another identical round when there is no new obligation, argument, requested artifact, evidence, changed candidate, or actionable checker finding.
4. Send a candidate proof to a fresh independent checker. The checker returns `pass`, `gap`, `counterexample`, or `uncertain`, with its first decisive finding. On a non-pass verdict, give the solver that specific finding for a targeted repair. By default, allow one repair solver round per route, then close the route if there is still no accepted proof. The separate repair limit is configurable and remains subject to the overall round and route clocks.
5. At the route clock boundary, verify a ready candidate, permit one short extension for a specific promising test, switch to a distinct route, or stop with the best partial result.

The checker receives the complete problem, the current proof, exact indexes, and referenced supporting arguments. Earlier drafts and solver self-assessments are not checker verdicts. A new argument for an existing statement creates a distinct version; a changed statement or assumption creates a new obligation. A targeted counterexample marks its exact obligation disputed for review. A failed approach does not disprove an obligation.

When a shared library is configured, each new run freezes a small set of relevant prior records at startup. Solver claims are published as unverified leads; complete checker-approved solutions are published as model-checked results. Each record carries assumptions, argument, dependencies, source problem, source run, and model. A later checker must assess any imported result used in the new proof, including whether its hypotheses apply. The shared status is provenance, not a pass for the new task. Version one uses lexical overlap for retrieval, with an import count and text cap; it can miss mathematically related work that uses different terms.

## Route clock

`route_hours = X` is configurable. At `X/2`, the next solver prompt requests a compact checkpoint: strongest claim, obstruction, and next test. At `X`, the route must make a decision. One extension of `extension_minutes` is permitted only when the route has a new claim or checker finding and a concrete next test. Without that, the route closes and the harness tries a new route if its route allowance remains. A model call is bounded by the remaining route time. Verification calls are separate from the exploration clock.

The clock measures active solver-call and local-computation wall time, so stopping and later restarting the process does not consume the route allowance. The round limit is a second guard against repeated or runaway calls. Default values are deliberately small for experimentation and can be raised for research problems.

## Token policy

The solver prompt puts stable role instructions and the exact problem first. It then supplies the selected obligation, relevant dependencies, recent arguments, requested full artifacts, and compact indexes. Eligible repeated input may be cached; the runner reports actual `cached_tokens`. It does not pad prompts solely to reach a cache threshold. The checker uses its own stable instructions and fresh call. Solving and checking reasoning effort are configurable separately. Calls are stateless and do not preserve hidden reasoning across rounds.

Cached input is a subset of input tokens. Reasoning is a subset of output tokens. The harness cannot convert one to the other. A higher reasoning effort may increase time and output cost. The measurement is total cost and wall time per independently accepted argument, alongside mathematical quality, not a high cache-hit or reasoning-token percentage alone. See [OpenAI prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching), [reasoning](https://developers.openai.com/api/docs/guides/reasoning), and [usage accounting](https://developers.openai.com/api/docs/guides/agents-api/observability).

## Current implementation boundary

The local Python CLI uses the OpenAI Responses API, Pi, or Codex CLI with structured outputs. It records call intent before a request and writes a response receipt before applying the result. On resume, it applies a saved receipt once, or marks an interrupted call with no receipt `execution_unknown`. The state checkpoint is authoritative; the report and bounded research summaries are regenerated from it.

The research extension adds explicit exploration/proof/counterexample assignments, labeled partial outcomes, and distinct-route proposals without a standing coordinator model. Optional pivotal-lemma checks have an output-token allocation target and a small call cap; complete candidates still receive mandatory review. Named standard theorems may be used when correctly stated and permitted. Computation is opt-in: Python, installed Sage, and installed Lean run through an OS sandbox with limits and recorded receipts. Their outputs are evidence, and successful execution does not certify the original target. There is no automatic literature search or complete-proof formalization. See the README for configuration and tested platform coverage.

## Evaluation

Compare against the same model working without this workflow on problems with assessable solutions, using comparable budgets and blind proof review. Record total input, cached input, output, reasoning tokens, wall time, repeated attempts at the same gap, and accepted proof rate. Measure the full run, including checker calls and unsuccessful routes. The existing successful first-attempt benchmarks predate the obligation workflow; the next useful comparison should include blocked routes and argument reuse.
