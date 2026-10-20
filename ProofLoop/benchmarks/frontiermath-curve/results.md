# FrontierMath public-sample comparison — 20 October 2026

Problem: count projective points on \(x^3y+y^3z+z^3x=0\) over \(\mathbb F_{5^{18}}\), the published [Epoch AI Tier 1 sample](https://epoch.ai/frontiermath/tiers-1-4/benchmark-problems). Epoch's answer is **3,814,708,984,376**. The answer key was kept out of all model prompts. One fresh run per arm; `gpt-6-sol`, high reasoning for primary solving; 480-second wall cap. See [protocol.md](protocol.md) and [summary.json](summary.json) for the exact setup and data.

| Arm | Result | Wall time | Calls | Fresh input | Cached input | Reasoning output | Other output | Reported total |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Plain Codex CLI | Correct answer, sound proof | 166.4 s | 1 | 13,666 | 12,032 | 2,142 | 1,317 | 29,157 |
| ProofLoop direct Pi | Correct answer, model checked, sound on manual audit | 84.8 s | 2 | 2,607 | 0 | 4,713 | 998 | 8,318 |
| Xean | Correct answer, accepted proof, sound on manual audit | 436.9 s | 11 | 119,782 | 559,104 | 15,973 | 6,807 | 701,666 |

The reported total is fresh input + cached input + reasoning output + other output. It is a token count, **not a monetary price**. The CLI and Pi transports can account for caching differently. All 11 Xean calls had reported usage, so its total is complete at the level exposed by the providers.

Xean's split matters: its ten `gpt-6-sol` Pi calls account for **31,106** tokens (16,341 fresh input, no cache read, 10,176 reasoning, 4,589 other output). One `gpt-6-astra` Codex CLI source-review call at **max** reasoning accounts for **670,560** tokens (103,441 fresh input, 559,104 cached input, 5,797 reasoning, 2,218 other output), or 95.6% of Xean's reported total. Xean's primary solver work alone was therefore much closer to plain Codex than its full campaign total suggests. ProofLoop's checker used 1,265 input and 771 output tokens, including 655 reasoning tokens; its solver used 1,342 input and 4,940 output tokens.

## Proof audit

- **Plain Codex:** Its program for the small fields was executed after the run and printed \(N_1=6,N_2=26,N_3=126\). The smooth plane-quartic argument gives genus 3. Newton identities and the genus-three zeta functional equation then give \(L(T)=1+125T^6\) and \(N_{18}=5^{18}+6\cdot5^9+1\). The proof is sound given the standard curve zeta theorem.
- **ProofLoop:** It used an order-seven automorphism with three fixed coordinate points. The induced six-cycle on the six nontrivial cohomology characters forces a Frobenius polynomial \(X^6-c\), where \(|c|=125\). Counting \(\mathbb F_{5^6}\)-points modulo 7 selects \(c=-125\), yielding the right number. The smoothness check, automorphism weights, fixed points, Frobenius cycle and mod-7 arithmetic were checked manually. Its model checker passed this one candidate. A model pass is not formal verification.
- **Xean:** Its accepted candidate derives the same automorphism/Frobenius route with an additional genus-zero quotient and character argument. Its mathematical steps and final arithmetic check out on manual audit. A candidate containing the right answer was recorded before its source-review web activity.

## Interpretation and deviations

On this one case, ProofLoop used **71.5% fewer reported total tokens** and **49.0% less wall time** than plain Codex. It spent more reasoning output (4,713 versus 2,142), largely on developing its alternate proof and running a checker, while avoiding much of Codex CLI's input context. Against Xean's full campaign, ProofLoop used 98.8% fewer reported total tokens; that comparison is strongly affected by Xean's source-review backend and cache accounting. All three found valid proofs, so this case shows an efficiency difference, **not** a proof-quality win or evidence of improved open-conjecture solving.

The frozen protocol asked all arms to avoid web search. The Xean primary solver complied, but its built-in `gpt-6-astra` source-review call performed web searches for standard external premises despite `literature: false`; its call trace records those searches. The review did not search Epoch's answer page. This is a protocol deviation and a capability difference, so the three-arm totals are observational rather than a strictly controlled tool-matched experiment. Xean's pre-review candidate already had the published answer. None of the arms executed code during model solving; the evaluator ran plain Codex's supplied counting code afterward. The public sample may be memorized, and a single attempt gives no reliable success-rate estimate. This run did not exercise ProofLoop's retry, blocker, obligation, or optional computation paths because its first solver call completed the proof.

Artifacts: [plain proof](plain/proof.md), [ProofLoop report](proof-loop/run/report.md), [Xean export](xean-proof.txt), [token summary](summary.json), and [raw Xean status](xean-status.json).
