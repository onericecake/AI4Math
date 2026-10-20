# ProofLoop

ProofLoop is a small, local workflow for exploring difficult mathematics. It gives a solver bounded proof routes, saves obligations and partial results, and sends complete candidate proofs to an independent model checker. A checker pass is labeled **model checked**; it is not a formal proof certificate.

The runner saves `state.json`, a readable `report.md`, compact research summaries, and immutable call and argument artifacts. You can resume interrupted work, set route and call limits, allow one targeted repair after a rejected proof, and optionally reuse leads from a local library across different problems. One route is active at a time.

See [PLAN.md](PLAN.md) for the design and [the FrontierMath case study](benchmarks/frontiermath-curve/results.md) for a three-arm comparison with plain Codex and Xean. That public sample shows a token and time reduction on one problem, not a success-rate estimate for open conjectures.

## Install

Python 3.9+ is required. For the separately billed OpenAI API backend:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
export OPENAI_API_KEY='your-key'
```

For the `codex` backend, install Bun and `@earendil-works/pi-ai`, sign in to Codex with ChatGPT, and set `PROOF_LOOP_PI_PACKAGE` to the installed package directory (the one containing `dist/index.js`). Set `PROOF_LOOP_BUN` if Bun is not on `PATH`. The adapter reads `CODEX_ACCESS_TOKEN` or the normal Codex login file. If needed, set `PROOF_LOOP_PI_PROXY` to your proxy URL. The `codex-cli` backend instead invokes an installed `codex` CLI.

## Run

Write a Markdown file with the exact problem, definitions, permitted assumptions, and completion criteria. See [examples/problem.md](examples/problem.md).

```bash
proof-loop examples/problem.md --output-dir runs/problem-1 \
  --backend codex --model gpt-6-sol \
  --solver-effort high --checker-effort high \
  --route-hours 2 --max-routes 2 --max-rounds 8 \
  --max-repairs-per-route 1
```

Resume the same run with the same options plus `--resume`. To reuse prior results across different problems, give each problem a separate output directory and pass the same `--library-dir runs/shared-library` to each run. Imported results are leads whose assumptions and arguments must still be checked.

Optional local computations require `--tools python`, `--tools sage`, or `--tools lean`. They run in an OS sandbox with no network access and are recorded as evidence, not proof. The macOS sandbox path has been exercised; Linux bubblewrap and Sage need validation on the target machine.

## Workflow and limits

- The solver may submit a complete proof immediately or record precise obligations, arguments, blockers, and a cheapest next test.
- The checker reviews each complete candidate. The default allows one targeted solver repair after a rejection, subject to the overall route, round, and wall limits.
- Partial lemmas, conditional theorems, reductions, and counterexamples retain their statements, assumptions, and dependencies. A failed attempt does not disprove a lemma.
- `state.json` records call status and reported fresh input, cached input, cache writes, output, and reasoning tokens. An interrupted call without a response receipt is marked `execution_unknown`; its earlier usage can be unavailable.
- A result marked `model_checked` still needs human mathematical review. There is no automatic literature search or complete-proof formalization.

Run the offline tests with:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -p test_proof_loop.py -v
```

`PROOF_LOOP_TEST_SANDBOX=1` enables the real OS sandbox test. `PROOF_LOOP_TEST_LEAN=1` and `PROOF_LOOP_LEAN` enable the installed Lean test.
