from __future__ import annotations

from typing import Dict

from .types import ErrorCategory, FailureFeedback, LeanProblem


_REPAIR_HINTS: Dict[ErrorCategory, str] = {
    ErrorCategory.SYNTAX_ERROR: "Repair Lean syntax first. Preserve the intended proof strategy when possible.",
    ErrorCategory.UNKNOWN_IDENTIFIER: "Replace the unknown name with an imported Mathlib declaration or a core tactic that is actually in scope.",
    ErrorCategory.TYPE_MISMATCH: "Inspect the expected and inferred types. Add an intermediate `have`, a coercion, or use a tactic whose conclusion exactly matches the goal.",
    ErrorCategory.UNSOLVED_GOALS: "Keep the successful prefix and close every remaining goal explicitly.",
    ErrorCategory.TACTIC_FAILURE: "Replace or prepare the failing tactic; establish its missing hypotheses before calling it.",
    ErrorCategory.TIMEOUT: "Use a shorter, more direct proof and avoid broad or expensive search tactics.",
    ErrorCategory.FORBIDDEN_PLACEHOLDER: "Produce a complete kernel-checkable proof without sorry, admit, or new axioms.",
    ErrorCategory.OTHER: "Use the diagnostic and current proof state to make the smallest plausible repair.",
}


def generation_prompt(problem: LeanProblem) -> str:
    return """Write a Lean 4 proof body for this theorem.

Rules:
- Return only tactics to place after `by`.
- Use the listed imports.
- Do not use `sorry`, `admit`, or introduce axioms.
- The result must compile as written.

Problem id: {problem_id}
Imports:
{imports}

Theorem:
{statement}
""".format(
        problem_id=problem.id,
        imports="\n".join(problem.imports),
        statement=problem.statement,
    )


def retry_prompt(problem: LeanProblem, previous_proof: str) -> str:
    return """The previous Lean 4 proof did not compile. Try a different proof.
Return only the new proof body, without `by`, Markdown, or prose.

Theorem:
{statement}

Previous proof:
{proof}
""".format(statement=problem.statement, proof=previous_proof)


def raw_feedback_prompt(problem: LeanProblem, previous_proof: str, raw_output: str) -> str:
    return """Repair this Lean 4 proof using the compiler output.
Return only the complete replacement proof body, without `by`, Markdown, or prose.

Theorem:
{statement}

Previous proof:
{proof}

Lean compiler output:
{output}
""".format(statement=problem.statement, proof=previous_proof, output=raw_output[-8000:])


def structured_feedback_prompt(
    problem: LeanProblem, previous_proof: str, feedback: FailureFeedback
) -> str:
    location = "unknown"
    if feedback.line is not None:
        location = "line {0}".format(feedback.line)
        if feedback.column is not None:
            location += ", column {0}".format(feedback.column)

    return """Repair only what is needed in this Lean 4 proof. Return the complete
replacement proof body and nothing else. Do not include `by`, Markdown, prose,
`sorry`, `admit`, or new axioms.

Theorem:
{statement}

Failure type: {category}
Location: {location}
Targeted advice: {hint}
Primary diagnostic:
{message}

Relevant goal:
{goal}

Failing source excerpt:
{excerpt}

Previous proof:
{proof}
""".format(
        statement=problem.statement,
        category=feedback.category.value,
        location=location,
        hint=_REPAIR_HINTS[feedback.category],
        message=feedback.message,
        goal=feedback.goal or "not reported",
        excerpt=feedback.source_excerpt or "not available",
        proof=previous_proof,
    )

