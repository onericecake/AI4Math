"""Bounded, opt-in local computations. No unsandboxed fallback."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path


TOOLS = {"matching", "python", "sage", "lean"}


def runtime(tool: str) -> tuple[list[str], list[Path], str]:
    if tool == "python":
        executable = Path(sys.executable).absolute()
        return [str(executable), "-I"], [Path(sys.prefix), Path(sys.base_prefix)], ".py"
    if tool not in TOOLS or tool == "matching":
        raise ValueError("unknown computation tool")
    executable = os.environ.get("PROOF_LOOP_" + tool.upper()) or shutil.which(tool)
    if not executable:
        raise RuntimeError(f"{tool} is not installed; set PROOF_LOOP_{tool.upper()} to its executable")
    path = Path(executable).resolve()
    if path.name == "elan":
        raise RuntimeError("Set PROOF_LOOP_LEAN to an installed toolchain's lean binary, not the elan installer")
    prefix = path.parent.parent
    if prefix in {Path("/"), Path.home(), Path.home().parent}:
        raise RuntimeError("Computation tools must live in a dedicated runtime directory")
    return [str(path)] + (["-python", "-I"] if tool == "sage" else []), [prefix], ".lean" if tool == "lean" else ".py"


def sandbox(command: list[str], roots: list[Path], scratch: Path, source: Path, log: Path) -> list[str]:
    roots = list(dict.fromkeys(p.resolve() for p in roots if p.exists()))
    if sys.platform == "darwin" and Path("/usr/bin/sandbox-exec").exists():
        read_roots = [Path("/usr"), Path("/bin"), Path("/System"), Path("/Library/Developer"), *roots]
        read_rules = " ".join(f"(subpath {json.dumps(str(p))})" for p in read_roots)
        profile = f'''(version 1)
(deny default)
(import "dyld-support.sb")
(allow syscall* mach-bootstrap)
(allow process-exec process-fork sysctl-read)
(allow signal (target self))
(allow file-read-metadata)
(allow file-map-executable {read_rules})
(allow file-read* {read_rules} (subpath {json.dumps(str(scratch))}) (literal {json.dumps(str(source))}) (literal "/dev/null") (literal "/dev/urandom") (literal "/dev/random"))
(allow file-write* (subpath {json.dumps(str(scratch))}) (literal "/dev/null"))
(allow file-write-data (literal {json.dumps(str(log))}))'''
        return ["/usr/bin/sandbox-exec", "-p", profile, *command]
    bwrap = shutil.which("bwrap")
    if sys.platform.startswith("linux") and bwrap:
        args = [bwrap, "--unshare-all", "--die-with-parent", "--new-session", "--proc", "/proc", "--dev", "/dev"]
        for path in dict.fromkeys([Path("/usr"), Path("/bin"), Path("/lib"), Path("/lib64"), *roots]):
            if path.exists():
                args += ["--ro-bind", str(path), str(path)]
        return args + ["--bind", str(scratch), str(scratch), "--ro-bind", str(source), str(source),
                       "--chdir", str(scratch), *command]
    raise RuntimeError("Computation requires macOS sandbox-exec or Linux bubblewrap; execution refused")


def execute(tool: str, code: str, directory: Path, seconds: float) -> dict:
    """The caller journals intent before calling and stores the returned receipt."""
    directory = directory.resolve()
    if tool == "matching":
        from .finite_matching import check_matching
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / "source.json").open("x", encoding="utf-8") as handle:
            handle.write(code)
        result = check_matching(code, seconds)
        with (directory / "output.txt").open("x", encoding="utf-8") as handle:
            handle.write(result["output"])
        return result
    command, roots, suffix = runtime(tool)
    directory.mkdir(parents=True, exist_ok=True)
    scratch = directory / "scratch"
    scratch.mkdir(exist_ok=True)
    source = directory / ("source" + suffix)
    # Exclusive creation prevents accidental replacement of a previous computation.
    with source.open("x", encoding="utf-8") as handle:
        handle.write(code)
    log = directory / "output.txt"
    runtime_executable = command[0]
    command = sandbox([*command, str(source)], roots, scratch, source, log)
    import resource  # Optional computations require a supported Unix sandbox.
    env = {"PATH": os.pathsep.join([str(Path(runtime_executable).parent), "/usr/bin", "/bin"]),
           "TMPDIR": str(scratch), "DOT_SAGE": str(scratch), "LANG": "C.UTF-8"}

    def limits():
        resource.setrlimit(resource.RLIMIT_CPU, (max(1, int(seconds) + 1), max(2, int(seconds) + 2)))
        resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
        resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
        if sys.platform.startswith("linux"):
            resource.setrlimit(resource.RLIMIT_AS, (1024 ** 3, 1024 ** 3))

    start = time.monotonic()
    with log.open("x+b") as output:
        process = subprocess.Popen(command, cwd=scratch, env=env, stdin=subprocess.DEVNULL,
                                   stdout=output, stderr=subprocess.STDOUT, start_new_session=True,
                                   preexec_fn=limits)
        timed_out = False
        try:
            process.wait(timeout=max(0.1, seconds))
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            # Also stop descendants left behind by a script that already returned.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        output.seek(0)
        raw = output.read(12001)
    return {"status": "timed_out" if timed_out else "completed" if process.returncode == 0 else "failed",
            "exit_code": process.returncode, "seconds": round(time.monotonic() - start, 3),
            "output": raw[:12000].decode("utf-8", errors="replace"), "output_truncated": len(raw) > 12000,
            "runtime": runtime_executable,
            "evidence_only": True}
