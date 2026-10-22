"""Codex CLI adapter for local solver and checker calls."""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any

from .backend import CHECKER_INSTRUCTIONS, CHECKER_SCHEMA, SOLVER_INSTRUCTIONS, SOLVER_SCHEMA


def _field(data: dict[str, Any], *names: str) -> int | None:
    for name in names:
        value = data.get(name)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def codex_usage(events: str) -> dict[str, int | None]:
    """Read only reported usage; a missing category remains unknown."""
    raw = None
    for line in events.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
            raw = event["usage"]
    if raw is None:
        return {name: None for name in ("input_tokens", "cached_tokens", "fresh_input_tokens", "output_tokens", "reasoning_tokens", "visible_output_tokens", "cache_write_tokens")}
    details_in = raw.get("input_tokens_details") or {}
    details_out = raw.get("output_tokens_details") or {}
    total_in = _field(raw, "input_tokens")
    cached = _field(raw, "cached_input_tokens", "cached_tokens")
    if cached is None:
        cached = _field(details_in, "cached_tokens")
    total_out = _field(raw, "output_tokens")
    reasoning = _field(raw, "reasoning_output_tokens", "reasoning_tokens")
    if reasoning is None:
        reasoning = _field(details_out, "reasoning_tokens")
    cache_write = _field(raw, "cache_write_input_tokens", "cache_write_tokens")
    if cache_write is None:
        cache_write = _field(details_in, "cache_write_tokens")
    return {
        "input_tokens": total_in,
        "cached_tokens": cached,
        "fresh_input_tokens": total_in - cached if total_in is not None and cached is not None else None,
        "output_tokens": total_out,
        "reasoning_tokens": reasoning,
        "visible_output_tokens": total_out - reasoning if total_out is not None and reasoning is not None else None,
        "cache_write_tokens": cache_write,
    }


class CodexCLIBackend:
    def __init__(self, model: str, solver_effort: str, checker_effort: str, workdir: Path, executable: str | None = None):
        self.executable = executable or shutil.which("codex")
        if not self.executable:
            raise FileNotFoundError("codex CLI is not on PATH")
        self.model = model
        self.efforts = {"solver": solver_effort, "checker": checker_effort}
        self.workdir = workdir.resolve()
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.call_number = len(list(self.workdir.glob("call-*.jsonl")))
        self._call_lock = threading.Lock()

    def call(self, role: str, problem: str, context: dict[str, Any], timeout_seconds: float | None) -> tuple[dict[str, Any], dict[str, int | None]]:
        if role not in self.efforts:
            raise ValueError(f"unknown role: {role}")
        with self._call_lock:
            self.call_number += 1
            stem = f"call-{self.call_number:03d}-{role}"
        schema = SOLVER_SCHEMA if role == "solver" else CHECKER_SCHEMA
        instructions = SOLVER_INSTRUCTIONS if role == "solver" else CHECKER_INSTRUCTIONS
        schema_path = self.workdir / f"{stem}-schema.json"
        output_path = self.workdir / f"{stem}-output.json"
        schema_path.write_text(json.dumps(schema, ensure_ascii=False), encoding="utf-8")
        if role == "solver":
            parts = [context["stable_context"], context["working_context"]]
        else:
            parts = [context]
        prompt = "\n\n".join([
            instructions,
            "Do not use shell tools or web search. Return only the requested JSON object.",
            "Exact problem and completion criteria:\n" + problem,
            *[json.dumps(part, ensure_ascii=False, sort_keys=True) for part in parts],
        ])
        command = [
            self.executable, "exec", "--ephemeral", "--skip-git-repo-check",
            "--ignore-user-config", "--ignore-rules", "--sandbox", "read-only",
            "--model", self.model, "--config", f'model_reasoning_effort="{self.efforts[role]}"',
            "--config", 'web_search="disabled"',
            "--config", "features.shell_tool=false",
            "--config", "features.apps=false",
            "--config", "features.multi_agent=false",
            "--cd", str(self.workdir),
            "--output-schema", str(schema_path), "--output-last-message", str(output_path),
            "--json", "-",
        ]
        try:
            process = subprocess.run(command, input=prompt, text=True, capture_output=True, cwd=self.workdir, timeout=timeout_seconds, check=False)
        except subprocess.TimeoutExpired as error:
            raise TimeoutError(f"Codex {role} exceeded {timeout_seconds:.0f}s") from error
        (self.workdir / f"{stem}.jsonl").write_text(process.stdout, encoding="utf-8")
        (self.workdir / f"{stem}.stderr.txt").write_text(process.stderr, encoding="utf-8")
        if process.returncode:
            raise RuntimeError(f"Codex {role} exited {process.returncode}: {process.stderr[-1000:]}")
        if not output_path.exists():
            raise RuntimeError(f"Codex {role} did not write a final response")
        result = json.loads(output_path.read_text(encoding="utf-8"))
        if not isinstance(result, dict):
            raise ValueError(f"Codex {role} returned a non-object")
        return result, codex_usage(process.stdout)
