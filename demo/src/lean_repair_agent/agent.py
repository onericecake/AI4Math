from __future__ import annotations

import re
from typing import Optional

from .errors import LeanErrorParser
from .llm import LanguageModel
from .prompts import (
    generation_prompt,
    raw_feedback_prompt,
    retry_prompt,
    structured_feedback_prompt,
)
from .types import (
    AttemptRecord,
    CompilerResult,
    ErrorCategory,
    FailureFeedback,
    FeedbackMode,
    LeanProblem,
    ModelResponse,
    SolveResult,
)


_FORBIDDEN = re.compile(r"\b(?:sorry|admit|axiom)\b", re.IGNORECASE)


class MathAgent:
    """Generate, verify, and repair a Lean proof for a bounded number of attempts."""

    def __init__(self, model: LanguageModel, compiler: object, max_attempts: int = 3) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self.model = model
        self.compiler = compiler
        self.max_attempts = max_attempts
        self.error_parser = LeanErrorParser()

    def solve(
        self,
        problem: LeanProblem,
        mode: FeedbackMode = FeedbackMode.STRUCTURED,
        initial_response: Optional[ModelResponse] = None,
    ) -> SolveResult:
        prompt = generation_prompt(problem)
        attempts = []
        limit = 1 if mode == FeedbackMode.SINGLE else self.max_attempts

        for attempt_number in range(1, limit + 1):
            if attempt_number == 1 and initial_response is not None:
                response = initial_response
            else:
                response = self.model.complete(prompt)
            proof = normalize_proof(response.text)
            source = problem.render(proof)

            if _FORBIDDEN.search(proof):
                compiler_result = CompilerResult(
                    success=False,
                    exit_code=2,
                    stdout="",
                    stderr="Generated proof contains a forbidden placeholder or axiom.",
                    duration_seconds=0.0,
                )
                feedback: Optional[FailureFeedback] = FailureFeedback(
                    category=ErrorCategory.FORBIDDEN_PLACEHOLDER,
                    message=compiler_result.stderr,
                )
            else:
                compiler_result = self.compiler.check(source)
                feedback = None
                if not compiler_result.success:
                    feedback = self.error_parser.parse(compiler_result, source)

            attempts.append(
                AttemptRecord(
                    attempt=attempt_number,
                    proof=proof,
                    prompt=prompt,
                    compiler=compiler_result,
                    usage=response.usage,
                    feedback=feedback,
                )
            )

            if compiler_result.success:
                return SolveResult(problem.id, mode, True, proof, attempts)
            if attempt_number == limit:
                break

            prompt = self._repair_prompt(mode, problem, proof, compiler_result, feedback)

        return SolveResult(problem.id, mode, False, None, attempts)

    @staticmethod
    def _repair_prompt(
        mode: FeedbackMode,
        problem: LeanProblem,
        proof: str,
        compiler: CompilerResult,
        feedback: Optional[FailureFeedback],
    ) -> str:
        if mode == FeedbackMode.RETRY:
            return retry_prompt(problem, proof)
        if mode == FeedbackMode.RAW:
            return raw_feedback_prompt(problem, proof, compiler.output)
        if mode == FeedbackMode.STRUCTURED:
            if feedback is None:
                raise RuntimeError("Structured repair requires parsed feedback")
            return structured_feedback_prompt(problem, proof, feedback)
        raise ValueError("Mode {0} does not support repair".format(mode.value))


def normalize_proof(text: str) -> str:
    """Remove common presentation wrappers without rewriting Lean code."""

    value = text.strip()
    fence = re.fullmatch(r"```(?:lean\d*|lean)?\s*\n?(.*?)```", value, re.I | re.S)
    if fence:
        value = fence.group(1).strip()
    if re.match(r"^by(?:\s|$)", value):
        value = re.sub(r"^by(?:\s*\n|\s+)", "", value, count=1).strip()
    return value
