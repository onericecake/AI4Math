# ProofLoop design

## Goal

ProofLoop gives a model a small, durable workflow for difficult mathematics. The unit of progress is a **route with explicit obligations**, rather than another unconstrained conversation turn. A run should preserve useful partial results, avoid repeating the same failed step without new evidence, and spend checking effort where it can change the next decision.

The design draws on [Xean's durable research notes and verification](https://github.com/chaoxu/xean) and [Rethlas's generator and checker loop](https://github.com/yexf308/Rethlas). The implementation stays in one local application with one active solver route, a separate checker call, files for durable state, and a small provider interface. It has no standing swarm or scheduler.

## Research record

The original problem is fixed by its Markdown input file and hash. The saved state has these linked objects:

| Object | What it records |
| --- | --- |
| Route | Technique, status, current focus, summary, blocker, next test, and budget use. Competing routes stay separate. |
| Obligation | Exact subgoal, assumptions, dependencies, and the argument attempts that address it. |
| Claim | A versioned argument for a statement, including its assumptions, dependencies, and immutable artifact. |
| Finding | A checker verdict tied to a complete candidate or an intermediate claim. |
| Decision | Why work continued, repaired a step, changed routes, or stopped. |

An altered statement or hypothesis creates a new obligation. Multiple arguments for the same statement remain distinct. A conditional theorem or weaker target is a labeled partial result, never a silent change to the original problem. A counterexample disputes only the precise claim it refutes and any arguments depending on it.

## Decision loop

1. **Assign a bounded task.** The solver receives one question selected from the latest repair hint, next discriminating test, or open obligation. With no recorded obligation, its first task is to settle one decisive obstacle on a route toward the original target. The next question names an existing obligation or an obligation submitted in the response; changing scope creates a distinct target. Before dispatch, the coordinator retrieves up to two relevant claims from other routes with exact statements, assumptions, review status, and short full arguments, plus an applicable blocker. Similarity proposes leads but does not identify equivalent mathematical statements. The solver may request longer full saved artifacts by ID. The assignment and output allowance are journaled before each call, including parallel calls, so a recovered response is assessed against the question it actually received.
2. **Commit the result.** A round may add an obligation, a new argument, a complete candidate, or a structured blocker with evidence and a cheapest next test. The runner saves the useful result before another call. A repeated blocker without new evidence ends that route.
3. **Check a complete candidate.** The independent checker reviews the exact problem, proof, assumptions, and imported premises. It returns `pass`, `gap`, `counterexample`, or `uncertain` with a decisive finding. A non-pass finding can support one targeted repair round by default; exhausted repairs close that route.
4. **Redirect or stop.** A blocker may lead to a local repair, a smaller obligation, an assumption check, a different route, or a request for human input. A new route must name a different technique and a test that distinguishes it from prior routes.

The low-progress gate requires an explicit `progress` report linking evidence to the assigned target ID (`target` denotes the original problem). It cites a submitted claim by its zero-based position in `claims` followed by `research.outcomes`, or a completed experiment by ID, and explains what uncertainty the evidence resolves. A claim must supply a new statement/assumption pair across the whole run; a label such as `reduction`, a revised argument, or a different label alone earns no credit. A copied claim is logged in `reused_claim_ids` without new-discovery credit. Weaker assumptions or a stronger exact statement can create a new result. A computation requires a completed saved receipt and an interpretation; each experiment source is credited at most once per route. Queued, failed, skipped, or execution-unknown computations never reset the counter. The model reports whether a cited claim resolves the assigned obligation, partially advances it, or leaves a blocker. A reported resolution stays linked to the claim as a lead; it is not an automatic proof certificate. This deterministic gate checks references and novelty, leaving mathematical validity to review.

A new complete candidate earns credit pending mandatory checking. A first passed intermediate check earns credit only when its claim addresses the assigned target or has a recorded link to it. Requesting a review does not reset the counter; an admitted review may finish before a due pivot is applied. At the configured threshold (two rounds by default), the active route stalls and the coordinator tries a saved alternative or opens another route within the route cap. `--pivot-after 0` disables the threshold. Received legacy responses without progress metadata remain recoverable but do not earn claim or computation credit.

With `--parallel-routes`, one concrete blocker can open a single two-route trial. The original route and one distinct alternative each receive one concurrent solver call. The coordinator reserves both calls from the global round cap, stores separate assignments and receipts, applies each result to the research graph, records leads from the other route, and selects an actionable route using checker-backed claims, a reported resolution, credited progress linked to the assignment, and a concrete next test. The number of claims or obligations no longer breaks a tie. It parks the other route with its artifacts intact, then can resume it if the selected route stops. An exactly matching, previously model-checked claim on the other route can redirect an assignment before another solver call. Unverified results remain leads with assumptions to examine. Workers never edit `state.json`; only the coordinator merges results. A missing receipt is marked `execution_unknown` on resume rather than silently repeated. This mode is optional and does not launch a standing worker pool.

Intermediate reviews are optional and capped. The solver may request one for a pivotal claim; the round checkpoint can select the focused or latest unreviewed claim. Complete candidates always receive a checker call. A model checker pass is recorded as **model checked**, meaning no gap was found in an informal proof; it does not certify mathematical truth.

## Budgets and checkpoints

The ordinary configuration allows 8 solver rounds and 2 routes. A route has a 2-hour active-work clock, a 30-minute per-call timeout, and at most one repair after a rejected complete candidate. At half the route clock, the next solver prompt asks for the strongest result, obstruction, and cheapest next test. When the route clock expires, one short extension is allowed only for material progress and a concrete next test; otherwise the route closes. Zero disables the route or call time limit without disabling the other bounds. The optional two-route trial spends two solver rounds, one per route, even if a provider call fails; it adds no separate round allowance.

The initial solver allowance is 8,000 output tokens, including provider-counted reasoning. Credited progress plus a concrete next question on the same target doubles the next allowance, capped by `max_output_tokens` (25,000 by default). A new target or an unproductive round returns to the initial allowance. `--initial-round-tokens 0` uses the full configured allowance every time. The OpenAI API request carries the actual output cap. The Pi bridge passes maxTokens, but the installed Codex provider does not forward it upstream; Pi Codex and the CLI therefore use advisory prompt allowances. Budget-enforcement tests must inspect the provider request or measured usage, not only the Python-to-Pi payload. The existing time caps still apply. Prompts request useful partial results before the allowance ends; an incomplete structured response is a failed call, not evidence warranting an automatic larger retry. Mandatory final checks and optional review budgets remain separate from solver allowances.

`--open-problem` uses a 10-round cap and a checkpoint after round 6. The checkpoint saves the current route and next test. It stops the run if the active route lacks material progress or a specific next test. Otherwise, it selects one unreviewed claim for an intermediate checker call when the configured review allowance permits, then passes the finding into the next solver assignment. The round cap remains a hard stop; ProofLoop has no “work until proven” mode.

These budgets control work, not proof validity. More rounds may uncover a new route or may only generate more unchecked claims. The recorded obligations, checker findings, and decision log are the basis for deciding whether a later run deserves a larger cap.

## Context and token use

Each model call starts with stable role instructions and the exact problem. A route-frozen context follows; changing obligation indexes, the focused subgoal, and relevant argument text come afterward. Full artifacts are loaded on request. This keeps unrelated prior turns out of the prompt and makes unchanged prefixes eligible for provider caching. The Pi adapter requests short cache retention, while reported cache reads remain the only evidence of an actual hit. Solver and checker reasoning effort can be set separately.

The runner records provider-reported fresh input, cached input, cache writes, reasoning output, and visible output. Cached input is a subset of input; reasoning is a subset of output. The system cannot force cache hits or turn input tokens into reasoning tokens. Solver-requested lemma checks use a soft output-token allocation and a call limit. The round-6 checkpoint can spend one remaining review slot outside that soft allocation; final-candidate checks always run.

## Durability and reuse

`state.json` is authoritative. Reports and bounded research summaries are derived from it; argument and response artifacts are immutable files. Before a provider call, the runner writes its intent. It saves a response receipt before applying the result, so resuming can apply a received answer once. An interrupted call with no receipt is marked `execution_unknown` and may need a new request; its previous cost can be unknown.

The optional shared file library makes results from earlier problems discoverable by lexical relevance. Each imported record retains its exact statement, assumptions, argument, dependencies, and provenance. It is a lead, even if previously model checked: the new proof must justify applicability. Retrieval is intentionally simple and can miss results that use different terminology.

## Boundary

The local CLI supports the OpenAI Responses API, Pi, and Codex CLI through a small backend interface. The optional finite matching tool parses explicit bipartite graphs and returns a maximum matching certificate and, when needed, a Hall witness without executing supplied code. Python, Sage, and Lean computations are separately opt-in and sandboxed. Computation output is evidence, not a complete-proof certificate. There is no automatic literature search, database service, standing parallel solver swarm, or full formalization of a candidate proof. Human review remains the final authority for a mathematical claim.
