"""Small, checkpointed proof-search state machine."""

from __future__ import annotations

import hashlib
import copy
import json
import os
import re
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from .library import SharedLibrary, make_record, permitted_assumptions
from .experiments import TOOLS, execute


class Backend(Protocol):
    def call(self, role: str, problem: str, context: dict[str, Any], timeout_seconds: float) -> tuple[dict[str, Any], dict[str, int | None]]: ...


@dataclass(frozen=True)
class Config:
    model: str
    backend: str = "api"
    solver_effort: str = "high"
    checker_effort: str = "high"
    route_hours: float = 2.0
    extension_minutes: float = 30.0
    max_call_minutes: float = 30.0
    max_routes: int = 2
    max_rounds: int = 8
    max_repairs_per_route: int = 1
    max_output_tokens: int = 25000
    library_limit: int = 5
    exploration_share: float = 0.85
    max_lemma_checks: int = 2
    tools: str = ""
    max_experiments: int = 8
    experiment_seconds: float = 30.0

    def validate(self) -> None:
        if not self.model.strip():
            raise ValueError("model is required")
        if self.backend not in {"api", "codex", "codex-cli"}:
            raise ValueError("backend must be api, codex, or codex-cli")
        if min(self.route_hours, self.max_call_minutes) <= 0 or self.extension_minutes < 0:
            raise ValueError("time limits must be positive; extension may be zero")
        if min(self.max_routes, self.max_rounds, self.max_output_tokens) <= 0:
            raise ValueError("route, round, and output limits must be positive")
        if self.max_repairs_per_route < 0:
            raise ValueError("repair limit cannot be negative")
        if self.library_limit < 0:
            raise ValueError("library limit cannot be negative")
        if not 0.5 <= self.exploration_share <= 1 or self.max_lemma_checks < 0:
            raise ValueError("exploration share must be between 0.5 and 1; lemma check limit must be nonnegative")
        if set(filter(None, self.tools.split(","))) - TOOLS:
            raise ValueError("tools must be a comma-separated subset of python,sage,lean")
        if self.max_experiments < 0 or not 0 < self.experiment_seconds <= 300:
            raise ValueError("experiment count must be nonnegative and duration in (0, 300] seconds")


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _normalized(value: str) -> str:
    return " ".join(value.split()).casefold()


def _statement_key(statement: str, assumptions: list[str]) -> str:
    # Keep mathematical spelling and hypotheses exact; only their order is irrelevant.
    return _digest(json.dumps([statement.strip(), sorted(a.strip() for a in assumptions)], ensure_ascii=False))


def _blocker_key(blocker: dict[str, Any]) -> str:
    return _digest(json.dumps([blocker.get(key, "") for key in
        ("obligation_id", "attempted_technique", "failure_point", "evidence", "next_test")], ensure_ascii=False))


def _totals(calls: list[dict[str, Any]]) -> dict[str, int | None]:
    names = ("input_tokens", "cached_tokens", "fresh_input_tokens", "cache_write_tokens", "output_tokens", "reasoning_tokens", "visible_output_tokens")
    result = {}
    for name in names:
        values = []
        for call in calls:
            usage = call["usage"] or {}
            value = usage.get(name)
            if value is None and name == "fresh_input_tokens" and usage.get("input_tokens") is not None and usage.get("cached_tokens") is not None:
                value = usage["input_tokens"] - usage["cached_tokens"]
            if value is None and name == "visible_output_tokens" and usage.get("output_tokens") is not None and usage.get("reasoning_tokens") is not None:
                value = usage["output_tokens"] - usage["reasoning_tokens"]
            values.append(value)
        result[name] = sum(values) if all(value is not None for value in values) else None
    return result


