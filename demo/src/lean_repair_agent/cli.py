from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import List, Optional

from .agent import MathAgent
from .compiler import LeanCompiler, LeanNotFoundError
from .evaluation import evaluate_modes, load_jsonl, summarize, write_results
from .llm import OpenAIModel
from .types import FeedbackMode, LeanProblem


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Lean 4 structured proof-repair agent")
    parser.add_argument("--model", default=os.environ.get("OPENAI_MODEL", "gpt-5.2"))
    parser.add_argument("--project-dir", type=Path)
    parser.add_argument("--lean-command", help="Verifier command, for example 'lake env lean'")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--max-attempts", type=int, default=3)

    commands = parser.add_subparsers(dest="command", required=True)
    solve = commands.add_parser("solve", help="Solve one JSON problem")
    solve.add_argument("problem", type=Path)
    solve.add_argument("--mode", choices=[m.value for m in FeedbackMode], default="structured")

    run_eval = commands.add_parser("evaluate", help="Evaluate one or more modes on JSONL")
    run_eval.add_argument("dataset", type=Path)
    run_eval.add_argument(
        "--modes",
        nargs="+",
        choices=[m.value for m in FeedbackMode],
        default=[m.value for m in FeedbackMode],
    )
    run_eval.add_argument("--output-dir", type=Path, default=Path("results"))
    return parser


def _make_agent(args: argparse.Namespace) -> MathAgent:
    model = OpenAIModel(args.model)
    compiler = LeanCompiler(args.project_dir, args.lean_command, args.timeout)
    return MathAgent(model, compiler, args.max_attempts)


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        agent = _make_agent(args)
        if args.command == "solve":
            problem = LeanProblem.from_dict(json.loads(args.problem.read_text(encoding="utf-8")))
            result = agent.solve(problem, FeedbackMode(args.mode))
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
            return 0 if result.solved else 1

        problems = load_jsonl(args.dataset)
        modes = [FeedbackMode(mode_name) for mode_name in args.modes]
        comparison = evaluate_modes(agent, problems, modes)
        for mode in modes:
            results = comparison[mode]
            summary = summarize(results, mode)
            destination = args.output_dir / (mode.value + ".json")
            write_results(destination, summary, results)
            print(json.dumps(summary.to_dict(), ensure_ascii=False))
        return 0
    except (LeanNotFoundError, FileNotFoundError, ValueError) as error:
        print("error: {0}".format(error))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
