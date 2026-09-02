# Lean Repair Agent

A deliberately small AI4Math research agent that generates a Lean 4 proof,
checks it with Lean, and makes bounded repairs using verifier feedback.

The experiment isolates one question: **does structured Lean feedback improve
proof repair over naive retrying or raw compiler output?**

## What is implemented

- Four comparable modes: `single`, `retry`, `raw`, and `structured`.
- Eight failure categories: syntax error, unknown identifier, type mismatch,
  unsolved goals, tactic failure, timeout, forbidden placeholder, and fallback.
- Error-specific repair advice plus extracted location, goal, and source excerpt.
- A real `lean` / `lake env lean` subprocess verifier with a timeout.
- Pass@1, pass@K, attempts-per-solved-problem, and token-use metrics.
- JSON and JSONL inputs, JSON result artifacts, and deterministic offline tests.
- Fair mode comparison: every method branches from the same initial generated
  proof for each problem, so feedback strategy is the changed variable.

`max_attempts=3` means three total model generations: the initial proof plus at
most two repairs. This makes the reported result directly interpretable as
Pass@3.

### Proof output and diagnostics

The agent accepts model responses wrapped in Markdown fences or an optional
outer `by`, then normalizes the proof before rendering it into the theorem.
Shared leading indentation is removed while indentation inside tactic
branches and bullets is preserved, so generated top-level tactics should
start at column 0. Structured feedback reports the primary compiler message,
source location, all detected goals, and the relevant source excerpt.
Unknown tactics are classified as tactic failures so retries receive focused
repair guidance.

## Setup

You need Python 3.9+, an OpenAI API key, and a Lean 4 project with Mathlib.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
export OPENAI_API_KEY='...'
```

Install Lean through `elan`, create or clone a Mathlib project, and verify that
this works from the project directory:

```bash
lake env lean --version
```

## Solve one theorem

Problems are JSON objects with an id, Lean theorem statement, and imports:

```json
{
  "id": "two_mul_even",
  "imports": ["Mathlib"],
  "statement": "theorem two_mul_even (n : ℕ) : Even (2 * n)"
}
```

Run the structured agent:

```bash
lean-repair \
  --project-dir /path/to/mathlib-project \
  --model gpt-5.2 \
  --max-attempts 3 \
  solve examples/problem.json \
  --mode structured
```

If the project uses a nonstandard command, add
`--lean-command 'lake env lean'`.

## Run the comparison

Prepare a JSONL file with one problem object per line, then run:

```bash
lean-repair \
  --project-dir /path/to/mathlib-project \
  --model gpt-5.2 \
  evaluate examples/problems.jsonl \
  --modes single retry raw structured \
  --output-dir results
```

Each mode produces a result file containing its aggregate metrics and every
attempt's proof, verifier output, parsed error, duration, and token usage.

For an initial study, use 30–50 validation problems from one domain, keep the
model settings and verifier fixed, and compare the four modes. Do not tune on
the test set.

## Dataset templates

For declarations that need custom surrounding source, put `{{PROOF}}` exactly
where the indented proof body should go:

```json
{
  "id": "custom_context",
  "imports": ["Mathlib"],
  "statement": "namespace Demo\n\ntheorem custom_context : True := by\n{{PROOF}}\n\nend Demo"
}
```

## Run offline tests (no API key or Lean required)

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The 18 tests use fake model and compiler adapters, so they exercise the
complete repair loop—including proof normalization and structured error
parsing—without network access or a local Lean installation.
