import json
import hashlib
import os
import shutil
import socket
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from proof_loop.runner import Config, Runner
from proof_loop.backend import OpenAIBackend
from proof_loop.codex_backend import codex_usage
from proof_loop.pi_backend import PiBackend, _pi_usage
from proof_loop.library import SharedLibrary
from proof_loop.experiments import execute


USAGE = {"input_tokens": 100, "cached_tokens": 40, "output_tokens": 50, "reasoning_tokens": 30}


def solver(status="progress", claims=None, proof="", next_test="Try a new lemma"):
    return {
        "status": status,
        "route_title": "Direct argument",
        "summary": "Checked the core case",
        "claims": claims or [],
        "candidate_proof": proof,
        "obstruction": "Remaining case",
        "next_test": next_test,
    }


def claim(statement="A useful lemma"):
    return {"statement": statement, "assumptions": [], "depends_on": [], "argument": "Direct derivation."}


def blocker(action="repair", evidence="A tested boundary case"):
    return {"obligation_id": "", "attempted_technique": "Direct argument", "failure_point": "Missing implication",
            "evidence": evidence, "affected_assumptions": [], "next_test": "Test the implication on the boundary case",
            "proposed_action": action, "reason": "This test separates the two possible routes"}


def research(**changes):
    return {"technique": "Direct induction", "difference_from_prior": "", "discriminating_test": "",
            "next_task": "explore", "review_claim_id": "", "review_reason": "", "candidate_kind": "proof",
            "outcomes": [], "experiment": {"tool": "", "code": "", "purpose": ""}, **changes}


class ScriptedBackend:
    def __init__(self, script):
        self.script = list(script)
        self.roles = []
        self.contexts = []

    def call(self, role, problem, context, timeout_seconds):
        self.roles.append(role)
        self.contexts.append(context)
        expected, output = self.script.pop(0)
        assert role == expected
        assert "problem" in problem.casefold()
        assert timeout_seconds > 0
        if isinstance(output, Exception):
            raise output
        return output, USAGE


class ProofLoopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.problem = self.root / "problem.md"
        self.problem.write_text("# problem\nProve P.\n", encoding="utf-8")
        self.output = self.root / "run"

    def test_candidate_checked_and_usage_recorded(self):
        backend = ScriptedBackend([
            ("solver", solver("candidate", proof="A complete argument.")),
            ("checker", {"verdict": "pass", "finding": "No gap found.", "repair_hint": "", "unverified_premises": []}),
        ])
        state = Runner(self.problem, self.output, Config(model="fake"), backend).run()
        self.assertEqual(state["status"], "model_checked")
        self.assertEqual(backend.roles, ["solver", "checker"])
        self.assertEqual(state["accepted_proof"], "A complete argument.")
        self.assertEqual(len(state["calls"]), 2)
        self.assertIn("Model checked proof", (self.output / "report.md").read_text())
        self.assertEqual(json.loads((self.output / "state.json").read_text())["calls"][0]["usage"]["cached_tokens"], 40)

    def test_no_progress_stops_without_repeating(self):
        backend = ScriptedBackend([("solver", solver())])
        state = Runner(self.problem, self.output, Config(model="fake", max_routes=1), backend).run()
        self.assertEqual(state["status"], "unsolved")
        self.assertEqual(state["rounds"], 1)
        self.assertEqual(state["routes"][0]["status"], "stalled")

    def test_unverified_premise_prevents_acceptance(self):
        backend = ScriptedBackend([
            ("solver", solver("candidate", proof="Apply an unproved theorem.")),
            ("checker", {"verdict": "pass", "finding": "Looks sound subject to T.", "repair_hint": "Prove T.", "unverified_premises": ["T"]}),
        ])
        state = Runner(self.problem, self.output, Config(model="fake", max_rounds=1), backend).run()
        self.assertEqual(state["status"], "round_limit")
        self.assertEqual(state["findings"][0]["verdict"], "uncertain")
        self.assertFalse(state["accepted_proof"])

    def test_one_repair_after_checker_gap_then_new_route(self):
        gap = {"verdict": "gap", "finding": "The key implication is unjustified.", "repair_hint": "Prove the implication.", "unverified_premises": []}
        backend = ScriptedBackend([
            ("solver", solver("candidate", proof="First incomplete proof.")),
            ("checker", gap),
            ("solver", solver("candidate", proof="Revised but incomplete proof.")),
            ("checker", gap),
            ("solver", solver("candidate", proof="A different complete proof.")),
            ("checker", {"verdict": "pass", "finding": "No gap found.", "repair_hint": "", "unverified_premises": []}),
        ])
        state = Runner(self.problem, self.output, Config(model="fake", max_routes=2, max_rounds=3), backend).run()
        self.assertEqual(state["status"], "model_checked")
        self.assertEqual([route["status"] for route in state["routes"]], ["repair_limit", "completed"])
        self.assertEqual([route["repair_rounds"] for route in state["routes"]], [1, 0])
        self.assertEqual(backend.contexts[2]["working_context"]["repairs_remaining"], 1)
        self.assertEqual(backend.contexts[4]["working_context"]["latest_checker_finding"], None)
        self.assertEqual(backend.contexts[4]["stable_context"]["prior_routes_to_avoid"][0]["checker_finding"], gap["finding"])

    def test_shared_obligation_keeps_distinct_argument_versions(self):
        first = solver(claims=[claim("Exact lemma")])
        first["blocker"] = blocker("switch_route")
        second = solver(claims=[{**claim("Exact lemma"), "argument": "A different derivation."}])
        second["focus_obligation_id"] = "o1"
        backend = ScriptedBackend([("solver", first), ("solver", second)])
        state = Runner(self.problem, self.output, Config(model="fake", max_rounds=2), backend).run()
        self.assertEqual(len(state["obligations"]), 1)
        self.assertEqual(state["obligations"][0]["attempt_ids"], ["c1", "c2"])
        self.assertEqual(state["routes"][1]["obligation_ids"], ["o1"])
        self.assertEqual(backend.contexts[1]["stable_context"]["shared_obligation_index"][0]["id"], "o1")
        self.assertNotEqual(state["claims"][0]["artifact_id"], state["claims"][1]["artifact_id"])

    def test_focused_context_omits_unrelated_argument_text(self):
        first = solver(claims=[claim("First exact lemma"), claim("Second exact lemma")])
        first["blocker"] = blocker()
        backend = ScriptedBackend([("solver", first), ("solver", solver("stalled"))])
        Runner(self.problem, self.output, Config(model="fake", max_routes=1), backend).run()
        context = backend.contexts[1]["working_context"]
        self.assertEqual(context["focus_obligation"]["id"], "o1")
        self.assertEqual([c["id"] for c in context["relevant_claims"]], ["c1"])
        self.assertNotIn("Second exact lemma", json.dumps(context["relevant_claims"]))

    def test_repeated_blocker_without_new_evidence_stops_route(self):
        first = solver()
        first["blocker"] = blocker()
        second = solver()
        second["blocker"] = blocker()
        backend = ScriptedBackend([("solver", first), ("solver", second)])
        state = Runner(self.problem, self.output, Config(model="fake", max_routes=1), backend).run()
        self.assertEqual(state["rounds"], 2)
        self.assertEqual(state["routes"][0]["status"], "stalled")
        self.assertEqual(state["decisions"][-1]["action"], "switch_route")

    def test_human_note_resumes_paused_route(self):
        first = solver()
        first["blocker"] = blocker("request_human_input")
        config = Config(model="fake", max_routes=1, max_rounds=2)
        state = Runner(self.problem, self.output, config, ScriptedBackend([("solver", first)])).run()
        self.assertEqual(state["status"], "needs_human_input")
        backend = ScriptedBackend([("solver", solver("candidate", proof="Complete argument with the supplied hint.")),
                                   ("checker", {"verdict": "pass", "finding": "No gap found.", "repair_hint": "", "unverified_premises": []})])
        runner = Runner(self.problem, self.output, config, backend, resume=True)
        runner.resume_with_human_note("Use the n=0 base case.")
        resumed = runner.run()
        self.assertEqual(resumed["status"], "model_checked")
        self.assertEqual(backend.contexts[0]["working_context"]["latest_human_note"], "Use the n=0 base case.")

    def test_received_solver_response_replays_without_model_call(self):
        config = Config(model="fake", max_routes=1, max_rounds=1)
        runner = Runner(self.problem, self.output, config, ScriptedBackend([("solver", solver(claims=[claim()]))]))
        route = runner._open_route()
        runner._call("solver", route, runner._solver_context(route), 10)
        saved = json.loads((self.output / "state.json").read_text())
        self.assertEqual(saved["calls"][0]["status"], "received")
        # Simulate a crash after receipt replacement but before checkpoint replacement.
        saved["calls"][0].update(status="pending", usage=None, seconds=0, receipt="")
        (self.output / "state.json").write_text(json.dumps(saved), encoding="utf-8")
        backend = ScriptedBackend([])
        state = Runner(self.problem, self.output, config, backend, resume=True).run()
        self.assertEqual(backend.roles, [])
        self.assertEqual(state["calls"][0]["status"], "applied")
        self.assertEqual(state["rounds"], 1)
        self.assertEqual(len(state["claims"]), 1)

    def test_received_checker_response_replays_without_model_call(self):
        config = Config(model="fake", max_rounds=1)
        check = {"verdict": "pass", "finding": "No gap found.", "repair_hint": "", "unverified_premises": []}
        runner = Runner(self.problem, self.output, config, ScriptedBackend([("checker", check)]))
        route = runner._open_route()
        proof = "A complete argument."
        runner.state["candidate_proof"] = proof
        runner.state["candidate_sha256"] = hashlib.sha256(proof.encode()).hexdigest()
        runner._save()
        runner._call("checker", route, {"candidate_proof": proof}, 10)
        backend = ScriptedBackend([])
        state = Runner(self.problem, self.output, config, backend, resume=True).run()
        self.assertEqual(backend.roles, [])
        self.assertEqual(state["status"], "model_checked")
        self.assertEqual(state["calls"][0]["status"], "applied")

    def test_interrupted_call_without_receipt_is_marked_unknown(self):
        config = Config(model="fake", max_routes=1)
        runner = Runner(self.problem, self.output, config, ScriptedBackend([]))
        route = runner._open_route()
        runner.state["calls"].append({"id": 1, "role": "solver", "route_id": route["id"],
                                      "status": "pending", "seconds": 0, "usage": None, "receipt": ""})
        runner._save()
        backend = ScriptedBackend([("solver", solver("stalled"))])
        state = Runner(self.problem, self.output, config, backend, resume=True).run()
        self.assertEqual([c["status"] for c in state["calls"]], ["execution_unknown", "applied"])
        self.assertEqual(backend.roles, ["solver"])

    def test_checker_counterexample_does_not_disprove_recorded_lemma(self):
        backend = ScriptedBackend([
            ("solver", solver("candidate", claims=[claim("Lemma A")], proof="An invalid use of Lemma A.")),
            ("checker", {"verdict": "counterexample", "finding": "The candidate fails at n=0.", "repair_hint": "Repair that case.", "unverified_premises": []}),
        ])
        state = Runner(self.problem, self.output, Config(model="fake", max_rounds=1), backend).run()
        self.assertEqual(state["obligations"][0]["status"], "supported")
        self.assertEqual(state["findings"][0]["verdict"], "counterexample")

    def test_precise_counterexample_disputes_only_named_obligation(self):
        backend = ScriptedBackend([
            ("solver", solver("candidate", claims=[claim("Lemma A"), claim("Lemma B")], proof="A candidate using Lemma A.")),
            ("checker", {"verdict": "counterexample", "finding": "Lemma A fails at n=0.",
                         "repair_hint": "Revise Lemma A.", "unverified_premises": [],
                         "target_obligation_id": "o1", "counterexample_evidence": "n=0"}),
        ])
        state = Runner(self.problem, self.output, Config(model="fake", max_rounds=1), backend).run()
        self.assertEqual([o["status"] for o in state["obligations"]], ["disputed", "supported"])
        self.assertEqual(state["findings"][0]["affected_route_ids"], [1])

    def test_disputed_argument_is_excluded_from_future_library_imports(self):
        library = self.root / "shared"
        backend = ScriptedBackend([
            ("solver", solver("candidate", claims=[claim("Prime lemma")], proof="Candidate using Prime lemma.")),
            ("checker", {"verdict": "counterexample", "finding": "Prime lemma fails in a boundary case.",
                         "repair_hint": "Revise it.", "unverified_premises": [],
                         "target_obligation_id": "o1", "counterexample_evidence": "Boundary case"}),
        ])
        state = Runner(self.problem, self.output, Config(model="fake", max_rounds=1), backend, library_dir=library).run()
        self.assertEqual(len(state["disputed_record_ids"]), 1)
        self.assertEqual(len(SharedLibrary(library).load()[0]), 1)
        other = "# Problem\nStudy the Prime lemma."
        records, _ = SharedLibrary(library).retrieve(other, hashlib.sha256(other.encode()).hexdigest(), 5)
        self.assertEqual(records, [])

    def test_old_argument_can_be_requested_by_artifact_id(self):
        old_text = "First derivation, with full details."
        def version(argument):
            return {**claim("Exact lemma"), "argument": argument}
        outputs = [solver(claims=[version(old_text)]), solver(claims=[version("Second derivation.")]),
                   solver(claims=[version("Third derivation.")])]
        for output in outputs:
            output["blocker"] = blocker()
        artifact_id = "claim:" + hashlib.sha256(old_text.encode()).hexdigest()
        request = solver()
        request["request_artifact_ids"] = [artifact_id]
        request["blocker"] = blocker()
        backend = ScriptedBackend([*(('solver', output) for output in outputs), ("solver", request), ("solver", solver("stalled"))])
        Runner(self.problem, self.output, Config(model="fake", max_routes=1), backend).run()
        self.assertNotIn(old_text, json.dumps(backend.contexts[3]["working_context"]["relevant_claims"]))
        self.assertEqual(backend.contexts[4]["working_context"]["requested_artifacts"], [{"id": artifact_id, "content": old_text}])

    def test_checker_failure_resumes_candidate_without_new_solver_call(self):
        first = ScriptedBackend([
            ("solver", solver("candidate", proof="Attempted proof.")),
            ("checker", RuntimeError("temporary service failure")),
        ])
        config = Config(model="fake")
        state = Runner(self.problem, self.output, config, first).run()
        self.assertEqual(state["status"], "blocked")
        second = ScriptedBackend([("checker", {"verdict": "pass", "finding": "No gap found.", "repair_hint": "", "unverified_premises": []})])
        resumed = Runner(self.problem, self.output, config, second, resume=True).run()
        self.assertEqual(resumed["status"], "model_checked")
        self.assertEqual(second.roles, ["checker"])

    def test_route_clock_one_extension_then_stop(self):
        clock = [0.0]

        class AdvancingBackend(ScriptedBackend):
            def call(self, role, problem, context, timeout_seconds):
                output = super().call(role, problem, context, timeout_seconds)
                clock[0] += 3601 if len(self.roles) == 1 else 1801
                return output

        backend = AdvancingBackend([
            ("solver", solver(claims=[claim()])),
            ("solver", solver(claims=[claim("Another lemma")])),
        ])
        config = Config(model="fake", route_hours=1, extension_minutes=30, max_call_minutes=120, max_routes=1)
        with patch("proof_loop.runner.time.monotonic", side_effect=lambda: clock[0]):
            state = Runner(self.problem, self.output, config, backend).run()
        self.assertEqual(state["status"], "unsolved")
        self.assertTrue(state["routes"][0]["extended"])
        self.assertEqual(state["routes"][0]["status"], "time_limit")
        self.assertEqual(state["rounds"], 2)

    def test_api_adapter_keeps_fixed_prefix_before_working_context(self):
        class FakeResponses:
            def __init__(self):
                self.request = None

            def create(self, **kwargs):
                self.request = kwargs
                return types.SimpleNamespace(
                    status="completed",
                    output_text=json.dumps(solver(claims=[claim()])),
                    usage=types.SimpleNamespace(
                        input_tokens=100,
                        input_tokens_details=types.SimpleNamespace(cached_tokens=40, cache_write_tokens=0),
                        output_tokens=50,
                        output_tokens_details=types.SimpleNamespace(reasoning_tokens=30),
                    ),
                )

        responses = FakeResponses()

        class FakeClient:
            def __init__(self, **kwargs):
                self.responses = responses

            def with_options(self, **kwargs):
                self.timeout = kwargs["timeout"]
                return self

        with patch.dict(sys.modules, {"openai": types.SimpleNamespace(OpenAI=FakeClient)}):
            backend = OpenAIBackend("fake", "high", "medium", 25000)
            result, usage = backend.call("solver", "A problem", {"stable_context": {"base": "fixed"}, "working_context": {"round": 2}}, 15)
        request = responses.request
        self.assertEqual(result["status"], "progress")
        self.assertEqual(request["input"][1]["content"], "Exact problem and completion criteria:\nA problem")
        self.assertIn('"base": "fixed"', request["input"][2]["content"])
        self.assertIn('"round": 2', request["input"][3]["content"])
        self.assertFalse(request["store"])
        self.assertEqual(usage["cached_tokens"], 40)

    def test_pi_usage_includes_cache_in_total_input(self):
        usage = _pi_usage({"input": 100, "cacheRead": 40, "cacheWrite": 5, "output": 50, "reasoning": 30})
        self.assertEqual(usage["input_tokens"], 145)
        self.assertEqual(usage["fresh_input_tokens"], 100)
        self.assertEqual(usage["cached_tokens"], 40)
        self.assertEqual(usage["visible_output_tokens"], 20)

    def test_pi_bridge_submits_structured_result_without_cli(self):
        bun = shutil.which("bun") or str(Path(__file__).resolve().parents[1] / "xean-benchmark-2026-09-29/bun-darwin-aarch64/bun")
        if not Path(bun).is_file():
            self.skipTest("Bun unavailable")
        package = self.root / "pi-stub"
        (package / "dist/providers").mkdir(parents=True)
        (package / "package.json").write_text('{"type":"module"}', encoding="utf-8")
        (package / "dist/index.js").write_text('''
export const envApiKeyAuth = () => ({});
export const createModels = () => ({
  setProvider() {},
  getModel(provider, name) { return { provider, id: name }; },
  async complete(model, context, options) {
    if (options.apiKey !== "test-token" || options.toolChoice !== "required" || !options.sessionId)
      throw new Error("bridge options missing");
    if (context.tools[0].name !== "submit_result" || !context.messages[0].content.includes("Prove P") ||
        !context.tools[0].parameters.required.includes("research"))
      throw new Error("bridge context missing");
    return { stopReason: "toolUse", usageReported: true, content: [{ type: "toolCall", name: "submit_result", arguments: {
      status: "progress", route_title: "Stub", summary: "ok", claims: [],
      candidate_proof: "", obstruction: "", next_test: "next"
    }}], usage: { input: 100, cacheRead: 40, cacheWrite: 0, output: 50, reasoning: 30 } };
  }
});
''', encoding="utf-8")
        (package / "dist/providers/openai-codex.js").write_text('export const openaiCodexProvider = () => ({});', encoding="utf-8")
        with patch.dict(os.environ, {"CODEX_ACCESS_TOKEN": "test-token"}):
            result, usage = PiBackend("fake", "high", "medium", 1000, package_path=package, bun_executable=bun).call(
                "solver", "Prove P.", {"stable_context": {}, "working_context": {}}, 10)
        self.assertEqual(result["status"], "progress")
        self.assertEqual(usage["input_tokens"], 140)

    def test_prior_solution_is_retrieved_with_assumptions_and_checked_again(self):
        self.problem.write_text("# Problem\nProve prime divisibility.\n\n## Permitted assumptions\nEuclid's lemma.\n\n## Completion criteria\nAll primes.\n", encoding="utf-8")
        library = self.root / "shared"
        first = ScriptedBackend([
            ("solver", solver("candidate", proof="An argument using Euclid's lemma.")),
            ("checker", {"verdict": "pass", "finding": "No gap found.", "repair_hint": "", "unverified_premises": []}),
        ])
        Runner(self.problem, self.output, Config(model="fake"), first, library_dir=library).run()
        records, rejected = SharedLibrary(library).load()
        self.assertEqual(rejected, 0)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["status"], "model_checked")
        self.assertEqual(records[0]["assumptions"], ["Euclid's lemma."])

        second_problem = self.root / "another.md"
        second_problem.write_text("# Problem\nProve a different prime divisibility statement.\n", encoding="utf-8")
        second = ScriptedBackend([
            ("solver", solver("candidate", proof="Apply the prior prime divisibility argument in this new case.")),
            ("checker", {"verdict": "uncertain", "finding": "New hypotheses were not checked.", "repair_hint": "Check the new case.", "unverified_premises": ["Applicability"]}),
        ])
        state = Runner(second_problem, self.root / "second-run", Config(model="fake", max_rounds=1), second, library_dir=library).run()
        self.assertEqual(state["status"], "round_limit")
        self.assertEqual(len(state["library_imports"]), 1)
        self.assertEqual(second.contexts[0]["stable_context"]["prior_problem_index"][0]["status"], "model_checked")
        self.assertEqual(second.contexts[0]["working_context"]["selected_prior_records"][0]["status"], "model_checked")
        self.assertEqual(second.contexts[1]["prior_problem_records"][0]["assumptions"], ["Euclid's lemma."])

    def test_unverified_claim_is_shared_as_lead(self):
        self.problem.write_text("# Problem\nStudy prime factorization.\n", encoding="utf-8")
        library = self.root / "shared"
        backend = ScriptedBackend([("solver", solver(claims=[claim("Prime factorization lemma")]))])
        state = Runner(self.problem, self.output, Config(model="fake", max_rounds=1), backend, library_dir=library).run()
        self.assertEqual(state["status"], "round_limit")
        records, _ = SharedLibrary(library).load()
        self.assertEqual(records[0]["status"], "unverified")
        self.assertEqual(records[0]["kind"], "claim")

        second_problem = self.root / "another.md"
        second_problem.write_text("# Problem\nExplore prime factorization in a new setting.\n", encoding="utf-8")
        resumed = Runner(second_problem, self.root / "other-run", Config(model="fake", max_rounds=1), ScriptedBackend([]), library_dir=library)
        self.assertEqual(resumed.state["library_imports"][0]["status"], "unverified")

    def test_library_snapshot_is_frozen_and_corrupt_records_are_skipped(self):
        self.problem.write_text("# Problem\nStudy prime factorization.\n", encoding="utf-8")
        library = self.root / "shared"
        first = ScriptedBackend([("solver", solver(claims=[claim("Prime factorization lemma")]))])
        Runner(self.problem, self.output, Config(model="fake", max_rounds=1), first, library_dir=library).run()
        second_problem = self.root / "another.md"
        second_problem.write_text("# Problem\nExplore prime factorization in a new setting.\n", encoding="utf-8")
        config = Config(model="fake", max_rounds=1)
        output = self.root / "second-run"
        initial = Runner(second_problem, output, config, ScriptedBackend([]), library_dir=library)
        self.assertEqual(len(initial.state["library_imports"]), 1)
        record_file = next((library / "records").glob("*.json"))
        damaged = json.loads(record_file.read_text(encoding="utf-8"))
        damaged["status"] = "model_checked"
        record_file.write_text(json.dumps(damaged), encoding="utf-8")
        resumed = Runner(second_problem, output, config, ScriptedBackend([]), resume=True, library_dir=library)
        self.assertEqual(len(resumed.state["library_imports"]), 1)
        third_problem = self.root / "third.md"
        third_problem.write_text("# Problem\nPrime factorization elsewhere.\n", encoding="utf-8")
        third = Runner(third_problem, self.root / "third-run", config, ScriptedBackend([]), library_dir=library)
        self.assertEqual(third.state["library_imports"], [])
        self.assertEqual(third.state["library_rejected_records"], 1)

    def test_old_checkpoint_without_library_fields_still_resumes(self):
        config = Config(model="fake", max_rounds=1)
        Runner(self.problem, self.output, config, ScriptedBackend([]))
        path = self.output / "state.json"
        old = json.loads(path.read_text(encoding="utf-8"))
        old["schema_version"] = 1
        old["config"].pop("library_limit")
        old["config"].pop("backend")
        old["config"].pop("max_repairs_per_route")
        for name in ("library_dir", "library_imports", "library_rejected_records", "published_record_ids", "library_error"):
            old.pop(name)
        path.write_text(json.dumps(old), encoding="utf-8")
        resumed = Runner(self.problem, self.output, config, ScriptedBackend([]), resume=True)
        self.assertEqual(resumed.state["schema_version"], 4)
        self.assertEqual(resumed.state["library_imports"], [])

    def test_codex_usage_breakdown_keeps_unreported_reasoning_unknown(self):
        event = json.dumps({"type": "turn.completed", "usage": {"input_tokens": 120, "cached_input_tokens": 80, "output_tokens": 30}})
        parsed = codex_usage(event)
        self.assertEqual(parsed["fresh_input_tokens"], 40)
        self.assertEqual(parsed["cached_tokens"], 80)
        self.assertIsNone(parsed["reasoning_tokens"])

    def test_partial_outcomes_and_counterexample_assignment_preserve_target(self):
        first = solver()
        first["research"] = research(next_task="counterexample", outcomes=[{
            **claim("P follows under assumption H"), "kind": "conditional_theorem", "assumptions": ["H"]}])
        backend = ScriptedBackend([("solver", first), ("solver", solver("stalled"))])
        state = Runner(self.problem, self.output, Config(model="fake", max_rounds=2), backend).run()
        self.assertEqual(backend.contexts[1]["working_context"]["assignment_kind"], "counterexample")
        self.assertIn("falsify", backend.contexts[1]["working_context"]["task"])
        self.assertEqual(state["claims"][0]["assumptions"], ["H"])
        self.assertEqual(state["claims"][0]["kind"], "conditional_theorem")
        self.assertFalse(state["accepted_proof"])
        self.assertEqual(state["problem_sha256"], hashlib.sha256(self.problem.read_bytes()).hexdigest())
        self.assertIn("conditional_theorem", (self.output / "research-state.md").read_text())

    def test_duplicate_route_is_rejected_before_candidate_check(self):
        first = solver(claims=[claim()])
        first["research"] = research()
        first["blocker"] = blocker("switch_route")
        second = solver("candidate", proof="Same route disguised as a different proof.")
        second["research"] = research(difference_from_prior="Renamed variables", discriminating_test="Same induction")
        backend = ScriptedBackend([("solver", first), ("solver", second)])
        state = Runner(self.problem, self.output, Config(model="fake", max_rounds=2), backend).run()
        self.assertEqual(state["routes"][1]["status"], "duplicate_route")
        self.assertFalse(state["accepted_proof"])
        self.assertEqual(backend.roles, ["solver", "solver"])

    def test_distinct_route_can_reuse_lemma_and_submit_complete_candidate(self):
        first = solver(claims=[claim()])
        first["research"] = research()
        first["blocker"] = blocker("switch_route")
        second = solver("candidate", proof="Complete proof using an invariant.")
        second["research"] = research(technique="Invariant argument", difference_from_prior="Avoids induction by classifying invariant values",
                                       discriminating_test="Check whether the invariant forces the missing boundary case")
        backend = ScriptedBackend([("solver", first), ("solver", second), ("checker", {
            "verdict": "pass", "finding": "Complete.", "repair_hint": "", "unverified_premises": []})])
        state = Runner(self.problem, self.output, Config(model="fake", max_rounds=2), backend).run()
        self.assertEqual(state["status"], "model_checked")
        self.assertEqual(state["routes"][1]["technique"], "Invariant argument")
        self.assertEqual(backend.contexts[1]["stable_context"]["shared_obligation_index"][0]["id"], "o1")

    def test_experiment_receipt_survives_crash_before_state_commit(self):
        config = Config(model="fake", tools="python", max_rounds=1)
        runner = Runner(self.problem, self.output, config, ScriptedBackend([]))
        route = runner._open_route()
        request = {**solver(), "research": research(experiment={"tool": "python", "code": "print(7)", "purpose": "Exact check"})}
        runner._accept_research(request, route)
        runner.state["experiments"][0]["status"] = "pending"
        runner.state["rounds"] = 1
        runner._save()
        directory = self.output / "experiments/e1"
        directory.mkdir(parents=True)
        (directory / "receipt.json").write_text(json.dumps({"status": "completed", "seconds": 0.5, "output": "7"}))
        with patch("proof_loop.runner.execute") as execution:
            state = Runner(self.problem, self.output, config, ScriptedBackend([]), resume=True).run()
            execution.assert_not_called()
        self.assertEqual(state["experiments"][0]["output"], "7")
        self.assertEqual(state["routes"][0]["elapsed_seconds"], 0.5)
        self.assertIn("result_artifact_id", state["experiments"][0])

    def test_pivotal_check_replays_without_using_candidate_repair_allowance(self):
        class ResearchBackend(ScriptedBackend):
            def call(self, *args):
                result, usage = super().call(*args)
                return result, {**usage, "output_tokens": 10000}

        first = solver(claims=[claim()])
        first["research"] = research()
        second = solver()
        second["research"] = research(review_claim_id="c1", review_reason="All later work depends on this lemma")
        config = Config(model="fake", max_rounds=2)
        backend = ResearchBackend([("solver", first), ("solver", second), ("checker", RuntimeError("interrupted"))])
        state = Runner(self.problem, self.output, config, backend).run()
        self.assertEqual(state["status"], "blocked")
        self.assertEqual(state["pending_review"]["claim_id"], "c1")
        resume_backend = ScriptedBackend([("checker", {"verdict": "pass", "finding": "Lemma checked under its hypotheses.",
                                                     "repair_hint": "", "unverified_premises": []})])
        resumed = Runner(self.problem, self.output, config, resume_backend, resume=True).run()
        self.assertEqual(resume_backend.roles, ["checker"])
        self.assertEqual(resumed["claims"][0]["review_status"], "model_checked")
        self.assertEqual(resumed["routes"][0]["repair_rounds"], 0)
        self.assertEqual(resumed["reviewed_claim_ids"], ["c1"])
        self.assertFalse(resumed["accepted_proof"])
        self.assertIsNone(resumed["pending_review"])

    def test_optional_check_is_deferred_when_exploration_budget_is_small(self):
        first = solver(claims=[claim()])
        first["research"] = research(review_claim_id="c1", review_reason="Pivotal claim")
        backend = ScriptedBackend([("solver", first)])
        state = Runner(self.problem, self.output, Config(model="fake", max_rounds=1), backend).run()
        self.assertIsNone(state["pending_review"])
        self.assertTrue(any(d["action"] == "defer_review" for d in state["decisions"]))
        self.assertEqual(backend.roles, ["solver"])

    def test_experiment_evidence_is_saved_retrieved_and_not_repeated(self):
        first = solver()
        first["research"] = research(next_task="counterexample", experiment={
            "tool": "python", "purpose": "Check the smallest possible witness", "code": "print(2**10)"})
        second = {**first, "status": "stalled"}
        backend = ScriptedBackend([("solver", first), ("solver", second)])
        config = Config(model="fake", tools="python", max_rounds=2)
        with patch("proof_loop.runner.execute", return_value={"status": "completed", "output": "1024", "seconds": 0.1}) as execution:
            state = Runner(self.problem, self.output, config, backend).run()
        self.assertEqual(execution.call_count, 1)
        self.assertEqual(len(state["experiments"]), 1)
        self.assertEqual(backend.contexts[1]["working_context"]["recent_experiments"][0]["output_preview"], "1024")
        self.assertFalse(state["accepted_proof"])
        resumed = Runner(self.problem, self.output, config, ScriptedBackend([]), resume=True).run()
        self.assertEqual(resumed["experiments"][0]["status"], "completed")

    def test_disabled_computation_and_unknown_execution_never_run_silently(self):
        result = solver()
        result["research"] = research(experiment={"tool": "python", "code": "print(1)", "purpose": "check"})
        with patch("proof_loop.runner.execute") as execution:
            state = Runner(self.problem, self.output, Config(model="fake"), ScriptedBackend([("solver", result)])).run()
            execution.assert_not_called()
        self.assertEqual(state["status"], "blocked")
        self.assertIn("disabled", state["error"])
        config = Config(model="fake", tools="python", max_rounds=1)
        other = self.root / "interrupted"
        runner = Runner(self.problem, other, config, ScriptedBackend([]))
        route = runner._open_route()
        runner._accept_research(result, route)
        runner.state["experiments"][0]["status"] = "pending"
        runner.state["rounds"] = 1
        runner._save()
        with patch("proof_loop.runner.execute") as execution:
            resumed = Runner(self.problem, other, config, ScriptedBackend([]), resume=True).run()
            execution.assert_not_called()
        self.assertEqual(resumed["experiments"][0]["status"], "execution_unknown")

    def test_checked_refutation_is_not_published_as_a_proof_of_original(self):
        output = solver("candidate", proof="A witness satisfies the hypotheses and contradicts P.")
        output["research"] = research(candidate_kind="counterexample")
        backend = ScriptedBackend([("solver", output), ("checker", {
            "verdict": "pass", "finding": "Witness checked.", "repair_hint": "", "unverified_premises": []})])
        library = self.root / "refutations"
        state = Runner(self.problem, self.output, Config(model="fake"), backend, library_dir=library).run()
        self.assertEqual(state["accepted_kind"], "counterexample")
        self.assertIn("refutation", backend.contexts[1]["task"])
        self.assertTrue(SharedLibrary(library).load()[0][0]["statement"].startswith("Refutation of:"))

    def test_disputed_dependency_invalidates_only_dependent_argument_versions(self):
        claims = [claim("Prime lemma A"), {**claim("Prime consequence B"), "depends_on": ["c1"]}, claim("Prime independent C")]
        backend = ScriptedBackend([("solver", solver("candidate", claims=claims, proof="Apply Prime lemma A.")),
            ("checker", {"verdict": "counterexample", "finding": "A fails.", "repair_hint": "Replace A.",
                         "unverified_premises": [], "target_obligation_id": "o1", "counterexample_evidence": "A boundary witness"})])
        library = self.root / "shared"
        state = Runner(self.problem, self.output, Config(model="fake", max_rounds=1), backend, library_dir=library).run()
        self.assertTrue(state["claims"][1]["stale_reason"])
        self.assertNotIn("stale_reason", state["claims"][2])
        self.assertEqual(state["obligations"][1]["status"], "supported")
        imported, _ = SharedLibrary(library).retrieve("Prime consequences", "other-problem", 5)
        self.assertEqual([r["statement"] for r in imported], ["Prime independent C"])

    @unittest.skipUnless(os.environ.get("PROOF_LOOP_TEST_SANDBOX") == "1", "opt-in real OS sandbox check")
    def test_local_sandbox_computes_but_blocks_external_files_and_network(self):
        private = self.root / "private.txt"
        private.write_text("not-for-the-worker")
        listener = socket.socket()
        self.addCleanup(listener.close)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        code = f'''import os, socket
from fractions import Fraction
print(Fraction(1, 3) + Fraction(1, 6))
for action in (lambda: open({str(private)!r}).read(), lambda: open({str(private)!r}, "w"),
               lambda: socket.create_connection(("127.0.0.1", {port}), timeout=1)):
    try:
        action()
        print("UNEXPECTED_ACCESS")
    except OSError:
        print("blocked")
print("secret_in_env", "CODEX_ACCESS_TOKEN" in os.environ)
'''
        with patch.dict(os.environ, {"CODEX_ACCESS_TOKEN": "private-test-token"}):
            result = execute("python", code, self.root / "sandbox-job", 5)
        self.assertEqual(result["status"], "completed", result)
        self.assertIn("1/2", result["output"])
        self.assertNotIn("UNEXPECTED_ACCESS", result["output"])
        self.assertIn("secret_in_env False", result["output"])
        self.assertEqual(private.read_text(), "not-for-the-worker")
        timeout = execute("python", "while True: pass", self.root / "timeout-job", 0.2)
        self.assertEqual(timeout["status"], "timed_out")

    @unittest.skipUnless(os.environ.get("PROOF_LOOP_TEST_LEAN") == "1", "opt-in installed Lean test")
    def test_local_lean_adapter_runs_installed_kernel_as_evidence(self):
        result = execute("lean", "example : 2 + 2 = (4 : Nat) := by decide\n", self.root / "lean-job", 10)
        self.assertEqual(result["status"], "completed", result)
        self.assertTrue(result["evidence_only"])


if __name__ == "__main__":
    unittest.main()
