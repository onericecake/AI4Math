import unittest

from lean_repair_agent.types import LeanProblem


class ProblemTests(unittest.TestCase):
    def test_problem_renders_plain_statement(self):
        source = LeanProblem("p", "theorem p : True").render("trivial")
        self.assertEqual(source, "import Mathlib\n\ntheorem p : True := by\n  trivial\n")

    def test_problem_renders_template(self):
        source = LeanProblem("p", "theorem p : True := by\n{{PROOF}}").render("  trivial")
        self.assertTrue(source.endswith("theorem p : True := by\n  trivial\n"))
