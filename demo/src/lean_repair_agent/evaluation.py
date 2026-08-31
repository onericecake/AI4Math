from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

from .agent import MathAgent
from .prompts import generation_prompt
from .types import FeedbackMode, LeanProblem, SolveResult


@dataclass(frozen=True)
class EvaluationSummary:
    mode: FeedbackMode
    problems: int
    pass_at_1: float
    pass_at_k: float
    average_attempts_solved: float
    total_tokens: int

    def to_dict(self) -> Dict[str, object]:
        return {
            "mode": self.mode.value,
            "problems": self.problems,
            "pass_at_1": self.pass_at_1,
            "pass_at_k": self.pass_at_k,
            "average_attempts_solved": self.average_attempts_solved,
            "total_tokens": self.total_tokens,
        }


def load_jsonl(path: Path) -> List[LeanProblem]:
    problems = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                problems.append(LeanProblem.from_dict(json.loads(line)))
            except (KeyError, TypeError, json.JSONDecodeError) as error:
                raise ValueError("Invalid JSONL at line {0}: {1}".format(line_number, error)) from error
    return problems


def evaluate(agent: MathAgent, problems: Iterable[LeanProblem], mode: FeedbackMode) -> List[SolveResult]:
    return [agent.solve(problem, mode) for problem in problems]


def evaluate_modes(
    agent: MathAgent,
    problems: Iterable[LeanProblem],
    modes: Sequence[FeedbackMode],
) -> Dict[FeedbackMode, List[SolveResult]]:
    """Compare modes from identical initial generations for every problem."""

    results = {mode: [] for mode in modes}
    for problem in problems:
        initial_response = agent.model.complete(generation_prompt(problem))
        for mode in modes:
            results[mode].append(agent.solve(problem, mode, initial_response))
    return results


def summarize(results: Sequence[SolveResult], mode: FeedbackMode) -> EvaluationSummary:
    count = len(results)
    solved = [result for result in results if result.solved]
    first_pass = sum(1 for result in results if result.attempts and result.attempts[0].compiler.success)
    attempts = sum(len(result.attempts) for result in solved)
    return EvaluationSummary(
        mode=mode,
        problems=count,
        pass_at_1=(first_pass / count) if count else 0.0,
        pass_at_k=(len(solved) / count) if count else 0.0,
        average_attempts_solved=(attempts / len(solved)) if solved else 0.0,
        total_tokens=sum(result.token_usage.total_tokens for result in results),
    )


def write_results(path: Path, summary: EvaluationSummary, results: Sequence[SolveResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "summary": summary.to_dict(),
        "results": [result.to_dict() for result in results],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
