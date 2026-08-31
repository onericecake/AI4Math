import sys
import unittest

from lean_repair_agent.compiler import LeanCompiler


class CompilerTests(unittest.TestCase):
    def test_invokes_command_with_temporary_source(self):
        code = (
            "import pathlib, sys; "
            "text = pathlib.Path(sys.argv[1]).read_text(); "
            "print('verified' if 'theorem p' in text else 'missing'); "
            "raise SystemExit(0 if 'theorem p' in text else 1)"
        )
        compiler = LeanCompiler(command=[sys.executable, "-c", code])

        result = compiler.check("theorem p : True := by trivial")

        self.assertTrue(result.success)
        self.assertEqual(result.exit_code, 0)
        self.assertIn("verified", result.stdout)

    def test_captures_failed_verifier_diagnostics(self):
        code = "import sys; print('error: bad proof', file=sys.stderr); raise SystemExit(1)"
        compiler = LeanCompiler(command=[sys.executable, "-c", code])

        result = compiler.check("theorem p : True := by trivial")

        self.assertFalse(result.success)
        self.assertEqual(result.exit_code, 1)
        self.assertIn("bad proof", result.stderr)

