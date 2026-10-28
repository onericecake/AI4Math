import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from proof_loop.backend import OpenAIBackend
from proof_loop.pi_backend import PiBackend


class CallBudgetTests(unittest.TestCase):
    def test_api_uses_assignment_allowance_without_reducing_final_check(self):
        backend = object.__new__(OpenAIBackend)
        backend.model = "fake"
        backend.efforts = {"solver": "high", "checker": "high"}
        backend.max_output_tokens = 25000
        backend.client = Mock()
        backend.client.with_options.return_value = backend.client
        backend.client.responses.create.return_value = SimpleNamespace(status="completed", output_text="{}", usage=None)
        backend.call("solver", "A target", {"stable_context": {}, "working_context": {}, "solver_output_limit": 8000}, 60)
        self.assertEqual(backend.client.responses.create.call_args.kwargs["max_output_tokens"], 8000)
        backend.call("checker", "A target", {}, 60)
        self.assertEqual(backend.client.responses.create.call_args.kwargs["max_output_tokens"], 25000)
        backend.call("checker", "A target", {"review_output_limit": 2048}, 60)
        self.assertEqual(backend.client.responses.create.call_args.kwargs["max_output_tokens"], 2048)

    def test_pi_bridge_receives_requested_allowance_and_global_ceiling(self):
        # This tests the adapter boundary, not enforcement by Pi's Codex provider.
        backend = object.__new__(PiBackend)
        backend.model = "fake"
        backend.efforts = {"solver": "high", "checker": "high"}
        backend.max_output_tokens = 25000
        backend.package_path = Path("/unused/package")
        backend.bridge = Path("/unused/bridge")
        backend.bun = "unused-bun"
        process = SimpleNamespace(returncode=0, stdout=json.dumps({"result": {}}), stderr="")
        with patch("proof_loop.pi_backend._access_token", return_value="test-token"), patch("proof_loop.pi_backend.subprocess.run", return_value=process) as run:
            for limit, expected in ((8000, 8000), (16000, 16000), (32000, 25000)):
                backend.call("solver", "A target", {"stable_context": {}, "working_context": {}, "solver_output_limit": limit}, 60)
                self.assertEqual(json.loads(run.call_args.kwargs["input"])["max_output_tokens"], expected)
            backend.call("checker", "A target", {}, 60)
            self.assertEqual(json.loads(run.call_args.kwargs["input"])["max_output_tokens"], 25000)


if __name__ == "__main__":
    unittest.main()