class Runner:
    def __init__(self, problem_path: Path, output_dir: Path, config: Config, backend: Backend, resume: bool = False, library_dir: Path | None = None):
        config.validate()
        self.problem_path = problem_path.resolve()
        self.problem = self.problem_path.read_text(encoding="utf-8")
        if not self.problem.strip():
            raise ValueError("problem file is empty")
        self.output_dir = output_dir.resolve()
        self.library = SharedLibrary(library_dir) if library_dir is not None else None
        self.library_path = str(self.library.directory) if self.library else None
        if self.library and self.library.directory == self.output_dir:
            raise ValueError("library directory must differ from the run output directory")
        self.config = config
        self.backend = backend
        self.state_path = self.output_dir / "state.json"
        self.report_path = self.output_dir / "report.md"
        if self.state_path.exists():
            if not resume:
                raise FileExistsError(f"{self.state_path} exists; use --resume")
            self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
            if self.state.get("schema_version") == 1:
                self.state["schema_version"] = 2
                self.state["config"].setdefault("library_limit", 5)
                self.state["config"].setdefault("backend", "api")
                self.state.setdefault("library_dir", None)
                self.state.setdefault("library_imports", [])
                self.state.setdefault("library_rejected_records", 0)
                self.state.setdefault("published_record_ids", [])
                self.state.setdefault("library_error", "")
            elif self.state.get("schema_version") not in {2, 3, 4}:
                raise ValueError("unsupported checkpoint schema")
            self.state["config"].setdefault("backend", "api")
            self.state["config"].setdefault("max_repairs_per_route", 1)
            for key in ("exploration_share", "max_lemma_checks", "tools", "max_experiments", "experiment_seconds"):
                self.state["config"].setdefault(key, asdict(Config(model=config.model))[key])
            for route in self.state["routes"]:
                if "repair_rounds" not in route:
                    route_calls = [call for call in self.state["calls"] if call["route_id"] == route["id"]]
                    first_check = next((i for i, call in enumerate(route_calls) if call["role"] == "checker"), len(route_calls))
                    route["repair_rounds"] = sum(call["role"] == "solver" for call in route_calls[first_check + 1:])
            self.state.setdefault("obligations", [])
            self.state.setdefault("decisions", [])
            for obligation in self.state["obligations"]:
                obligation.setdefault("dependency_sets", [obligation["depends_on"]])
            for route in self.state["routes"]:
                route.setdefault("obligation_ids", [])
                route.setdefault("focus_obligation_id", "")
                route.setdefault("requested_artifact_ids", [])
                route.setdefault("seen_requested_artifact_ids", [])
                route.setdefault("seen_evidence_keys", [])
                route.setdefault("last_material_progress", route.get("last_progress", False))
                route.setdefault("human_notes", [])
                route.setdefault("blocker", None)
                route.setdefault("research_status", "ready_for_review" if route["status"] == "completed" else "exploring" if route["status"] == "active" else "abandoned")
                route.setdefault("last_blocker_key", "")
            prior_claim_obligations = {c["id"]: c.get("obligation_id") for c in self.state["claims"]}
            for claim in self.state["claims"]:
                claim.setdefault("artifact_id", self._artifact_id("claim", claim["argument"]))
                if claim["artifact_id"] != self._artifact_id("claim", claim["argument"]):
                    raise ValueError(f"claim artifact reference changed: {claim['id']}")
                dependency_obligations = [prior_claim_obligations[d] for d in claim["depends_on"] if prior_claim_obligations.get(d)]
                obligation, _ = self._ensure_obligation(claim["statement"], claim["assumptions"], claim["route_id"], dependency_obligations)
                claim.setdefault("obligation_id", obligation["id"])
                prior_claim_obligations[claim["id"]] = claim["obligation_id"]
                if claim["id"] not in obligation["attempt_ids"]:
                    obligation["attempt_ids"].append(claim["id"])
                    obligation["status"] = "supported"
                self._write_artifact("claim", claim["argument"])
            self.state.setdefault("candidate_artifact_ids", [])
            self.state.setdefault("disputed_record_ids", [])
            if self.state.get("candidate_proof"):
                candidate_id = self._write_artifact("candidate", self.state["candidate_proof"])
                self.state.setdefault("candidate_artifact_id", candidate_id)
                if self.state["candidate_artifact_id"] and self.state["candidate_artifact_id"] != candidate_id:
                    raise ValueError("candidate artifact reference changed")
                self.state["candidate_artifact_id"] = candidate_id
                if candidate_id not in self.state["candidate_artifact_ids"]:
                    self.state["candidate_artifact_ids"].append(candidate_id)
            for call in self.state["calls"]:
                call.setdefault("id", len([c for c in self.state["calls"] if c.get("id") is not None]) + 1)
                call.setdefault("status", "failed" if call.get("usage") is None else "applied")
                call.setdefault("receipt", "")
            for call in self.state["calls"]:
                if call["status"] == "pending":
                    path = self._receipt_path(call["id"])
                    if path.exists():
                        receipt = self._read_receipt(call)
                        call.update(status="received", receipt=str(path.relative_to(self.output_dir)),
                                    receipt_sha256=_digest(path.read_text(encoding="utf-8")),
                                    usage=receipt.get("usage"), seconds=receipt.get("seconds", 0.0))
                        if call["role"] == "solver":
                            route = next(r for r in self.state["routes"] if r["id"] == call["route_id"])
                            route["elapsed_seconds"] += call["seconds"]
                    else:
                        call["status"] = "execution_unknown"
            self.state["schema_version"] = 4
            if self.state["problem_sha256"] != _digest(self.problem) or self.state["config"] != asdict(config):
                raise ValueError("problem or configuration changed since the checkpoint")
            if self.state.get("library_dir") != self.library_path:
                raise ValueError("library directory changed since the checkpoint")
            if self.state["status"] == "blocked":
                self.state["status"] = "running"
                self.state["error"] = ""
        else:
            if resume:
                raise FileNotFoundError(self.state_path)
            imported, rejected = self.library.retrieve(self.problem, _digest(self.problem), config.library_limit) if self.library else ([], 0)
            self.state = {
                "schema_version": 4,
                "problem_path": str(self.problem_path),
                "problem_sha256": _digest(self.problem),
                "config": asdict(config),
                "status": "running",
                "error": "",
                "routes": [],
                "claims": [],
                "obligations": [],
                "decisions": [],
                "findings": [],
                "calls": [],
                "rounds": 0,
                "candidate_proof": "",
                "candidate_sha256": "",
                "candidate_artifact_id": "",
                "candidate_artifact_ids": [],
                "checked_candidate_hashes": [],
                "accepted_proof": "",
                "library_dir": self.library_path,
                "library_imports": imported,
                "library_rejected_records": rejected,
                "published_record_ids": [],
                "disputed_record_ids": [],
                "library_error": "",
            }
        self.state.setdefault("experiments", [])
        self.state.setdefault("pending_review", None)
        self.state.setdefault("reviewed_claim_ids", [])
        self.state.setdefault("candidate_kind", "proof")
        self.state.setdefault("accepted_kind", "proof" if self.state["accepted_proof"] else "")
        for route in self.state["routes"]:
            route.setdefault("technique", "")
            route.setdefault("difference_from_prior", "")
            route.setdefault("discriminating_test", "")
            route.setdefault("next_task", "explore")
        for job in self.state["experiments"]:
            if job["status"] == "pending":
                receipt = self.output_dir / "experiments" / job["id"] / "receipt.json"
                if receipt.exists():
                    recovered = json.loads(receipt.read_text(encoding="utf-8"))
                    job.update(recovered)
                    job["result_artifact_id"] = self._write_artifact("experiment", json.dumps(recovered, ensure_ascii=False))
                    next(r for r in self.state["routes"] if r["id"] == job["route_id"])["elapsed_seconds"] += recovered.get("seconds", 0)
                else:
                    # Side effects may have happened. Never silently repeat the execution.
                    job["status"] = "execution_unknown"
        self._save()

    def _artifact_id(self, kind: str, content: str) -> str:
        if kind not in {"claim", "candidate", "receipt", "experiment"}:
            raise ValueError("invalid artifact kind")
        return f"{kind}:{_digest(content)}"

    def _artifact_path(self, artifact_id: str) -> Path:
        kind, digest = artifact_id.split(":", 1)
        if kind not in {"claim", "candidate", "receipt", "experiment"} or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("invalid artifact ID")
        return self.output_dir / "artifacts" / f"{kind}-{digest}.txt"

    def _write_artifact(self, kind: str, content: str) -> str:
        artifact_id = self._artifact_id(kind, content)
        path = self._artifact_path(artifact_id)
        if path.exists():
            if _digest(path.read_text(encoding="utf-8")) != artifact_id.split(":", 1)[1]:
                raise ValueError(f"artifact changed: {artifact_id}")
        else:
            _atomic_text(path, content)
        return artifact_id

    def _read_artifact(self, artifact_id: str) -> str:
        content = self._artifact_path(artifact_id).read_text(encoding="utf-8")
        if self._artifact_id(artifact_id.split(":", 1)[0], content) != artifact_id:
            raise ValueError(f"artifact changed: {artifact_id}")
        return content

    def _receipt_path(self, call_id: int) -> Path:
        return self.output_dir / "artifacts" / f"call-{call_id:06d}-receipt.json"

    def _read_receipt(self, call: dict[str, Any]) -> dict[str, Any]:
        path = self._receipt_path(call["id"])
        content = path.read_text(encoding="utf-8")
        if call.get("receipt_sha256") and _digest(content) != call["receipt_sha256"]:
            raise ValueError(f"call receipt changed: {call['id']}")
        receipt = json.loads(content)
        if not isinstance(receipt, dict) or not isinstance(receipt.get("result"), dict):
            raise ValueError(f"invalid call receipt: {call['id']}")
        return receipt

    def _ensure_obligation(self, statement: str, assumptions: list[str], route_id: int, depends_on: list[str]) -> tuple[dict[str, Any], bool]:
        key = _statement_key(statement, assumptions)
        obligation = next((o for o in self.state["obligations"] if o["key"] == key), None)
        created = obligation is None
        if obligation is None:
            obligation = {"id": f"o{len(self.state['obligations']) + 1}", "key": key,
                          "statement": statement.strip(), "assumptions": assumptions,
                          "depends_on": list(depends_on), "dependency_sets": [list(depends_on)],
                          "status": "open", "attempt_ids": [], "evidence_ids": []}
            self.state["obligations"].append(obligation)
        elif depends_on not in obligation["dependency_sets"]:
            obligation["dependency_sets"].append(list(depends_on))
        route = next((r for r in self.state["routes"] if r["id"] == route_id), None)
        if route is not None and obligation["id"] not in route["obligation_ids"]:
            route["obligation_ids"].append(obligation["id"])
        return obligation, created

    def _add_obligations(self, raw: Any, route_id: int) -> int:
        if not isinstance(raw, list):
            raise ValueError("solver obligations must be a list")
        known = {o["id"] for o in self.state["obligations"]}
        added = 0
        for item in raw:
            if not isinstance(item, dict) or not isinstance(item.get("statement"), str) or not item["statement"].strip():
                raise ValueError("invalid obligation statement")
            assumptions, dependencies = item.get("assumptions"), item.get("depends_on")
            if not isinstance(assumptions, list) or not all(isinstance(a, str) for a in assumptions):
                raise ValueError("invalid obligation assumptions")
            if not isinstance(dependencies, list) or not all(isinstance(d, str) and d in known for d in dependencies):
                raise ValueError("obligation depends_on must contain existing obligation IDs")
            route = next(r for r in self.state["routes"] if r["id"] == route_id)
            before = len(route["obligation_ids"])
            self._ensure_obligation(item["statement"], assumptions, route_id, dependencies)
            added += int(len(route["obligation_ids"]) > before)
        return added

    def _sync_library(self) -> None:
        if self.library is None:
            return
        records = []
        claim_records = []
        claim_index = {claim["id"]: claim for claim in self.state["claims"]}
        for claim in self.state["claims"]:
            dependencies = [{"id": dep, "statement": claim_index[dep]["statement"], "status": "unverified"} for dep in claim["depends_on"]]
            record = make_record(
                kind="claim", status="unverified", statement=claim["statement"],
                assumptions=claim["assumptions"], argument=claim["argument"],
                dependencies=dependencies, source_problem_sha256=self.state["problem_sha256"],
                source_problem_path=str(self.problem_path), source_run=str(self.output_dir),
                source_model=self.config.model,
            )
            records.append(record)
            claim_records.append((claim, record))
        if self.state["accepted_proof"]:
            records.append(make_record(
                kind="solution", status="model_checked", statement=("Refutation of:\n" if self.state.get("accepted_kind") == "counterexample" else "") + self.problem,
                assumptions=permitted_assumptions(self.problem),
                argument=self.state["accepted_proof"], dependencies=[],
                source_problem_sha256=self.state["problem_sha256"],
                source_problem_path=str(self.problem_path), source_run=str(self.output_dir),
                source_model=self.config.model,
            ))
        published = set(self.state["published_record_ids"])
        try:
            for record in records:
                if record["id"] not in published:
                    self.library.publish(record)
                    self.state["published_record_ids"].append(record["id"])
                    published.add(record["id"])
            disputed = set(self.state["disputed_record_ids"])
            obligation_by_id = {o["id"]: o for o in self.state["obligations"]}
            for claim, record in claim_records:
                obligation = obligation_by_id[claim["obligation_id"]]
                if (obligation["status"] == "disputed" or claim.get("stale_reason")) and record["id"] not in disputed:
                    evidence = next((f.get("counterexample_evidence", "") for f in reversed(self.state["findings"])
                                     if f.get("target_obligation_id") == obligation["id"]), claim.get("stale_reason", "Model checker disputed the obligation."))
                    self.library.dispute(record["id"], evidence)
                    self.state["disputed_record_ids"].append(record["id"])
                    disputed.add(record["id"])
            self.state["library_error"] = ""
        except (OSError, ValueError) as error:
            self.state["library_error"] = f"{type(error).__name__}: {error}"

    def _save(self) -> None:
        _atomic_text(self.state_path, json.dumps(self.state, ensure_ascii=False, indent=2) + "\n")
        _atomic_text(self.report_path, self._report())
        brief = self._research_brief()
        _atomic_text(self.output_dir / "research-state.json", json.dumps(brief, ensure_ascii=False, indent=2) + "\n")
        lines = ["# Research state", "", "Navigation summary; exact statements, assumptions, and arguments remain in state.json and artifacts/.",
                 "The original target is unchanged. Partial results do not certify it.", "", f"Round: {self.state['rounds']}; run status: {self.state['status']}"]
        for route in brief["routes"]:
            lines += ["", f"## Route {route['id']}: {route['status']}", route["summary"],
                      f"Technique: {route['technique']}", f"Blocker: {route['blocker']}", f"Next test: {route['next_test']}"]
        lines += ["", "## Partial results", ""]
        lines += [f"- {c['id']} ({c['kind']}, {c['status']}): {c['statement_preview']} — {c['artifact_id']}" for c in brief["results"]]
        lines += ["", "## Recent decisions", ""]
        lines += [f"- {d['action']}: {d['reason']}" for d in brief["decisions"]]
        _atomic_text(self.output_dir / "research-state.md", "\n".join(lines) + "\n")

    def _research_brief(self) -> dict[str, Any]:
        return {"problem_sha256": self.state["problem_sha256"], "round": self.state["rounds"],
                "routes": [{"id": r["id"], "status": r["research_status"], "technique": r.get("technique", "")[:300],
                            "summary": r["summary"][:800], "blocker": r["obstruction"][:400], "next_test": r["next_test"][:400]}
                           for r in self.state["routes"][-6:]],
                "results": [{"id": c["id"], "kind": c.get("kind", "lemma"), "status": c.get("review_status", "unverified"),
                             "statement_preview": c["statement"][:300], "artifact_id": c["artifact_id"]}
                            for c in self.state["claims"][-12:]],
                "decisions": [{"action": d["action"], "reason": d["reason"][:400]} for d in self.state["decisions"][-8:]]}

    def resume_with_human_note(self, note: str) -> None:
        if self.state["status"] != "needs_human_input" or not note.strip():
            raise ValueError("a nonempty human note requires a run waiting for human input")
        route = self.state["routes"][-1]
        route["human_notes"].append(note.strip())
        route["status"] = "active"
        route["research_status"] = "exploring"
        self.state["status"] = "running"
        self._decide(route, "human_input", note.strip())
        self._save()

    def _report(self) -> str:
        state = self.state
        lines = ["# Proof Loop run", "", f"Status: **{state['status']}**", "", f"Problem: `{state['problem_path']}`", "", f"Rounds: {state['rounds']}"]
        totals = _totals(state["calls"])
        lines += ["", "## Usage", ""]
        lines += [f"- {name}: {amount if amount is not None else 'unavailable'}" for name, amount in totals.items()]
        unknown_calls = sum(call["usage"] is None for call in state["calls"])
        if unknown_calls:
            lines.append(f"- {unknown_calls} call(s) have unavailable usage; the totals may undercount cost.")
        call_states = [f"{status}={sum(c['status'] == status for c in state['calls'])}" for status in
                       ("pending", "received", "applied", "failed", "execution_unknown")]
        lines.append(f"- call states: {', '.join(call_states)}")
        lines += ["", "## Routes", ""]
        for route in state["routes"]:
            lines.append(f"- Route {route['id']} ({route['research_status']}; {route['status']}, {route['elapsed_seconds']:.1f}s, repairs {route['repair_rounds']}/{self.config.max_repairs_per_route}): {route['title'] or 'untitled'} — {route['summary']}")
            if route["obstruction"]:
                lines.append(f"  - Obstruction: {route['obstruction']}")
            if route["obligation_ids"]:
                lines.append(f"  - Obligations: {', '.join(route['obligation_ids'])}")
            if route["blocker"]:
                lines.append(f"  - Blocker: {route['blocker']['failure_point']} (next test: {route['blocker']['next_test']})")
            if route["human_notes"]:
                lines.append(f"  - Human notes: {len(route['human_notes'])}")
        if not state["routes"]:
            lines.append("No route started.")
        lines += ["", "## Obligations", ""]
        for obligation in state["obligations"]:
            lines.append(f"- **{obligation['id']}** ({obligation['status']}): {obligation['statement']}")
            dependency_text = " or ".join("{" + ", ".join(group) + "}" for group in obligation["dependency_sets"])
            lines.append(f"  - Assumptions: {'; '.join(obligation['assumptions']) or 'None stated'}; dependency options: {dependency_text}; argument attempts: {', '.join(obligation['attempt_ids']) or 'None'}")
        if not state["obligations"]:
            lines.append("No obligations recorded; a direct complete proof may need none.")
        lines += ["", "## Decisions", ""]
        for decision in state["decisions"]:
            lines.append(f"- Route {decision['route_id']}, round {decision['round']}: **{decision['action']}** — {decision['reason']}")
        if not state["decisions"]:
            lines.append("No redirection decision yet.")
        if state["library_dir"]:
            lines += ["", "## Shared library", "", f"Directory: `{state['library_dir']}`", ""]
            lines.append(f"Imported {len(state['library_imports'])} relevant record(s); published {len(state['published_record_ids'])} record(s).")
            for record in state["library_imports"]:
                lines.append(f"- `{record['id'][:12]}` ({record['status']}, {record['kind']}): {record['statement'].strip().splitlines()[0]}")
                lines.append(f"  - Assumptions: {'; '.join(record['assumptions']) or 'None stated'}")
                lines.append(f"  - Source: `{record['source_problem_path']}`")
            if state["library_rejected_records"]:
                lines.append(f"- Skipped {state['library_rejected_records']} invalid record(s).")
            if state["library_error"]:
                lines.append(f"- Publication error: {state['library_error']}")
            if state["disputed_record_ids"]:
                lines.append(f"- Excluded {len(state['disputed_record_ids'])} disputed argument version(s) from future library imports.")
        lines += ["", "## Claims", ""]
        for claim in state["claims"]:
            lines.append(f"- **{claim['id']}** ({claim.get('kind', 'lemma')}, {claim.get('review_status', 'unverified')} argument for {claim['obligation_id']}; artifact `{claim['artifact_id']}`): {claim['statement']}")
            if claim["assumptions"]:
                lines.append(f"  - Assumptions: {', '.join(claim['assumptions'])}")
        if not state["claims"]:
            lines.append("No claims recorded.")
        lines += ["", "## Computations", ""]
        for job in state.get("experiments", []):
            lines.append(f"- {job['id']} ({job['tool']}, {job['status']}): {job['purpose']} — source artifact `{job['artifact_id']}`")
            if job.get("output"):
                lines.append("\n```text\n" + job["output"][:2000] + "\n```\n")
        lines.append("Computation output is evidence only; even successful Lean code does not establish correspondence with the original target.")
        lines += ["", "## Checker findings", ""]
        for finding in state["findings"]:
            lines.append(f"- **{finding['verdict']}** ({finding.get('scope', 'candidate')}) on route {finding['route_id']}: {finding['finding']}")
            if finding["repair_hint"]:
                lines.append(f"  - Repair hint: {finding['repair_hint']}")
        if not state["findings"]:
            lines.append("No candidate checked.")
        proof = state["accepted_proof"] or state["candidate_proof"]
        if proof:
            label = "Model checked proof" if state["accepted_proof"] else "Latest unverified candidate"
            if state.get("candidate_kind") == "counterexample":
                label = "Model checked refutation" if state["accepted_proof"] else "Latest unverified refutation"
            lines += ["", f"## {label}", "", proof]
            if state.get("candidate_artifact_id"):
                lines.append(f"\nCandidate artifact: `{state['candidate_artifact_id']}`")
        if state["error"]:
            lines += ["", "## Operational error", "", state["error"]]
        lines += ["", "A model checker pass is not a formal proof certificate.", ""]
        return "\n".join(lines)

    def _active_route(self) -> dict[str, Any] | None:
        return next((route for route in reversed(self.state["routes"]) if route["status"] == "active"), None)

    def _open_route(self) -> dict[str, Any]:
        prior_routes = []
        for earlier in self.state["routes"]:
            finding = next((f for f in reversed(self.state["findings"]) if f["route_id"] == earlier["id"]), None)
            prior_routes.append({
                "title": earlier["title"], "summary": earlier["summary"], "obstruction": earlier["obstruction"],
                "checker_finding": finding["finding"] if finding else "",
                "blocker": earlier.get("blocker"),
                "technique": earlier.get("technique", ""),
            })
        route = {
            "id": len(self.state["routes"]) + 1,
            "title": "",
            "summary": "",
            "obstruction": "",
            "next_test": "",
            "elapsed_seconds": 0.0,
            "rounds": 0,
            "repair_rounds": 0,
            "extended": False,
            "checkpoint_sent": False,
            "last_progress": False,
            "status": "active",
            "base_claims": [],
            "prior_routes": prior_routes,
            "obligation_ids": [],
            "focus_obligation_id": "",
            "requested_artifact_ids": [],
            "seen_requested_artifact_ids": [],
            "seen_evidence_keys": [],
            "last_material_progress": False,
            "human_notes": [],
            "blocker": None,
            "last_blocker_key": "",
            "research_status": "exploring",
            "technique": "", "difference_from_prior": "", "discriminating_test": "", "next_task": "explore",
        }
        self.state["routes"].append(route)
        self._save()
        return route

    def _remaining(self, route: dict[str, Any]) -> float:
        allowance = self.config.route_hours * 3600
        if route["extended"]:
            allowance += self.config.extension_minutes * 60
        return allowance - route["elapsed_seconds"]

    def _call(self, role: str, route: dict[str, Any], context: dict[str, Any], timeout: float) -> dict[str, Any]:
        existing = next((c for c in self.state["calls"] if c["status"] == "received"), None)
        if existing is not None:
            if existing["role"] != role or existing["route_id"] != route["id"]:
                raise ValueError(f"unapplied {existing['role']} receipt on route {existing['route_id']}")
            self._current_call_id = existing["id"]
            return self._read_receipt(existing)["result"]
        call = {"id": len(self.state["calls"]) + 1, "role": role, "route_id": route["id"],
                "status": "pending", "seconds": 0.0, "usage": None, "receipt": "", "scope": context.get("scope", role)}
        self.state["calls"].append(call)
        self._save()
        started = time.monotonic()
        try:
            result, usage = self.backend.call(role, self.problem, context, max(1.0, timeout))
            if not isinstance(result, dict):
                raise ValueError(f"{role} returned a non-object")
            elapsed = time.monotonic() - started
            receipt_text = json.dumps({"result": result, "usage": usage, "seconds": elapsed}, ensure_ascii=False, sort_keys=True)
            path = self._receipt_path(call["id"])
            _atomic_text(path, receipt_text)
            call.update(status="received", seconds=elapsed, usage=usage,
                        receipt=str(path.relative_to(self.output_dir)), receipt_sha256=_digest(receipt_text))
            if role == "solver":
                route["elapsed_seconds"] += elapsed
            self._current_call_id = call["id"]
            self._save()
            return result
        except Exception as error:
            elapsed = time.monotonic() - started
            if role == "solver":
                route["elapsed_seconds"] += elapsed
            call.update(status="failed", seconds=elapsed)
            self.state["status"] = "blocked"
            self.state["error"] = f"{role} call failed: {type(error).__name__}: {error}"
            self._save()
            raise

    def _finish_call(self, success: bool = True) -> None:
        call = next(c for c in self.state["calls"] if c["id"] == self._current_call_id)
        call["status"] = "applied" if success else "failed"

    def _decide(self, route: dict[str, Any], action: str, reason: str, blocker_key: str = "") -> None:
        self.state["decisions"].append({"route_id": route["id"], "round": self.state["rounds"],
                                        "action": action, "reason": reason, "blocker_key": blocker_key})

    def _review_budget(self) -> int:
        """Soft output-token allocation for optional checks; final checks are mandatory."""
        if len(self.state["reviewed_claim_ids"]) >= self.config.max_lemma_checks:
            return 0
        solver_tokens = checker_tokens = 0
        for call in self.state["calls"]:
            usage = call.get("usage") or {}
            amount = usage.get("output_tokens")
            if amount is None:
                return 0  # Unknown spend cannot justify an optional check.
            if call["role"] == "solver":
                solver_tokens += amount
            else:
                checker_tokens += amount
        allowance = int(solver_tokens * (1 - self.config.exploration_share) / self.config.exploration_share) - checker_tokens
        return min(allowance, self.config.max_output_tokens) if allowance >= 1024 else 0

    def _accept_research(self, result: dict[str, Any], route: dict[str, Any]) -> bool:
        raw = result.get("research")
        if raw is None:  # Already committed responses from older checkpoints.
            return False
        strings = ("technique", "difference_from_prior", "discriminating_test", "next_task", "review_claim_id", "review_reason", "candidate_kind")
        if not isinstance(raw, dict) or any(not isinstance(raw.get(k), str) for k in strings):
            raise ValueError("invalid research assignment")
        if raw["next_task"] not in {"explore", "prove", "counterexample"} or raw["candidate_kind"] not in {"proof", "counterexample"}:
            raise ValueError("invalid research task or candidate kind")
        if not raw["technique"].strip():
            raise ValueError("research route needs an explicit technique")
        if not route["technique"]:
            prior = self.state["routes"][:route["id"] - 1]
            if prior and (not raw["difference_from_prior"].strip() or not raw["discriminating_test"].strip() or
                          any(_normalized(r.get("technique", "")) == _normalized(raw["technique"]) for r in prior)):
                route["status"] = "duplicate_route"
                route["research_status"] = "abandoned"
                self._decide(route, "reject_route", "A new route must name a different technique, explain the difference, and give a discriminating test.")
            route.update({k: raw[k] for k in ("technique", "difference_from_prior", "discriminating_test")})
        elif _normalized(raw["technique"]) != _normalized(route["technique"]):
            raise ValueError("major technique changes require switching routes")
        route["next_task"] = raw["next_task"]
        outcomes = raw.get("outcomes")
        if not isinstance(outcomes, list) or any(not isinstance(o, dict) or o.get("kind") not in
                {"lemma", "conditional_theorem", "reduction", "counterexample"} for o in outcomes):
            raise ValueError("invalid partial outcomes")
        added = bool(self._add_claims(outcomes, route["id"]))
        experiment = raw.get("experiment")
        if not isinstance(experiment, dict) or any(not isinstance(experiment.get(k), str) for k in ("tool", "code", "purpose")):
            raise ValueError("invalid experiment")
        if result["status"] == "candidate":
            if experiment["tool"] or raw["review_claim_id"]:
                raise ValueError("complete candidates cannot also request experiments or intermediate review")
            self.state["candidate_kind"] = raw["candidate_kind"]
        if route["status"] != "active":
            return added
        if experiment["tool"]:
            if experiment["tool"] not in self.config.tools.split(",") or not experiment["code"].strip() or not experiment["purpose"].strip():
                raise ValueError("experiment tool is disabled or its code/purpose is missing")
            if len(experiment["code"]) > 50000:
                raise ValueError("experiment source exceeds 50000 characters")
            key = _digest(experiment["tool"] + "\n" + experiment["code"])
            if len(self.state["experiments"]) >= self.config.max_experiments or any(j["key"] == key for j in self.state["experiments"]):
                self._decide(route, "skip_experiment", "Computation already recorded or the experiment allowance is exhausted.")
            else:
                self.state["experiments"].append({"id": f"e{len(self.state['experiments']) + 1}", "key": key,
                    "route_id": route["id"], "status": "queued", "tool": experiment["tool"], "purpose": experiment["purpose"],
                    "artifact_id": self._write_artifact("experiment", experiment["code"])})
                added = True
        elif experiment["code"] or experiment["purpose"]:
            raise ValueError("experiment fields must all be empty when no tool is requested")
        target_id = raw["review_claim_id"]
        if target_id:
            claim = next((c for c in self.state["claims"] if c["id"] == target_id), None)
            if claim is None or not raw["review_reason"].strip():
                raise ValueError("pivotal review needs a known claim ID and a reason")
            budget = self._review_budget()
            if target_id in self.state["reviewed_claim_ids"] or not budget:
                self._decide(route, "defer_review", "Pivotal claim already reviewed or optional-check budget unavailable; continue exploration.")
            else:
                self.state["pending_review"] = {"claim_id": target_id, "route_id": route["id"], "output_limit": budget}
                self._decide(route, "review_lemma", raw["review_reason"])
                added = True
        return added

    def _compute(self, job: dict[str, Any]) -> None:
        route = next(r for r in self.state["routes"] if r["id"] == job["route_id"])
        directory = self.output_dir / "experiments" / job["id"]
        job["status"] = "pending"
        self._save()
        started = time.monotonic()
        try:
            seconds = min(self.config.experiment_seconds, self._remaining(route))
            if seconds <= 0:
                result = {"status": "skipped", "seconds": 0, "output": "Route time budget exhausted."}
            else:
                result = execute(job["tool"], self._read_artifact(job["artifact_id"]), directory, seconds)
        except Exception as error:
            result = {"status": "failed", "seconds": round(time.monotonic() - started, 3), "output": f"{type(error).__name__}: {error}"}
        _atomic_text(directory / "receipt.json", json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        job.update(result)
        job["result_artifact_id"] = self._write_artifact("experiment", json.dumps(result, ensure_ascii=False))
        route["elapsed_seconds"] += result["seconds"]
        self._save()

    def _parse_blocker(self, result: dict[str, Any], route: dict[str, Any]) -> dict[str, Any] | None:
        raw = result.get("blocker")
        if raw is None:  # Legacy scripted responses and old provider results.
            if result["status"] == "candidate":
                return None
            if not result["obstruction"].strip():
                return None
            raw = {"obligation_id": route["focus_obligation_id"], "attempted_technique": "",
                   "failure_point": result["obstruction"], "evidence": "", "affected_assumptions": [],
                   "next_test": result["next_test"], "proposed_action": "repair", "reason": "Legacy obstruction"}
        if not isinstance(raw, dict) or any(not isinstance(raw.get(k), str) for k in
            ("obligation_id", "attempted_technique", "failure_point", "evidence", "next_test", "proposed_action", "reason")):
            raise ValueError("invalid blocker")
        if not isinstance(raw.get("affected_assumptions"), list) or not all(isinstance(a, str) for a in raw["affected_assumptions"]):
            raise ValueError("invalid blocker assumptions")
        if raw["proposed_action"] not in {"repair", "split", "test_assumption", "switch_route", "request_human_input", "none"}:
            raise ValueError("invalid blocker action")
        if raw["obligation_id"] and raw["obligation_id"] not in route["obligation_ids"]:
            raise ValueError("blocker obligation is not on this route")
        if not raw["failure_point"].strip() and raw["proposed_action"] == "none":
            return None
        return raw

    def _add_claims(self, claims: Any, route_id: int) -> int:
        if not isinstance(claims, list):
            raise ValueError("solver claims must be a list")
        known = {claim["id"] for claim in self.state["claims"]}
        fingerprints = {_digest(json.dumps([_statement_key(c["statement"], c["assumptions"]), c["depends_on"], c["argument"]], ensure_ascii=False)) for c in self.state["claims"]}
        added = 0
        for claim in claims:
            if not isinstance(claim, dict) or not all(isinstance(claim.get(k), str) for k in ("statement", "argument")):
                raise ValueError("invalid claim")
            assumptions, dependencies = claim.get("assumptions"), claim.get("depends_on")
            if not isinstance(assumptions, list) or not all(isinstance(x, str) for x in assumptions):
                raise ValueError("invalid claim assumptions")
            if claim.get("kind") == "conditional_theorem" and not any(a.strip() for a in assumptions):
                raise ValueError("conditional theorem needs explicit assumptions")
            if not isinstance(dependencies, list) or not all(isinstance(x, str) and x in known for x in dependencies):
                raise ValueError("claim depends_on must contain existing claim IDs")
            if not claim["statement"].strip() or not claim["argument"].strip():
                continue
            dependency_obligations = [next(c for c in self.state["claims"] if c["id"] == dep)["obligation_id"] for dep in dependencies]
            obligation, _ = self._ensure_obligation(claim["statement"], assumptions, route_id, dependency_obligations)
            fingerprint = _digest(json.dumps([obligation["key"], dependencies, claim["argument"]], ensure_ascii=False))
            if fingerprint in fingerprints:
                continue
            artifact_id = self._write_artifact("claim", claim["argument"])
            new = {"id": f"c{len(self.state['claims']) + 1}", "route_id": route_id,
                   "obligation_id": obligation["id"], "artifact_id": artifact_id,
                   "kind": claim.get("kind", "lemma"), "review_status": "unverified",
                   "statement": claim["statement"], "assumptions": assumptions,
                   "depends_on": dependencies, "argument": claim["argument"]}
            self.state["claims"].append(new)
            obligation["attempt_ids"].append(new["id"])
            if obligation["status"] == "open":
                obligation["status"] = "supported"
            known.add(new["id"])
            fingerprints.add(fingerprint)
            added += 1
        return added

    def _focus_obligation(self, route: dict[str, Any]) -> dict[str, Any] | None:
        by_id = {o["id"]: o for o in self.state["obligations"]}
        chosen = by_id.get(route["focus_obligation_id"])
        if chosen and chosen["id"] in route["obligation_ids"] and chosen["status"] != "disputed":
            return chosen
        return next((by_id[i] for i in route["obligation_ids"] if by_id[i]["status"] != "disputed"), None)

    def _relevant_claims(self, obligation: dict[str, Any] | None, proof: str = "") -> list[dict[str, Any]]:
        by_id = {c["id"]: c for c in self.state["claims"]}
        selected: set[str] = set()
        if obligation:
            selected.update(obligation["attempt_ids"][-2:])
            for dependency in dict.fromkeys(d for group in obligation["dependency_sets"] for d in group):
                dep = next((o for o in self.state["obligations"] if o["id"] == dependency), None)
                if dep:
                    selected.update(dep["attempt_ids"][-1:])
        if proof:
            selected.update(c["id"] for c in self.state["claims"] if
                            re.search(rf"(?<!\w){re.escape(c['id'])}(?!\w)", proof) or
                            (len(c["statement"]) >= 12 and c["statement"] in proof))
        stack = list(selected)
        while stack:
            claim_id = stack.pop()
            for dependency in by_id[claim_id]["depends_on"]:
                if dependency not in selected:
                    selected.add(dependency)
                    stack.append(dependency)
        return [c for c in self.state["claims"] if c["id"] in selected]

    def _selected_imports(self, target: str) -> list[dict[str, Any]]:
        imports = self.state["library_imports"]
        if len(imports) <= 2:
            return imports
        terms = set(re.findall(r"\w+", target.casefold()))
        explicit = [r for r in imports if r["id"] in target or (len(r["statement"]) >= 12 and r["statement"] in target)]
        ranked = sorted((r for r in imports if r not in explicit), key=lambda r: -len(terms & set(re.findall(r"\w+", r["statement"].casefold()))))
        return explicit + ranked[:max(0, 2 - len(explicit))]

    def _requested_artifacts(self, route: dict[str, Any]) -> list[dict[str, str]]:
        result = []
        for artifact_id in route["requested_artifact_ids"]:
            if artifact_id.startswith("record:"):
                record = next(r for r in self.state["library_imports"] if r["id"] == artifact_id[7:])
                result.append({"id": artifact_id, "content": json.dumps(record, ensure_ascii=False)})
            else:
                result.append({"id": artifact_id, "content": self._read_artifact(artifact_id)})
        return result

    def _validate_requested(self, raw: Any) -> list[str]:
        if not isinstance(raw, list) or len(raw) > 2 or not all(isinstance(item, str) for item in raw):
            raise ValueError("request_artifact_ids must contain at most two IDs")
        available = {c["artifact_id"] for c in self.state["claims"]}
        available.update(self.state["candidate_artifact_ids"])
        available.update("record:" + r["id"] for r in self.state["library_imports"])
        available.update(j[k] for j in self.state["experiments"] for k in ("artifact_id", "result_artifact_id") if k in j)
        if any(item not in available for item in raw):
            raise ValueError("requested artifact is unavailable")
        return list(dict.fromkeys(raw))

    def _solver_context(self, route: dict[str, Any]) -> dict[str, Any]:
        findings = [f for f in self.state["findings"] if f["route_id"] == route["id"] and f.get("scope", "candidate") == "candidate"]
        repairing = bool(findings)
        focus = self._focus_obligation(route)
        selected_claims = self._relevant_claims(focus)
        selected_imports = self._selected_imports(focus["statement"] if focus else self.problem)
        task = "Repair the latest checker finding with a revised complete proof, or state the obstruction if it cannot be fixed." if repairing else (
            f"Work on obligation {focus['id']}; close it, split it, or report a discriminating blocker." if focus else
            "Explore a promising route; produce a complete proof if available, otherwise identify a decisive obligation.")
        assignment = "repair" if repairing else route["next_task"]
        if not repairing and route["blocker"] and route["blocker"]["proposed_action"] == "test_assumption":
            assignment = "counterexample"
        if assignment == "counterexample":
            task = "Try to falsify the focused obligation or the exact original conjecture. Check all hypotheses on each witness. A failed search proves nothing; report search bounds, evidence and the next discriminating test."
        elif assignment == "prove":
            task = "Close the focused obligation (or the original target if none is selected) using explicit assumptions and relevant supporting arguments. If blocked, state the precise missing implication and the cheapest way to test it."
        return {
            "stable_context": {"route_id": route["id"], "prior_routes_to_avoid": route["prior_routes"],
                               "obligation_index": [{"id": o["id"], "statement": o["statement"], "assumptions": o["assumptions"], "status": o["status"]} for o in self.state["obligations"] if o["id"] in route["obligation_ids"]],
                               "shared_obligation_index": [{"id": o["id"], "statement": o["statement"], "assumptions": o["assumptions"], "status": o["status"]} for o in self.state["obligations"] if o["id"] not in route["obligation_ids"]][-12:],
                               "prior_problem_index": [{"id": "record:" + r["id"], "statement": r["statement"], "assumptions": r["assumptions"], "status": r["status"]} for r in self.state["library_imports"]]},
            "working_context": {
                "task": task,
                "research_state": self._research_brief(),
                "technique": route["technique"],
                "assignment_kind": assignment,
                "optional_review_output_budget": self._review_budget(),
                "available_tools": list(filter(None, self.config.tools.split(","))),
                "experiments_remaining": max(0, self.config.max_experiments - len(self.state["experiments"])),
                "experiment_seconds": self.config.experiment_seconds,
                "recent_experiments": [{**{k: v for k, v in j.items() if k != "output"}, "output_preview": j.get("output", "")[:4000]}
                                       for j in self.state["experiments"][-3:]],
                "latest_intermediate_review": next((f for f in reversed(self.state["findings"]) if f.get("scope") == "intermediate"), None),
                "focus_obligation": focus,
                "relevant_claims": selected_claims,
                "other_attempts": [{"id": c["id"], "obligation_id": c["obligation_id"], "artifact_id": c["artifact_id"]} for c in self.state["claims"] if c["obligation_id"] in route["obligation_ids"] and c not in selected_claims][-12:],
                "requested_artifacts": self._requested_artifacts(route),
                "selected_prior_records": selected_imports,
                "repairs_remaining": self.config.max_repairs_per_route - route["repair_rounds"] if repairing else None,
                "route_title": route["title"],
                "latest_blocker": route["blocker"],
                "latest_human_note": route["human_notes"][-1] if route["human_notes"] else "",
                "latest_checker_finding": findings[-1] if findings else None,
                "latest_candidate_proof": self.state["candidate_proof"] if findings else "",
                "checkpoint_due": route["elapsed_seconds"] >= self.config.route_hours * 1800 and not route["checkpoint_sent"],
                "seconds_remaining": round(self._remaining(route)),
                "instruction": "Prior-problem records are leads with explicit assumptions and status. Check applicability; unverified records are not established facts. A candidate must justify every material imported premise. Use existing claim IDs in claims.depends_on and existing obligation IDs in obligations.depends_on. New obligations are for exact subgoals. To load older text next round, request up to two IDs from other_attempts or prior_problem_index. A candidate_proof must be complete when status=candidate. Keep summaries concise. Report a precise blocker and action for unfinished work. If checkpoint_due, state the strongest result and cheapest next test.",
            },
        }

    def _verify(self, route: dict[str, Any], proof: str, claim_id: str = "", output_limit: int = 0) -> bool:
        target_claim = next((c for c in self.state["claims"] if c["id"] == claim_id), None)
        if claim_id and target_claim is None:
            raise ValueError("review target is unavailable")
        context = {"task": "Independently check this candidate against the exact problem. Prior-run status is provenance, not acceptance authority; check the hypotheses and justification of every imported result used.",
                   "scope": "intermediate" if target_claim else "candidate",
                   "candidate_kind": self.state["candidate_kind"],
                   "candidate_proof": proof, "recorded_claims": self._relevant_claims(None, claim_id + " " + proof),
                   "claim_index": [{"id": c["id"], "statement": c["statement"], "assumptions": c["assumptions"]} for c in self.state["claims"]],
                   "obligation_index": [{"id": o["id"], "statement": o["statement"], "assumptions": o["assumptions"]} for o in self.state["obligations"]],
                   "prior_problem_index": [{"id": r["id"], "statement": r["statement"], "assumptions": r["assumptions"], "status": r["status"]} for r in self.state["library_imports"]],
                   "prior_problem_records": self._selected_imports(proof)}
        if target_claim:
            context.update(task="Check only this exact intermediate statement under its stated assumptions and dependencies. The original problem supplies context, not an additional claim to certify. Preserve conditionality. A pass does not solve the original target.",
                           review_target=target_claim, review_output_limit=output_limit)
        elif self.state["candidate_kind"] == "counterexample":
            context["task"] = "Check this claimed refutation of the exact original conjecture. Verify the witness meets every hypothesis and violates its conclusion. A counterexample to an auxiliary lemma is insufficient."
        result = self._call("checker", route, context, self.config.max_call_minutes * 60)
        verdict = result.get("verdict")
        premises = result.get("unverified_premises")
        if verdict not in {"pass", "gap", "counterexample", "uncertain"} or not isinstance(result.get("finding"), str) or not result["finding"].strip() or not isinstance(result.get("repair_hint"), str) or not isinstance(premises, list) or not all(isinstance(p, str) for p in premises):
            self._finish_call(False)
            raise ValueError("invalid checker result")
        if verdict == "pass" and premises:
            result = {**result, "verdict": "uncertain", "finding": "Unverified premises remain: " + "; ".join(premises)}
            verdict = "uncertain"
        target_id = result.get("target_obligation_id", "")
        counterexample = result.get("counterexample_evidence", "")
        if not isinstance(target_id, str) or not isinstance(counterexample, str) or (target_id and (verdict != "counterexample" or not counterexample.strip())):
            self._finish_call(False)
            raise ValueError("invalid targeted counterexample")
        target = next((o for o in self.state["obligations"] if o["id"] == target_id), None)
        if target_id and target is None:
            self._finish_call(False)
            raise ValueError("checker targeted an unknown obligation")
        finding = {"route_id": route["id"], "candidate_sha256": _digest(proof), "scope": context["scope"], "claim_id": claim_id, **result}
        if target is not None:
            target["status"] = "disputed"
            target["evidence_ids"].append(f"finding:{len(self.state['findings']) + 1}")
            invalid = {c["id"] for c in self.state["claims"] if c["obligation_id"] == target_id}
            while True:
                dependents = {c["id"] for c in self.state["claims"] if invalid.intersection(c["depends_on"])}
                if dependents <= invalid:
                    break
                invalid.update(dependents)
            for claim in self.state["claims"]:
                if claim["id"] in invalid:
                    claim["review_status"] = "unverified"
                    claim["stale_reason"] = f"Argument or dependency disputed by a counterexample to {target_id}."
            affected = [r["id"] for r in self.state["routes"] if target_id in r["obligation_ids"]]
            finding["affected_route_ids"] = affected
        self.state["findings"].append(finding)
        if target_claim:
            target_claim["review_status"] = "model_checked" if verdict == "pass" else "unverified"
            self.state["reviewed_claim_ids"].append(claim_id)
            self.state["pending_review"] = None
            self._decide(route, "lemma_reviewed", f"{claim_id}: {verdict}. {result['finding']}")
        else:
            self.state["checked_candidate_hashes"].append(finding["candidate_sha256"])
        if verdict == "pass" and not target_claim:
            self.state["accepted_proof"] = proof
            self.state["accepted_kind"] = self.state["candidate_kind"]
            self.state["status"] = "model_checked"
            route["research_status"] = "ready_for_review"
            self._decide(route, "review", "Independent model checker found no gap in the complete candidate.")
        elif not target_claim:
            action = "repair" if route["repair_rounds"] < self.config.max_repairs_per_route else "switch_route"
            self._decide(route, action, f"Checker {verdict}: {result['finding']}")
            route["research_status"] = "blocked"
        self._finish_call()
        self._sync_library()
        self._save()
        return verdict == "pass" and not target_claim

    def run(self) -> dict[str, Any]:
        if self.state["status"] in {"model_checked", "unsolved", "round_limit", "needs_human_input"}:
            if self.state["status"] == "model_checked":
                route = self._active_route()
                if route is not None:
                    route["status"] = "completed"
                    route["research_status"] = "ready_for_review"
            self._sync_library()
            self._save()
            return self.state
        while self.state["status"] == "running":
            queued = next((j for j in self.state["experiments"] if j["status"] == "queued"), None)
            if queued:
                self._compute(queued)
            review = self.state["pending_review"]
            if review:
                review_route = next(r for r in self.state["routes"] if r["id"] == review["route_id"])
                claim = next(c for c in self.state["claims"] if c["id"] == review["claim_id"])
                try:
                    self._verify(review_route, claim["argument"], claim["id"], review["output_limit"])
                except Exception as error:
                    self.state["status"] = "blocked"
                    self.state["error"] = f"intermediate check failed: {type(error).__name__}: {error}"
                    break
            # A solver candidate is checkpointed before the checker call. On a
            # resumed run, check that candidate before buying another solver call.
            pending = self.state["candidate_proof"]
            if pending and self.state["candidate_sha256"] not in self.state["checked_candidate_hashes"]:
                route = self._active_route()
                if route is None:
                    self.state["status"] = "blocked"
                    self.state["error"] = "pending candidate has no active route"
                    break
                try:
                    if self._verify(route, pending):
                        route["status"] = "completed"
                        break
                except Exception as error:
                    self.state["status"] = "blocked"
                    self.state["error"] = f"checker validation failed: {type(error).__name__}: {error}"
                    break
                route["last_progress"] = True
                route["last_material_progress"] = True
            if self.state["rounds"] >= self.config.max_rounds:
                self.state["status"] = "round_limit"
                break
            route = self._active_route()
            if route is not None and any(f["route_id"] == route["id"] and f.get("scope", "candidate") == "candidate" for f in self.state["findings"]) and route["repair_rounds"] >= self.config.max_repairs_per_route:
                route["status"] = "repair_limit"
                route["research_status"] = "abandoned"
                self._decide(route, "switch_route", "Bounded checker repair allowance exhausted.")
                self._save()
                continue
            if route is None:
                if len(self.state["routes"]) >= self.config.max_routes:
                    self.state["status"] = "unsolved"
                    break
                route = self._open_route()
            if self._remaining(route) <= 0:
                if not route["extended"] and self.config.extension_minutes > 0 and route["last_material_progress"] and route["next_test"].strip():
                    route["extended"] = True
                    self._decide(route, "extend", f"Material progress and a specific next test: {route['next_test']}")
                    self._save()
                else:
                    route["status"] = "time_limit"
                    route["research_status"] = "abandoned"
                    self._decide(route, "switch_route", "Route time budget exhausted without a justified extension.")
                    self._save()
                    continue
            context = self._solver_context(route)
            repairing = context["working_context"]["repairs_remaining"] is not None
            if context["working_context"]["checkpoint_due"]:
                route["checkpoint_sent"] = True
            timeout = min(self._remaining(route), self.config.max_call_minutes * 60)
            try:
                result = self._call("solver", route, context, timeout)
            except Exception as error:
                if self.state["status"] == "running":
                    self.state["status"] = "blocked"
                    self.state["error"] = f"solver receipt failed: {type(error).__name__}: {error}"
                break
            checkpoint = copy.deepcopy(self.state)
            try:
                if result.get("status") not in {"candidate", "progress", "stalled"}:
                    raise ValueError("invalid solver status")
                for key in ("route_title", "summary", "candidate_proof", "obstruction", "next_test"):
                    if not isinstance(result.get(key), str):
                        raise ValueError(f"invalid solver field: {key}")
                self.state["rounds"] += 1
                route["rounds"] += 1
                if repairing:
                    route["repair_rounds"] += 1
                before_links = len(route["obligation_ids"])
                new_obligations = self._add_obligations(result.get("obligations", []), route["id"])
                new_claims = self._add_claims(result.get("claims"), route["id"])
                focus_id = result.get("focus_obligation_id", "")
                if not isinstance(focus_id, str) or focus_id and focus_id not in {o["id"] for o in self.state["obligations"]}:
                    raise ValueError("invalid focus obligation ID")
                if focus_id:
                    if focus_id not in route["obligation_ids"]:
                        route["obligation_ids"].append(focus_id)
                    route["focus_obligation_id"] = focus_id
                new_route_links = len(route["obligation_ids"]) > before_links
                requests = self._validate_requested(result.get("request_artifact_ids", []))
                new_request = any(item not in route["seen_requested_artifact_ids"] for item in requests)
                route["seen_requested_artifact_ids"].extend(item for item in requests if item not in route["seen_requested_artifact_ids"])
                route["requested_artifact_ids"] = requests
                blocker = self._parse_blocker(result, route)
                before_research_claims = len(self.state["claims"])
                research_progress = self._accept_research(result, route)
                new_claims += len(self.state["claims"]) - before_research_claims
            except ValueError as error:
                self.state = checkpoint
                route = self._active_route()
                self._finish_call(False)
                self.state["status"] = "blocked"
                self.state["error"] = f"invalid solver result: {error}"
                self._save()
                break
            route["title"] = result["route_title"] or route["title"]
            route["summary"] = result["summary"]
            route["obstruction"] = result["obstruction"]
            route["next_test"] = blocker["next_test"] if blocker else result["next_test"]
            old_blocker_key = route["last_blocker_key"]
            blocker_key = _blocker_key(blocker) if blocker else ""
            route["blocker"] = blocker
            route["last_blocker_key"] = blocker_key
            evidence_key = _digest(_normalized(blocker["evidence"])) if blocker and blocker["evidence"].strip() else ""
            new_evidence = bool(evidence_key and evidence_key not in route["seen_evidence_keys"])
            if new_evidence:
                route["seen_evidence_keys"].append(evidence_key)
            changed_blocker = bool(blocker and blocker_key != old_blocker_key and new_evidence and blocker["next_test"].strip())
            route["last_material_progress"] = bool(new_claims or new_obligations or new_route_links or changed_blocker)
            route["last_progress"] = bool(route["last_material_progress"] or new_request or research_progress)
            route["research_status"] = "promising" if route["last_progress"] else "blocked"
            if blocker and blocker["proposed_action"] != "none":
                self._decide(route, blocker["proposed_action"], blocker["reason"] or blocker["failure_point"], blocker_key)
            self._finish_call()
            if route["status"] == "duplicate_route":
                route["research_status"] = "abandoned"
                self._sync_library()
                self._save()
                continue
            if result["status"] == "candidate":
                proof = result["candidate_proof"].strip()
                if not proof:
                    self.state["status"] = "blocked"
                    self.state["error"] = "candidate response had no proof"
                    self._save()
                    break
                proof_digest = _digest(proof)
                self.state["candidate_proof"] = proof
                self.state["candidate_sha256"] = proof_digest
                self.state["candidate_artifact_id"] = self._write_artifact("candidate", proof)
                if self.state["candidate_artifact_id"] not in self.state["candidate_artifact_ids"]:
                    self.state["candidate_artifact_ids"].append(self.state["candidate_artifact_id"])
                self._save()
                if proof_digest not in self.state["checked_candidate_hashes"]:
                    try:
                        if self._verify(route, proof):
                            route["status"] = "completed"
                            break
                    except Exception as error:
                        self.state["status"] = "blocked"
                        self.state["error"] = f"checker validation failed: {type(error).__name__}: {error}"
                        break
                    route["last_progress"] = True  # A new checker finding creates a repair opportunity.
                    route["last_material_progress"] = True
                else:
                    route["last_progress"] = bool(new_claims or new_obligations)
            if blocker and blocker["proposed_action"] == "request_human_input":
                route["status"] = "stalled"
                route["research_status"] = "blocked"
                self.state["status"] = "needs_human_input"
            elif blocker and blocker["proposed_action"] == "switch_route" and result["status"] != "candidate":
                route["status"] = "stalled"
                route["research_status"] = "abandoned"
            elif result["status"] == "stalled" or not route["last_progress"]:
                route["status"] = "stalled"
                route["research_status"] = "blocked"
                self._decide(route, "switch_route", "No new obligation, argument, candidate finding, or evidence for the same blocker.", blocker_key)
            self._sync_library()
            self._save()
        self._sync_library()
        self._save()
        return self.state
