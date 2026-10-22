import json
import tempfile
import unittest
from pathlib import Path

from proof_loop.runner import Config, Runner


def solver_result(technique, status="progress", claim=None, reduction=False):
    research_claims = []
    if reduction:
        research_claims = [{"kind": "reduction", "statement": "A reusable exact criterion",
                            "assumptions": [], "depends_on": [], "argument": "Proof of the criterion."}]
    return {
        "status": status, "route_title": technique, "summary": "A bounded attempt.",
        "claims": [claim] if claim else [], "obligations": [], "focus_obligation_id": "",
        "request_artifact_ids": [],
        "blocker": {"obligation_id": "", "attempted_technique": technique,
                    "failure_point": "", "evidence": "", "affected_assumptions": [],
                    "next_test": "", "proposed_action": "none", "reason": ""},
        "candidate_proof": "", "obstruction": "The main target is open.",
        "next_test": "Try a different route.",
        "research": {"technique": technique, "difference_from_prior": "A different method.",
                     "discriminating_test": "Check a finite case.", "next_task": "explore",
                     "review_claim_id": "", "review_reason": "", "candidate_kind": "proof",
                     "outcomes": research_claims,
                     "experiment": {"tool": "", "purpose": "", "code": ""}},
    }


class ScriptBackend:
    def __init__(self, answers):
        self.answers = iter(answers)

    def call(self, role, problem, context, timeout_seconds):
        answer = next(self.answers)
        return answer, {name: 0 for name in ("input_tokens", "cached_tokens", "fresh_input_tokens",
                                             "cache_write_tokens", "output_tokens", "reasoning_tokens",
                                             "visible_output_tokens")}


class WorkflowTests(unittest.TestCase):
    def make_runner(self, directory, backend, **config_kwargs):
        root = Path(directory)
        problem = root / "problem.md"
        problem.write_text("Prove the exact target.", encoding="utf-8")
        config = Config(model="fake", route_hours=0, max_call_minutes=0,
                        max_rounds=3, max_routes=2, pivot_after=2, **config_kwargs)
        return Runner(problem, root / "run", config, backend)

    def test_two_low_yield_rounds_pivot_to_second_route(self):
        claims = [{"statement": f"Narrow case {i}", "assumptions": [], "depends_on": [],
                   "argument": f"Argument {i}"} for i in (1, 2)]
        backend = ScriptBackend([solver_result("induction", claim=claims[0]),
                                 solver_result("induction", claim=claims[1]),
                                 solver_result("counting", status="stalled")])
        with tempfile.TemporaryDirectory() as directory:
            state = self.make_runner(directory, backend).run()
            self.assertEqual(len(state["routes"]), 2)
            self.assertEqual(state["routes"][0]["low_progress_rounds"], 2)
            self.assertEqual(state["routes"][0]["status"], "stalled")
            self.assertTrue(any(item["action"] == "pivot_low_yield" for item in state["decisions"]))

    def test_reduction_resets_progress_gate(self):
        first_claim = {"statement": "A narrow base case", "assumptions": [], "depends_on": [],
                       "argument": "Proof of the base case."}
        backend = ScriptBackend([solver_result("induction", claim=first_claim),
                                 solver_result("induction", reduction=True)])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            problem = root / "problem.md"
            problem.write_text("Prove the exact target.", encoding="utf-8")
            config = Config(model="fake", route_hours=0, max_call_minutes=0,
                            max_rounds=2, max_routes=2, pivot_after=2)
            state = Runner(problem, root / "run", config, backend).run()
            self.assertEqual(len(state["routes"]), 1)
            self.assertEqual(state["routes"][0]["low_progress_rounds"], 0)
            self.assertFalse(any(item["action"] == "pivot_low_yield" for item in state["decisions"]))

    def test_second_argument_for_same_reduction_is_not_decisive(self):
        first = solver_result("induction", reduction=True)
        second = solver_result("induction", reduction=True)
        second["research"]["outcomes"][0]["argument"] = "A revised argument for the same criterion."
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            problem = root / "problem.md"
            problem.write_text("Prove the exact target.", encoding="utf-8")
            config = Config(model="fake", route_hours=0, max_call_minutes=0,
                            max_rounds=2, max_routes=1, pivot_after=2)
            state = Runner(problem, root / "run", config, ScriptBackend([first, second])).run()
            self.assertEqual(state["routes"][0]["low_progress_rounds"], 1)
            self.assertFalse(state["routes"][0]["last_decisive_progress"])

    def test_cache_prefix_does_not_change_with_obligation_index(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = self.make_runner(directory, ScriptBackend([]))
            route = runner._open_route()
            before = runner._solver_context(route)
            runner._ensure_obligation("A new subgoal", [], route["id"], [])
            after = runner._solver_context(route)
            self.assertEqual(before["stable_context"], after["stable_context"])
            self.assertNotEqual(before["working_context"]["obligation_index"],
                                after["working_context"]["obligation_index"])

    def test_matching_experiment_is_executed_and_saved(self):
        first = solver_result("finite graph check")
        first["research"]["experiment"] = {
            "tool": "matching", "purpose": "Check a proposed finite obstruction",
            "code": json.dumps({"instances": [{"name": "obstruction", "left": ["a", "b"],
                                             "right": ["x"], "edges": [["a", "x"], ["b", "x"]]}]}),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            problem = root / "problem.md"
            problem.write_text("Check a general finite matching claim.", encoding="utf-8")
            config = Config(model="fake", route_hours=0, max_call_minutes=0,
                            max_rounds=2, max_routes=1, pivot_after=2, tools="matching")
            backend = ScriptBackend([first, solver_result("finite graph check", status="stalled")])
            state = Runner(problem, root / "run", config, backend).run()
            self.assertEqual(state["experiments"][0]["status"], "completed")
            self.assertIn('"deficiency": 1', state["experiments"][0]["output"])
            self.assertTrue((root / "run/experiments/e1/source.json").is_file())


if __name__ == "__main__":
    unittest.main()
