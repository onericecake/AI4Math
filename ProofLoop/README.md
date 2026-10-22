# ProofLoop

ProofLoop is a local agent for sustained work on mathematical problems. It asks a solver to pursue one proof route at a time, records exact obligations and partial arguments, and sends complete candidates to a separate model checker. Its purpose is to make each call build on recorded work and to give unsuccessful routes a clear reason to continue, change direction, or stop.

A checker pass is labeled **model checked**. It means the checker found no gap in an informal argument; it is not a formal proof certificate. Human mathematical review remains necessary.

## How the workflow runs

1. **Fix the target.** A Markdown problem file supplies the statement, definitions, permitted assumptions, and what would count as a solution. ProofLoop keeps that target unchanged. A weaker result is recorded as a partial result with its extra assumptions.
2. **Explore a route.** Each solver round either submits a complete candidate or records an exact subgoal, an argument attempt, a blocker, and a concrete next test. One route is active at a time. A new route must use a genuinely different technique.
3. **Reuse recorded work.** Obligations have IDs; different arguments for the same statement remain separate versions. Later calls receive a small index and the arguments relevant to the current obligation. Full saved artifacts can be requested when needed.
4. **Check selectively.** A complete candidate always gets an independent checker call. The solver may request review of a pivotal intermediate claim; the round-6 checkpoint can also select one. A gap or counterexample becomes a targeted repair or a route decision; a failed attempt alone does not disprove its statement.
5. **Stop with a usable record.** The run ends on a checked candidate, a budget or route limit, a lack of progress, or a request for human input. The report retains the strongest partial results and unresolved obligations.

The [plan](PLAN.md) describes the data and decision rules in more detail.

## Install

Python 3.9+ is required. For the OpenAI API backend:

```bash
cd ProofLoop
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
export OPENAI_API_KEY='your-key'
```

For `--backend codex`, install Bun and `@earendil-works/pi-ai`, sign in to Codex with ChatGPT, and set `PROOF_LOOP_PI_PACKAGE` to the installed package directory containing `dist/index.js`. Set `PROOF_LOOP_BUN` if Bun is not on `PATH`. The adapter reads `CODEX_ACCESS_TOKEN` or the normal Codex login file. If needed, set `PROOF_LOOP_PI_PROXY` to your proxy URL. `--backend codex-cli` instead invokes an installed `codex` CLI.

## Run

Start with a problem file such as [examples/problem.md](examples/problem.md):

```bash
proof-loop examples/problem.md \
  --output-dir runs/odd-sums \
  --backend api --model MODEL_ID
```

The ordinary budget is **8 solver rounds**, up to **2 routes**, a **2-hour route clock**, a **30-minute call timeout**, and **one repair round per route** after a rejected complete candidate. Change these independently with `--max-rounds`, `--max-routes`, `--route-hours`, `--max-call-minutes`, and `--max-repairs-per-route`.

For a difficult open problem, write its exact statement in your own Markdown file and add `--open-problem`:

```bash
proof-loop my-problem.md \
  --output-dir runs/my-problem \
  --backend codex --model MODEL_ID \
  --open-problem
```

This mode caps the run at **10 solver rounds**. After round 6, ProofLoop records a decision and continues only when the active route made material progress and has a specific next test. If an unreviewed claim and intermediate-review capacity are available, it checks one claim before round 7 and gives the finding to the solver. This checkpoint check can add model cost even when the usual soft review budget is exhausted. Set `--max-lemma-checks 0` to omit intermediate model reviews. A higher explicit `--max-rounds` cap should be chosen only after inspecting the checkpoint and its remaining obligation.

Set `--route-hours 0 --max-call-minutes 0` to remove the route and per-call timeouts; round, route, and repair limits still apply. The caller must also avoid setting an external wall timeout.

## Saved work and resuming

Each output directory contains:

| File | Purpose |
| --- | --- |
| `state.json` | Authoritative routes, obligations, claims, decisions, call receipts, findings, and token usage. |
| `report.md` | Readable run summary, including the round checkpoint and remaining blockers. |
| `research-state.md` and `research-state.json` | Short navigation summaries regenerated from state. |
| `artifacts/` | Immutable argument, candidate, and call artifacts. |

Use the same command with `--resume` after interruption. The problem text and settings must match the saved run. A received response is applied without repeating its model call. If a call was interrupted before its receipt was saved, it is marked `execution_unknown`; its token cost may be unavailable.

To share leads across different problems, give each run a separate output directory and pass the same `--library-dir runs/shared-library`. Imported statements retain their assumptions, argument, dependencies, and source. They remain leads until checked for the new problem.

## Cost and proof status

`state.json` reports fresh input, cached input, cache writes, visible output, and reasoning output where the backend supplies them. The runner puts stable instructions and the exact problem before changing context to make repeated input eligible for caching, but actual cache use depends on the provider. Missing usage is reported as unavailable.

Optional local computations are enabled with `--tools python`, `--tools sage`, or `--tools lean`. They run in an OS sandbox without network access and are saved as evidence. A successful computation or intermediate review does not solve the original target. ProofLoop does not automatically search the literature or formalize a complete proof.
