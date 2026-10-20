"""Command-line entry point for Proof Loop."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .backend import OpenAIBackend
from .codex_backend import CodexCLIBackend
from .pi_backend import PiBackend
from .runner import Config, Runner


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bounded mathematical exploration with independent model checking")
    parser.add_argument("problem", type=Path, help="Markdown file with the exact problem and completion criteria")
    parser.add_argument("--output-dir", required=True, type=Path, help="Directory for state.json and report.md")
    parser.add_argument("--model", required=True, help="OpenAI model available to your account")
    parser.add_argument("--backend", choices=("api", "codex", "codex-cli"), default="api", help="Model runtime; codex uses Pi requests (default: api)")
    parser.add_argument("--solver-effort", default="high")
    parser.add_argument("--checker-effort", default="high")
    parser.add_argument("--route-hours", type=float, default=2.0)
    parser.add_argument("--extension-minutes", type=float, default=30.0)
    parser.add_argument("--max-call-minutes", type=float, default=30.0)
    parser.add_argument("--max-routes", type=int, default=2)
    parser.add_argument("--max-rounds", type=int, default=8)
    parser.add_argument("--max-repairs-per-route", type=int, default=1, help="Solver revisions after a checker rejection on each route (default: 1)")
    parser.add_argument("--max-output-tokens", type=int, default=25000)
    parser.add_argument("--library-dir", type=Path, help="Optional shared file library for reuse across problems")
    parser.add_argument("--library-limit", type=int, default=5, help="Maximum relevant records imported at run start")
    parser.add_argument("--exploration-share", type=float, default=0.85, help="Soft solver share of output tokens for admitting optional lemma checks; final checks always run")
    parser.add_argument("--max-lemma-checks", type=int, default=2, help="Maximum optional pivotal-lemma reviews")
    parser.add_argument("--tools", default="", help="Opt-in computations: comma-separated python,sage,lean; requires an OS sandbox")
    parser.add_argument("--max-experiments", type=int, default=8)
    parser.add_argument("--experiment-seconds", type=float, default=30, help="Wall cap per local computation (at most 300)")
    parser.add_argument("--resume", action="store_true", help="Continue a checkpoint with the same problem and settings")
    parser.add_argument("--human-note", help="On resume, answer a paused route's request for human input")
    args = parser.parse_args(argv)
    if args.human_note and not args.resume:
        parser.error("--human-note requires --resume")
    config = Config(
        model=args.model,
        backend=args.backend,
        solver_effort=args.solver_effort,
        checker_effort=args.checker_effort,
        route_hours=args.route_hours,
        extension_minutes=args.extension_minutes,
        max_call_minutes=args.max_call_minutes,
        max_routes=args.max_routes,
        max_rounds=args.max_rounds,
        max_repairs_per_route=args.max_repairs_per_route,
        max_output_tokens=args.max_output_tokens,
        library_limit=args.library_limit,
        exploration_share=args.exploration_share,
        max_lemma_checks=args.max_lemma_checks,
        tools=args.tools,
        max_experiments=args.max_experiments,
        experiment_seconds=args.experiment_seconds,
    )
    try:
        if args.backend == "codex-cli":
            backend = CodexCLIBackend(config.model, config.solver_effort, config.checker_effort, args.output_dir / "codex-calls")
        elif args.backend == "codex":
            backend = PiBackend(config.model, config.solver_effort, config.checker_effort, config.max_output_tokens)
        else:
            backend = OpenAIBackend(config.model, config.solver_effort, config.checker_effort, config.max_output_tokens)
        runner = Runner(args.problem, args.output_dir, config, backend, resume=args.resume, library_dir=args.library_dir)
        if args.human_note:
            runner.resume_with_human_note(args.human_note)
        state = runner.run()
    except Exception as error:
        print(f"proof-loop: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"status": state["status"], "accepted_kind": state["accepted_kind"],
                      "partial_result_count": len(state["claims"]), "rounds": state["rounds"],
                      "report": str(runner.report_path), "research_state": str(runner.output_dir / "research-state.md"),
                      "library_error": state["library_error"]}, ensure_ascii=False))
    if state["library_error"]:
        return 2
    if state["status"] == "model_checked":
        return 0
    return 2 if state["status"] == "blocked" else 1


if __name__ == "__main__":
    raise SystemExit(main())
