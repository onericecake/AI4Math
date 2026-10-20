# Frozen FrontierMath public-sample case study

Source: Epoch AI, “FrontierMath Sample Problems,” Tier 1, “Counting nonzero solutions of homogeneous equations”: https://epoch.ai/frontiermath/tiers-1-4/benchmark-problems . The answer key is in `answer-key.md` and is absent from every model prompt.

All three arms receive the same equation and completion criteria, use `gpt-6-sol` at high reasoning for primary solving, and have a 480-second wall cap. No model may search the web or execute code. A reproducible exact-arithmetic algorithm in a proof is allowed; the evaluator may run it afterward. This is a local public-sample case study, not an official FrontierMath evaluation. The comparison does not exercise ProofLoop's optional computation adapter.

One fresh attempt per arm, run sequentially: plain Codex CLI in read-only ephemeral mode; ProofLoop via direct Pi with at most two routes, six rounds, and one local repair per route; Xean at its frozen source commit with a fresh campaign, literature disabled, and at most 20 provider calls. Record wall time and all model-reported token categories. Grade the exact number and derivation independently. A checker pass is not a proof certificate. An interrupted arm remains interrupted.

Limitations: this public sample could be memorized; one trial per arm; prompts, transport, and verification policy differ. Xean may invoke a separate source-review model despite `literature: false`; report its calls separately. CLI and Pi may account for prompt caching differently.
