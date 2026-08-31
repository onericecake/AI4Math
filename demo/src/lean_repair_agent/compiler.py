from __future__ import annotations

import shlex
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional, Sequence, Union

from .types import CompilerResult


class LeanNotFoundError(RuntimeError):
    pass


class LeanCompiler:
    """Verify generated source with a local Lean 4 executable."""

    def __init__(
        self,
        project_dir: Optional[Union[str, Path]] = None,
        command: Optional[Union[str, Sequence[str]]] = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.project_dir = Path(project_dir).resolve() if project_dir else None
        if isinstance(command, str):
            self.command = shlex.split(command)
        elif command:
            self.command = list(command)
        elif self.project_dir and (self.project_dir / "lakefile.toml").exists():
            self.command = ["lake", "env", "lean"]
        elif self.project_dir and (self.project_dir / "lakefile.lean").exists():
            self.command = ["lake", "env", "lean"]
        else:
            self.command = ["lean"]
        self.timeout_seconds = timeout_seconds

    def check(self, source: str) -> CompilerResult:
        executable = self.command[0]
        if shutil.which(executable) is None:
            raise LeanNotFoundError(
                "Could not find '{0}' on PATH. Install Lean 4/mathlib or pass "
                "--lean-command with the verifier command.".format(executable)
            )

        started = time.monotonic()
        path = ""
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", suffix=".lean", delete=False
            ) as handle:
                handle.write(source)
                path = handle.name

            completed = subprocess.run(
                self.command + [path],
                cwd=str(self.project_dir) if self.project_dir else None,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
            return CompilerResult(
                success=completed.returncode == 0,
                exit_code=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
                duration_seconds=time.monotonic() - started,
            )
        except subprocess.TimeoutExpired as error:
            return CompilerResult(
                success=False,
                exit_code=124,
                stdout=_decode_timeout_stream(error.stdout),
                stderr=_decode_timeout_stream(error.stderr),
                duration_seconds=time.monotonic() - started,
                timed_out=True,
            )
        finally:
            if path:
                Path(path).unlink(missing_ok=True)


def _decode_timeout_stream(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)

