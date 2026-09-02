import unittest

from lean_repair_agent.errors import LeanErrorParser
from lean_repair_agent.types import CompilerResult, ErrorCategory


def result(message, timed_out=False):
    return CompilerResult(False, 1, "", message, 0.1, timed_out)


class ErrorParserTests(unittest.TestCase):
    def test_parses_unknown_identifier_and_location(self):
        feedback = LeanErrorParser().parse(
            result("/tmp/Main.lean:7:11: error: unknown identifier 'ringg'"),
            "\n".join("line" for _ in range(10)),
        )
        self.assertEqual(feedback.category, ErrorCategory.UNKNOWN_IDENTIFIER)
        self.assertEqual(feedback.line, 7)
        self.assertEqual(feedback.column, 11)
        self.assertIn("   7 | line", feedback.source_excerpt)

    def test_parses_goal(self):
        feedback = LeanErrorParser().parse(result("error: unsolved goals\nx : ℝ\n⊢ x = x"))
        self.assertEqual(feedback.category, ErrorCategory.UNSOLVED_GOALS)
        self.assertIn("⊢ x = x", feedback.goal)

    def test_parses_unknown_tactic_as_tactic_failure(self):
        feedback = LeanErrorParser().parse(
            result("Main.lean:4:3: error: unknown tactic\n⊢ True")
        )
        self.assertEqual(feedback.category, ErrorCategory.TACTIC_FAILURE)

    def test_includes_all_reported_goals(self):
        feedback = LeanErrorParser().parse(
            result(
                "error: unsolved goals\n"
                "case left\n"
                "⊢ p\n\n"
                "case right\n"
                "⊢ q"
            )
        )
        self.assertIn("⊢ p", feedback.goal)
        self.assertIn("⊢ q", feedback.goal)

    def test_timeout_wins_over_text(self):
        feedback = LeanErrorParser().parse(result("unknown identifier", timed_out=True))
        self.assertEqual(feedback.category, ErrorCategory.TIMEOUT)
