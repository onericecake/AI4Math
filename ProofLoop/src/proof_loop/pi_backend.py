"""Small Pi request adapter for the Codex subscription transport."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from .backend import CHECKER_INSTRUCTIONS, CHECKER_SCHEMA, SOLVER_INSTRUCTIONS, SOLVER_SCHEMA


def _access_token() -> str:
    token = os.environ.get("CODEX_ACCESS_TOKEN")
    if not token:
        codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        auth_path = codex_home / "auth.json"
        if not auth_path.is_file():
            raise RuntimeError("No Codex access token: set CODEX_ACCESS_TOKEN or use file-based Codex login")
        auth = json.loads(auth_path.read_text(encoding="utf-8"))
        token = auth.get("tokens", {}).get("access_token")
    if not token:
        raise RuntimeError("No ChatGPT access token in Codex credentials; sign in with ChatGPT or set CODEX_ACCESS_TOKEN")
    try:
        encoded = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        expiry = claims.get("exp")
        if isinstance(expiry, (int, float)) and expiry <= time.time() + 60:
            raise RuntimeError("Codex access token is expired or expiring; refresh the Codex login before a Pi run")
    except (IndexError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        pass  # Opaque enterprise tokens may have no JWT expiry claim.
    return token


def _pi_usage(raw: dict[str, Any]) -> dict[str, int | None]:
    """Pi's input is fresh input; its cache reads/writes are separate buckets."""
    def count(name: str) -> int | None:
        value = raw.get(name)
        return value if type(value) is int and value >= 0 else None

    fresh, cached, written, output, reasoning = map(count, ("input", "cacheRead", "cacheWrite", "output", "reasoning"))
    total_input = fresh + cached + written if None not in (fresh, cached, written) else None
    return {
        "input_tokens": total_input,
        "cached_tokens": cached,
        "fresh_input_tokens": fresh,
        "cache_write_tokens": written,
        "output_tokens": output,
        "reasoning_tokens": reasoning,
        "visible_output_tokens": output - reasoning if output is not None and reasoning is not None else None,
    }


class PiBackend:
    def __init__(self, model: str, solver_effort: str, checker_effort: str, max_output_tokens: int,
                 package_path: Path | None = None, bun_executable: str | None = None):
        configured_package = package_path or os.environ.get("PROOF_LOOP_PI_PACKAGE")
        if not configured_package:
            raise FileNotFoundError("Set PROOF_LOOP_PI_PACKAGE to an installed @earendil-works/pi-ai directory")
        self.package_path = Path(configured_package).resolve()
        if not (self.package_path / "dist/index.js").is_file():
            raise FileNotFoundError("Pi package missing; set PROOF_LOOP_PI_PACKAGE to an installed @earendil-works/pi-ai directory")
        self.bun = bun_executable or os.environ.get("PROOF_LOOP_BUN") or shutil.which("bun")
        if not self.bun or not shutil.which(self.bun):
            raise FileNotFoundError("Bun missing; install Bun or set PROOF_LOOP_BUN")
        self.model = model
        self.efforts = {"solver": solver_effort, "checker": checker_effort}
        self.max_output_tokens = max_output_tokens
        self.bridge = Path(__file__).with_name("pi_bridge.mjs")

    def call(self, role: str, problem: str, context: dict[str, Any], timeout_seconds: float | None) -> tuple[dict[str, Any], dict[str, int | None]]:
        if role not in self.efforts:
            raise ValueError(f"Unknown role: {role}")
        token = _access_token()
        payload = {
            "package_path": str(self.package_path),
            "token": token,
            "model": self.model,
            "effort": self.efforts[role],
            "max_output_tokens": min(self.max_output_tokens, context.get("review_output_limit", self.max_output_tokens)),
            "timeout_ms": max(1000, int(timeout_seconds * 1000) - 2000) if timeout_seconds is not None else 0,
            "session_id": "proof-loop-" + hashlib.sha256(f"{self.model}\n{role}\n{problem}".encode("utf-8")).hexdigest()[:32],
            "instructions": SOLVER_INSTRUCTIONS if role == "solver" else CHECKER_INSTRUCTIONS,
            "schema": SOLVER_SCHEMA if role == "solver" else CHECKER_SCHEMA,
            "problem": problem,
            "context": [context["stable_context"], context["working_context"]] if role == "solver" else [context],
        }
        env = os.environ.copy()
        proxy = env.get("PROOF_LOOP_PI_PROXY")
        if proxy:
            env.setdefault("HTTPS_PROXY", proxy)
            env.setdefault("HTTP_PROXY", proxy)
        try:
            process = subprocess.run([self.bun, str(self.bridge)], input=json.dumps(payload, ensure_ascii=False),
                                     text=True, capture_output=True, timeout=timeout_seconds, check=False, env=env)
        except subprocess.TimeoutExpired as error:
            raise TimeoutError(f"Pi {role} exceeded {timeout_seconds:.0f}s") from error
        if process.returncode:
            detail = process.stderr[-1000:].replace(token, "[redacted]").strip()
            raise RuntimeError(f"Pi {role} exited {process.returncode}: {detail}")
        try:
            output = json.loads(process.stdout)
        except json.JSONDecodeError as error:
            raise RuntimeError(f"Pi {role} returned invalid JSON") from error
        result = output.get("result")
        if not isinstance(result, dict):
            raise ValueError(f"Pi {role} returned a non-object")
        return result, _pi_usage(output.get("usage") or {})
