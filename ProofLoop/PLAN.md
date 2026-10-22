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

1. **Assign a bounded task.** The solver receives the exact target, the current obligation, relevant supporting claims, recent blockers, and a requested action: explore, prove, or seek a counterexample. It may request full saved artifacts by ID.
2. **Commit the result.** A round may add an obligation, a new argument, a complete candidate, or a structured blocker with evidence and a cheapest next test. The runner saves the useful result before another call. A repeated blocker without new evidence ends that route.
3. **Check a complete candidate.** The independent checker reviews the exact problem, proof, assumptions, and imported premises. It returns `pass`, `gap`, `counterexample`, or `uncertain` with a decisive finding. A non-pass finding can support one targeted repair round by default; exhausted repairs close that route.
4. **Redirect or stop.** A blocker may lead to a local repair, a smaller obligation, an assumption check, a different route, or a request for human input. A new route must name a different technique and a test that distinguishes it from prior routes.

With `--parallel-routes`, one concrete blocker can open a single two-route trial. The original route and one distinct alternative each receive one concurrent solver call. The coordinator reserves both calls from the global round cap, stores separate receipts, applies each result to the research graph, and selects an actionable route using checker-backed claims, a concrete next test, and recorded progress. It parks the other route with its artifacts intact, then can resume it if the selected route stops. Workers never edit `state.json`; only the coordinator merges results. A missing receipt is marked `execution_unknown` on resume rather than silently repeated. This mode is optional and does not launch a standing worker pool.

Intermediate reviews are optional and capped. The solver may request one for a pivotal claim; the round checkpoint can select the focused or latest unreviewed claim. Complete candidates always receive a checker call. A model checker pass is recorded as **model checked**, meaning no gap was found in an informal proof; it does not certify mathematical truth.

## Budgets and checkpoints

The ordinary configuration allows 8 solver rounds and 2 routes. A route has a 2-hour active-work clock, a 30-minute per-call timeout, and at most one repair after a rejected complete candidate. At half the route clock, the next solver prompt asks for the strongest result, obstruction, and cheapest next test. When the route clock expires, one short extension is allowed only for material progress and a concrete next test; otherwise the route closes. Zero disables the route or call time limit without disabling the other bounds. The optional two-route trial spends two solver rounds, one per route, even if a provider call fails; it adds no separate round allowance.

`--open-problem` uses a 10-round cap and a checkpoint after round 6. The checkpoint saves the current route and next test. It stops the run if the active route lacks material progress or a specific next test. Otherwise, it selects one unreviewed claim for an intermediate checker call when the configured review allowance permits, then passes the finding into the next solver assignment. The round cap remains a hard stop; ProofLoop has no “work until proven” mode.

These budgets control work, not proof validity. More rounds may uncover a new route or may only generate more unchecked claims. The recorded obligations, checker findings, and decision log are the basis for deciding whether a later run deserves a larger cap.

## Context and token use

Each model call starts with stable role instructions and the exact problem. The changing part contains compact indexes, a focused obligation, relevant argument text, and selected prior records. Full artifacts are loaded on request. This keeps unrelated prior turns out of the prompt and makes unchanged prefixes eligible for provider caching. Solver and checker reasoning effort can be set separately.

The runner records provider-reported fresh input, cached input, cache writes, reasoning output, and visible output. Cached input is a subset of input; reasoning is a subset of output. The system cannot force cache hits or turn input tokens into reasoning tokens. Solver-requested lemma checks use a soft output-token allocation and a call limit. The round-6 checkpoint can spend one remaining review slot outside that soft allocation; final-candidate checks always run.

## Durability and reuse

`state.json` is authoritative. Reports and bounded research summaries are derived from it; argument and response artifacts are immutable files. Before a provider call, the runner writes its intent. It saves a response receipt before applying the result, so resuming can apply a received answer once. An interrupted call with no receipt is marked `execution_unknown` and may need a new request; its previous cost can be unknown.

The optional shared file library makes results from earlier problems discoverable by lexical relevance. Each imported record retains its exact statement, assumptions, argument, dependencies, and provenance. It is a lead, even if previously model checked: the new proof must justify applicability. Retrieval is intentionally simple and can miss results that use different terminology.

## Boundary

The local CLI supports the OpenAI Responses API, Pi, and Codex CLI through a small backend interface. Python, Sage, and Lean computations are opt-in and sandboxed; their outputs are evidence, not a complete-proof certificate. There is no automatic literature search, database service, standing parallel solver swarm, or full formalization of a candidate proof. Human review remains the final authority for a mathematical claim.
