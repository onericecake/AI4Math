from __future__ import annotations

import re
from typing import List, Optional, Tuple

from .types import CompilerResult, ErrorCategory, FailureFeedback


_LOCATION_PATTERNS = (
    re.compile(r"(?:^|\n)[^\n]*?:(\d+):(\d+):\s*(?:error:)?", re.MULTILINE),
    re.compile(r"line\s+(\d+)(?:,\s*column\s+(\d+))?", re.IGNORECASE),
)

_CATEGORY_PATTERNS = (
    (ErrorCategory.FORBIDDEN_PLACEHOLDER, re.compile(r"declaration uses ['\"]?(?:sorry|admit)|\b(?:sorry|admit)\b", re.I)),
    (ErrorCategory.SYNTAX_ERROR, re.compile(r"unexpected token|unexpected end of input|parser error|invalid syntax", re.I)),
    (ErrorCategory.UNKNOWN_IDENTIFIER, re.compile(r"unknown identifier|invalid field notation|unknown constant", re.I)),
    (ErrorCategory.TYPE_MISMATCH, re.compile(r"type mismatch|application type mismatch|failed to synthesize|has type\s+.+but is expected", re.I | re.S)),
    (ErrorCategory.TACTIC_FAILURE, re.compile(r"unknown tactic|tactic ['\"`]?.+?['\"`]? failed|tactic .* failed|linarith failed|omega could not prove|simp made no progress", re.I)),
    (ErrorCategory.UNSOLVED_GOALS, re.compile(r"unsolved goals?|no goals to be solved", re.I)),
)


class LeanErrorParser:
    """Turn noisy Lean diagnostics into a compact repair signal."""

    def parse(self, result: CompilerResult, source: str = "") -> FailureFeedback:
        if result.timed_out:
            return FailureFeedback(
                category=ErrorCategory.TIMEOUT,
                message="Lean verification exceeded the configured timeout.",
            )

        output = result.output
        category = ErrorCategory.OTHER
        for candidate, pattern in _CATEGORY_PATTERNS:
            if pattern.search(output):
                category = candidate
                break

        line, column = self._location(output)
        message = self._primary_message(output)
        goal = self._goal(output)
        excerpt = self._excerpt(source, line)
        return FailureFeedback(category, message, line, column, goal, excerpt)

    @staticmethod
    def _location(output: str) -> Tuple[Optional[int], Optional[int]]:
        for pattern in _LOCATION_PATTERNS:
            match = pattern.search(output)
            if match:
                line = int(match.group(1))
                column = int(match.group(2)) if match.lastindex and match.lastindex >= 2 and match.group(2) else None
                return line, column
        return None, None

    @staticmethod
    def _primary_message(output: str) -> str:
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        if not lines:
            return "Lean exited unsuccessfully without diagnostics."
        error_index = next((i for i, line in enumerate(lines) if "error:" in line.lower()), 0)
        selected: List[str] = lines[error_index : error_index + 40]
        return "\n".join(selected)[:6000]

    @staticmethod
    def _goal(output: str) -> Optional[str]:
        lines = output.splitlines()
        starts = [i for i, line in enumerate(lines) if re.search(r"(?:^|\s)⊢\s", line)]
        if not starts:
            return None
        chunks = []
        for index, start in enumerate(starts):
            end = starts[index + 1] if index + 1 < len(starts) else len(lines)
            collected = lines[max(0, start - 6) : end]
            chunks.append("\n".join(line.rstrip() for line in collected).strip())
        return "\n\n".join(chunk for chunk in chunks if chunk)[:6000]

    @staticmethod
    def _excerpt(source: str, line: Optional[int], radius: int = 2) -> Optional[str]:
        if not source or not line:
            return None
        lines = source.splitlines()
        start = max(0, line - radius - 1)
        end = min(len(lines), line + radius)
        return "\n".join(
            "{0:>4} | {1}".format(index + 1, lines[index])
            for index in range(start, end)
        )
