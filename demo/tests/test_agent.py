import unittest

from lean_repair_agent.agent import MathAgent, normalize_proof
from lean_repair_agent.types import (
    CompilerResult,
    ErrorCategory,
    FeedbackMode,
    LeanProblem,
    ModelResponse,
    TokenUsage,
)


class FakeModel:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.prompts = []

    def complete(self, prompt):
        self.prompts.append(prompt)
        return ModelResponse(next(self.responses), TokenUsage(10, 2, 12))


class FakeCompiler:
    def __init__(self, results):
        self.results = iter(results)
        self.sources = []

    def check(self, source):
        self.sources.append(source)
        return next(self.results)


def failed(stderr="Main.lean:4:2: error: unsolved goals\nn : ℕ\n⊢ n = n"):
    return CompilerResult(False, 1, "", stderr, 0.01)


def passed():
    return CompilerResult(True, 0, "", "", 0.01)


class AgentTests(unittest.TestCase):
    def test_structured_mode_repairs_with_classified_feedback(self):
        model = FakeModel(["simp?", "rfl"])
        compiler = FakeCompiler([failed(), passed()])
        agent = MathAgent(model, compiler, max_attempts=3)
        problem = LeanProblem("identity", "theorem identity (n : ℕ) : n = n")

        result = agent.solve(problem, FeedbackMode.STRUCTURED)

        self.assertTrue(result.solved)
        self.assertEqual(result.proof, "rfl")
        self.assertEqual(len(result.attempts), 2)
        self.assertEqual(result.attempts[0].feedback.category, ErrorCategory.UNSOLVED_GOALS)
        self.assertIn("Failure type: unsolved_goals", model.prompts[1])
        self.assertEqual(result.token_usage.total_tokens, 24)

    def test_retry_mode_does_not_leak_compiler_output(self):
        model = FakeModel(["exact bad", "rfl"])
        compiler = FakeCompiler([failed("SECRET COMPILER DETAIL"), passed()])
        result = MathAgent(model, compiler).solve(
            LeanProblem("p", "theorem p : True"), FeedbackMode.RETRY
        )

        self.assertTrue(result.solved)
        self.assertNotIn("SECRET COMPILER DETAIL", model.prompts[1])

    def test_single_mode_never_repairs(self):
        model = FakeModel(["exact bad", "unused"])
        compiler = FakeCompiler([failed()])
        result = MathAgent(model, compiler).solve(
            LeanProblem("p", "theorem p : True"), FeedbackMode.SINGLE
        )
        self.assertFalse(result.solved)
        self.assertEqual(len(result.attempts), 1)

    def test_forbidden_placeholder_is_rejected_before_compilation(self):
        model = FakeModel(["sorry"])
        compiler = FakeCompiler([])
        result = MathAgent(model, compiler, max_attempts=1).solve(
            LeanProblem("p", "theorem p : True"), FeedbackMode.STRUCTURED
        )
        self.assertFalse(result.solved)
        self.assertEqual(compiler.sources, [])
        self.assertEqual(
            result.attempts[0].feedback.category, ErrorCategory.FORBIDDEN_PLACEHOLDER
        )

    def test_normalize_proof_removes_fence_and_by(self):
        self.assertEqual(normalize_proof("```lean\nby\n  rfl\n```"), "rfl")
