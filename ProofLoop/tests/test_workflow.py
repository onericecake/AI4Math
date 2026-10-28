import json
import tempfile
import unittest
from pathlib import Path

from proof_loop.runner import Config, Runner


def solver_result(technique, status="progress", claim=None, reduction=False, linked=False):
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
        "progress": {"target_obligation_id": "target" if linked else "", "claim_index": 0 if linked else -1,
                     "experiment_id": "", "explanation": "This criterion reduces the assigned target to the remaining implication." if linked else ""},
        "research": {"technique": technique, "difference_from_prior": "A different method.",
                     "discriminating_test": "Check a finite case.", "next_task": "explore",
                     "review_claim_id": "", "review_reason": "", "candidate_kind": "proof",
                     "outcomes": research_claims,
                     "experiment": {"tool": "", "purpose": "", "code": ""}},
    }


class ScriptBackend:
    def __init__(self, answers):
        self.answers = iter(answers)
        self.contexts = []

    def call(self, role, problem, context, timeout_seconds):
        self.contexts.append((role, context))
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
                                 solver_result("induction", reduction=True, linked=True)])
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
        first = solver_result("induction", reduction=True, linked=True)
        second = solver_result("induction", reduction=True, linked=True)
        second["research"]["outcomes"][0]["argument"] = "A revised argument for the same criterion."
        second["research"]["outcomes"][0]["kind"] = "lemma"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            problem = root / "problem.md"
            problem.write_text("Prove the exact target.", encoding="utf-8")
            config = Config(model="fake", route_hours=0, max_call_minutes=0,
                            max_rounds=2, max_routes=1, pivot_after=2)
            state = Runner(problem, root / "run", config, ScriptBackend([first, second])).run()
            self.assertEqual(state["routes"][0]["low_progress_rounds"], 1)
            self.assertFalse(state["routes"][0]["last_decisive_progress"])

    def test_reduction_label_without_link_does_not_reset_gate(self):
        first = solver_result("induction", reduction=True)
        second = solver_result("induction", reduction=True)
        second["research"]["outcomes"][0]["statement"] = "Another detached reduction"
        with tempfile.TemporaryDirectory() as directory:
            runner = self.make_runner(directory, ScriptBackend([first, second]))
            # Stop after the second response; inspect the pivot without opening another route.
            route = runner._open_route()
            for response in (first, second):
                context = runner._solver_context(route)
                result = runner._call("solver", route, context, None)
                runner._apply_solver_result(route, result, False)
            self.assertEqual(route["low_progress_rounds"], 2)
            self.assertEqual(route["status"], "stalled")

    def test_new_focus_cannot_rebind_progress_to_an_unassigned_target(self):
        response = solver_result("induction", reduction=True, linked=True)
        response["obligations"] = [{"statement": "A different subgoal", "assumptions": [], "depends_on": []}]
        response["focus_obligation_id"] = "o1"
        response["progress"]["target_obligation_id"] = "o1"
        with tempfile.TemporaryDirectory() as directory:
            runner = self.make_runner(directory, ScriptBackend([response]))
            route = runner._open_route()
            context = runner._solver_context(route)
            result = runner._call("solver", route, context, None)
            runner._apply_solver_result(route, result, False)
            self.assertFalse(route["last_decisive_progress"])
            self.assertEqual(route["last_assignment"]["target_obligation_id"], "target")

    def test_claim_using_disputed_support_gets_no_progress_credit(self):
        response = solver_result("induction", claim={"statement": "A new consequence", "assumptions": [],
                                                    "depends_on": ["c1"], "argument": "It follows from c1."}, linked=True)
        with tempfile.TemporaryDirectory() as directory:
            runner = self.make_runner(directory, ScriptBackend([response]))
            route = runner._open_route()
            runner._add_claims([{"statement": "A false premise", "assumptions": [],
                                 "depends_on": [], "argument": "An invalid argument."}], route["id"])
            runner.state["obligations"][0]["status"] = "disputed"
            result = runner._call("solver", route, runner._solver_context(route), None)
            runner._apply_solver_result(route, result, False)
            self.assertFalse(route["last_decisive_progress"])

    def test_budget_grows_with_linked_progress_then_returns_to_initial(self):
        first = solver_result("induction", reduction=True, linked=True)
        second = solver_result("induction", reduction=True, linked=True)
        second["research"]["outcomes"][0]["statement"] = "A second useful reduction"
        narrow = [{"statement": f"Narrow case {i}", "assumptions": [], "depends_on": [],
                   "argument": f"Argument {i}"} for i in (1, 2)]
        backend = ScriptBackend([first, second, solver_result("induction", claim=narrow[0]),
                                 solver_result("induction", claim=narrow[1])])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            problem = root / "problem.md"
            problem.write_text("Prove the exact target.", encoding="utf-8")
            config = Config(model="fake", max_rounds=4, max_routes=1, route_hours=0, max_call_minutes=0)
            Runner(problem, root / "run", config, backend).run()
            self.assertEqual([c["solver_output_limit"] for role, c in backend.contexts], [8000, 16000, 25000, 8000])

    def test_new_assignment_gets_initial_budget(self):
        response = solver_result("induction", reduction=True, linked=True)
        response["obligations"] = [{"statement": "The remaining lemma", "assumptions": [], "depends_on": []}]
        response["focus_obligation_id"] = "o1"
        with tempfile.TemporaryDirectory() as directory:
            runner = self.make_runner(directory, ScriptBackend([response]))
            route = runner._open_route()
            result = runner._call("solver", route, runner._solver_context(route), None)
            runner._apply_solver_result(route, result, False)
            context = runner._solver_context(route)
            self.assertTrue(route["last_decisive_progress"])
            self.assertEqual(context["working_context"]["assignment"]["target_obligation_id"], "o1")
            self.assertEqual(context["solver_output_limit"], 8000)

    def test_received_result_keeps_assignment_on_resume(self):
        response = solver_result("induction", reduction=True, linked=True)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            problem = root / "problem.md"
            problem.write_text("Prove the exact target.", encoding="utf-8")
            config = Config(model="fake", max_rounds=1, max_routes=1, route_hours=0, max_call_minutes=0)
            runner = Runner(problem, root / "run", config, ScriptBackend([response]))
            route = runner._open_route()
            runner._call("solver", route, runner._solver_context(route), None)
            # Another committed change can alter the next context before this receipt is applied.
            runner._ensure_obligation("A new open obligation", [], route["id"], [])
            runner._save()
            backend = ScriptBackend([])
            resumed = Runner(problem, root / "run", config, backend, resume=True).run()
            self.assertEqual(backend.contexts, [])
            self.assertTrue(resumed["routes"][0]["last_decisive_progress"])
            self.assertEqual(resumed["routes"][0]["last_assignment"]["target_obligation_id"], "target")

    def test_parallel_trial_keeps_each_assignment_and_favors_linked_progress(self):
        class RoutingBackend(ScriptBackend):
            def call(self, role, problem, context, timeout_seconds):
                route_id = context["stable_context"]["route_id"]
                if route_id == 2:
                    result = solver_result("counting", reduction=True, linked=True)
                else:
                    first = not context["working_context"]["technique"]
                    claim = {"statement": "Narrow first case" if first else "Narrow second case", "assumptions": [],
                             "depends_on": [], "argument": "A narrow argument."}
                    result = solver_result("induction", claim=claim)
                    result["blocker"].update(failure_point="The induction step remains open.",
                                             next_test="Check whether the hypotheses imply the induction step.", proposed_action="repair")
                return result, {name: 0 for name in ("input_tokens", "cached_tokens", "fresh_input_tokens",
                                                    "cache_write_tokens", "output_tokens", "reasoning_tokens", "visible_output_tokens")}
        with tempfile.TemporaryDirectory() as directory:
            runner = self.make_runner(directory, RoutingBackend([]), parallel_routes=True)
            state = runner.run()
            self.assertEqual(state["parallel_trial"]["winner_route_id"], 2)
            self.assertTrue(all(c["assignment"] for c in state["calls"]))
            self.assertEqual(state["calls"][1]["assignment"]["output_tokens"], 8000)
            self.assertEqual(state["calls"][2]["assignment"]["output_tokens"], 8000)

    def test_changed_next_question_gets_its_own_obligation(self):
        first = solver_result("counting", reduction=True, linked=True)
        first["obligations"] = [{"statement": "Prove the finite case", "assumptions": ["size is four"], "depends_on": []}]
        first["next_target"] = {"id": "", "obligation_index": 0}
        first["next_test"] = "Prove the finite case under its exact assumptions."
        second = solver_result("counting", claim={"statement": "Prove the finite case", "assumptions": ["size is four"],
                                                  "depends_on": [], "argument": "A full argument for this case."}, linked=True)
        second["progress"].update(target_obligation_id="o1", resolution="resolved")
        second["next_target"] = {"id": "", "obligation_index": -1}
        with tempfile.TemporaryDirectory() as directory:
            runner = self.make_runner(directory, ScriptBackend([first, second]))
            route = runner._open_route()
            for answer in (first, second):
                context = runner._solver_context(route)
                result = runner._call("solver", route, context, None)
                runner._apply_solver_result(route, result, False)
            self.assertEqual(runner.state["calls"][1]["assignment"]["target_obligation_id"], "o1")
            self.assertEqual(runner.state["calls"][1]["assignment"]["output_tokens"], 8000)
            self.assertEqual(runner.state["obligations"][0]["reported_resolution_claim_ids"], ["c2"])
            self.assertEqual(runner._solver_context(route)["working_context"]["assignment"]["target_obligation_id"], "target")

    def test_shared_argument_is_retrieved_but_duplicate_gets_no_discovery_credit(self):
        statement = "Every graph of this type has the finite matching"
        first = solver_result("counting", claim={"statement": statement, "assumptions": ["finite graph"],
                                                  "depends_on": [], "argument": "First complete argument."}, linked=True)
        first["blocker"].update(failure_point="A separate finite graph matching extension remains open.",
                                 next_test="Check the finite graph matching extension.", proposed_action="repair")
        reused = solver_result("geometry")
        reused["reused_claim_ids"] = ["c1"]
        duplicate = solver_result("geometry", claim={"statement": statement, "assumptions": ["finite graph"],
                                                     "depends_on": [], "argument": "A second argument."}, linked=True)
        improved = solver_result("geometry", claim={"statement": statement, "assumptions": [],
                                                    "depends_on": [], "argument": "A proof without the extra assumption."}, linked=True)
        with tempfile.TemporaryDirectory() as directory:
            runner = self.make_runner(directory, ScriptBackend([first, reused, duplicate, improved]))
            route1 = runner._open_route()
            runner._apply_solver_result(route1, runner._call("solver", route1, runner._solver_context(route1), None), False)
            route2 = runner._open_route()
            route2["next_test"] = "Can the finite graph matching be proved again?"
            context = runner._solver_context(route2)
            self.assertEqual(context["working_context"]["shared_results"][0]["id"], "c1")
            self.assertEqual(context["working_context"]["shared_results"][0]["argument"], "First complete argument.")
            self.assertEqual(context["working_context"]["shared_blockers"][0]["route_id"], 1)
            runner._apply_solver_result(route2, runner._call("solver", route2, context, None), False)
            self.assertEqual(route2["last_reused_claim_ids"], ["c1"])
            self.assertFalse(route2["last_decisive_progress"])
            runner._apply_solver_result(route2, runner._call("solver", route2, runner._solver_context(route2), None), False)
            self.assertFalse(route2["last_decisive_progress"])
            self.assertEqual(runner.state["calls"][2]["repeated_claim_ids"], ["c2"])
            self.assertIn("solver calls repeating an exact statement and assumptions: 1", runner._report())
            runner._apply_solver_result(route2, runner._call("solver", route2, runner._solver_context(route2), None), False)
            self.assertTrue(route2["last_decisive_progress"])

    def test_exact_checked_claim_skips_repeated_assignment(self):
        first = solver_result("counting", claim={"statement": "A shared lemma", "assumptions": ["fixed hypotheses"],
                                                  "depends_on": [], "argument": "Checked argument."}, linked=True)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            problem = root / "problem.md"
            problem.write_text("Prove the exact target.", encoding="utf-8")
            backend = ScriptBackend([first, solver_result("geometry", status="stalled")])
            runner = Runner(problem, root / "run", Config(model="fake", route_hours=0, max_call_minutes=0,
                                                            max_rounds=2, max_routes=2), backend)
            route1 = runner._open_route()
            runner._apply_solver_result(route1, runner._call("solver", route1, runner._solver_context(route1), None), False)
            runner.state["claims"][0]["review_status"] = "model_checked"
            route1["status"] = "parked"
            route2 = runner._open_route()
            shared, _ = runner._ensure_obligation("A shared lemma", ["fixed hypotheses"], route2["id"], [])
            route2["next_obligation_id"] = shared["id"]
            route2["next_test"] = "Prove the shared lemma."
            state = runner.run()
            self.assertEqual(len([c for c in state["calls"] if c["role"] == "solver"]), 2)
            self.assertEqual(backend.contexts[1][1]["working_context"]["assignment"]["target_obligation_id"], "target")
            self.assertTrue(any(d["action"] == "reuse_checked_claim" for d in state["decisions"]))

    def test_parallel_selection_does_not_reward_claim_count(self):
        class RoutingBackend(ScriptBackend):
            def call(self, role, problem, context, timeout_seconds):
                route_id = context["stable_context"]["route_id"]
                if route_id == 1 and not context["working_context"]["technique"]:
                    result = solver_result("first", reduction=True, linked=True)
                    result["obligations"] = [{"statement": "Finite target", "assumptions": [], "depends_on": []}]
                    result["next_target"] = {"id": "", "obligation_index": 0}
                    result["blocker"].update(failure_point="Finite target remains open.", next_test="Resolve the finite target.", proposed_action="split")
                elif route_id == 1:
                    result = solver_result("first", claim={"statement": "Finite target", "assumptions": [],
                                                           "depends_on": [], "argument": "A complete finite argument."}, linked=True)
                    result["progress"].update(target_obligation_id="o1", resolution="resolved")
                else:
                    result = solver_result("second", linked=True)
                    result["claims"] = [{"statement": f"Unrelated case {i}", "assumptions": [],
                                         "depends_on": [], "argument": "A narrow argument."} for i in range(3)]
                    result["next_target"] = {"id": "o1", "obligation_index": -1}
                    result["next_test"] = "Resolve the finite target using a second technique."
                return result, {name: 0 for name in ("input_tokens", "cached_tokens", "fresh_input_tokens",
                                                    "cache_write_tokens", "output_tokens", "reasoning_tokens", "visible_output_tokens")}
        with tempfile.TemporaryDirectory() as directory:
            state = self.make_runner(directory, RoutingBackend([]), parallel_routes=True).run()
            self.assertEqual(state["parallel_trial"]["winner_route_id"], 1)
            self.assertIn("c2", state["parallel_trial"]["shared_result_ids"]["2"])

    def test_requested_review_does_not_reset_gate_but_relevant_pass_does(self):
        class UsageBackend(ScriptBackend):
            def call(self, *args):
                result, usage = super().call(*args)
                usage["output_tokens"] = 10000
                return result, usage
        first = solver_result("induction", reduction=True, linked=True)
        second = solver_result("induction", claim={"statement": "A narrow case", "assumptions": [],
                                                  "depends_on": [], "argument": "A narrow argument."})
        third = solver_result("induction")
        third["research"].update(review_claim_id="c1", review_reason="The remaining implication depends on this reduction.")
        checker = {"verdict": "pass", "finding": "The reduction is valid under its stated hypotheses.",
                   "repair_hint": "", "unverified_premises": [], "target_obligation_id": "", "counterexample_evidence": ""}
        with tempfile.TemporaryDirectory() as directory:
            runner = self.make_runner(directory, UsageBackend([first, second, third, checker]), exploration_share=0.5)
            route = runner._open_route()
            for _ in range(3):
                result = runner._call("solver", route, runner._solver_context(route), None)
                runner._apply_solver_result(route, result, False)
            self.assertEqual(route["low_progress_rounds"], 2)
            self.assertFalse(route["last_decisive_progress"])
            self.assertIsNotNone(runner.state["pending_review"])
            state = runner.run()
            self.assertEqual(state["routes"][0]["low_progress_rounds"], 0)
            self.assertTrue(state["routes"][0]["last_decisive_progress"])

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

    def test_experiment_needs_completed_receipt_and_interpretation_once(self):
        for failed in (False, True):
            with self.subTest(failed=failed), tempfile.TemporaryDirectory() as directory:
                first = solver_result("finite check")
                first["research"]["experiment"] = {"tool": "matching", "purpose": "Test the current obstruction",
                    "code": "invalid JSON" if failed else json.dumps({"instances": [{"name": "case", "left": ["a", "b"],
                        "right": ["x"], "edges": [["a", "x"], ["b", "x"]]}]})}
                second = solver_result("finite check")
                second["progress"] = {"target_obligation_id": "target", "claim_index": -1,
                    "experiment_id": "e1", "explanation": "The Hall witness refutes the finite assumption used by this route."}
                third = solver_result("finite check")
                third["progress"] = dict(second["progress"])
                root = Path(directory)
                problem = root / "problem.md"
                problem.write_text("Check the exact finite claim.", encoding="utf-8")
                config = Config(model="fake", max_rounds=3, max_routes=1, route_hours=0, max_call_minutes=0, tools="matching")
                backend = ScriptBackend([first, second, third])
                runner = Runner(problem, root / "run", config, backend)
                state = runner.run()
                self.assertFalse(backend.contexts[1][1]["working_context"]["last_progress_evidence"]["credited"])
                self.assertEqual(backend.contexts[1][1]["solver_output_limit"], 8000)
                credits = [d for d in state["decisions"] if d["action"] == "progress_credited"]
                self.assertEqual(len(credits), 0 if failed else 1)
                self.assertFalse(state["routes"][0]["last_decisive_progress"])
                if not failed:
                    self.assertEqual(backend.contexts[2][1]["solver_output_limit"], 16000)


if __name__ == "__main__":
    unittest.main()
