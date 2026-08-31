import unittest

from lean_repair_agent.agent import MathAgent
from lean_repair_agent.evaluation import evaluate_modes, summarize
from lean_repair_agent.types import (
    AttemptRecord,
    CompilerResult,
    FeedbackMode,
    LeanProblem,
    ModelResponse,
    SolveResult,
    TokenUsage,
)


class FakeModel:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.prompts = []

    def complete(self, prompt):
        self.prompts.append(prompt)
        return ModelResponse(next(self.responses), TokenUsage(total_tokens=5))


class FakeCompiler:
    def __init__(self, successes):
        self.successes = iter(successes)

    def check(self, source):
        success = next(self.successes)
        return CompilerResult(
            success,
            0 if success else 1,
            "",
            "error: unsolved goals\n⊢ True" if not success else "",
            0.1,
        )


def attempt(number, success, tokens=5):
    return AttemptRecord(
        number,
        "rfl",
        "prompt",
        CompilerResult(success, 0 if success else 1, "", "", 0.1),
        TokenUsage(total_tokens=tokens),
    )


class EvaluationTests(unittest.TestCase):
    def test_modes_share_the_same_initial_generation(self):
        model = FakeModel(["exact bad", "trivial", "trivial"])
        compiler = FakeCompiler([False, True, False, True])
        agent = MathAgent(model, compiler, max_attempts=2)

        comparison = evaluate_modes(
            agent,
            [LeanProblem("p", "theorem p : True")],
            [FeedbackMode.RETRY, FeedbackMode.STRUCTURED],
        )

        retry_result = comparison[FeedbackMode.RETRY][0]
        structured_result = comparison[FeedbackMode.STRUCTURED][0]
        self.assertEqual(retry_result.attempts[0].proof, "exact bad")
        self.assertEqual(structured_result.attempts[0].proof, "exact bad")
        self.assertEqual(len(model.prompts), 3)
        self.assertTrue(retry_result.solved)
        self.assertTrue(structured_result.solved)

    def test_summary_computes_research_metrics(self):
        results = [
            SolveResult("a", FeedbackMode.STRUCTURED, True, "rfl", [attempt(1, True)]),
            SolveResult(
                "b",
                FeedbackMode.STRUCTURED,
                True,
                "rfl",
                [attempt(1, False), attempt(2, True)],
            ),
            SolveResult("c", FeedbackMode.STRUCTURED, False, None, [attempt(1, False)]),
        ]
        summary = summarize(results, FeedbackMode.STRUCTURED)
        self.assertEqual(summary.pass_at_1, 1 / 3)
        self.assertEqual(summary.pass_at_k, 2 / 3)
        self.assertEqual(summary.average_attempts_solved, 1.5)
        self.assertEqual(summary.total_tokens, 20)
