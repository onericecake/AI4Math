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

    def test_timeout_wins_over_text(self):
        feedback = LeanErrorParser().parse(result("unknown identifier", timed_out=True))
        self.assertEqual(feedback.category, ErrorCategory.TIMEOUT)
