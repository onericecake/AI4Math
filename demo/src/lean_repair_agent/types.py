from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class FeedbackMode(str, Enum):
    """The independent variable used in proof-repair experiments."""

    SINGLE = "single"
    RETRY = "retry"
    RAW = "raw"
    STRUCTURED = "structured"


class ErrorCategory(str, Enum):
    SYNTAX_ERROR = "syntax_error"
    UNKNOWN_IDENTIFIER = "unknown_identifier"
    TYPE_MISMATCH = "type_mismatch"
    UNSOLVED_GOALS = "unsolved_goals"
    TACTIC_FAILURE = "tactic_failure"
    TIMEOUT = "timeout"
    FORBIDDEN_PLACEHOLDER = "forbidden_placeholder"
    OTHER = "other"


@dataclass(frozen=True)
class LeanProblem:
    """A theorem to prove.

    ``statement`` can be a declaration without a proof, or a complete source
    template containing ``{{PROOF}}``. The model always supplies a proof body
    (the tactics after ``by``).
    """

    id: str
    statement: str
    imports: List[str] = field(default_factory=lambda: ["Mathlib"])

    def render(self, proof: str) -> str:
        body = _indent_proof(proof)
        if "{{PROOF}}" in self.statement:
            declaration = self.statement.replace("{{PROOF}}", body)
        else:
            statement = self.statement.rstrip()
            if statement.endswith(":= by") or statement.endswith(" by"):
                declaration = statement + "\n" + body
            elif statement.endswith(":="):
                declaration = statement + " by\n" + body
            else:
                declaration = statement + " := by\n" + body

        imports = "\n".join("import " + item for item in self.imports)
        return imports + "\n\n" + declaration + "\n"

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "LeanProblem":
        return cls(
            id=str(value["id"]),
            statement=str(value["statement"]),
            imports=list(value.get("imports", ["Mathlib"])),
        )


def _indent_proof(proof: str) -> str:
    lines = proof.strip().splitlines() or ["-- model returned an empty proof"]
    return "\n".join("  " + line if line.strip() else "" for line in lines)


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.total_tokens + other.total_tokens,
        )


@dataclass(frozen=True)
class ModelResponse:
    text: str
    usage: TokenUsage = TokenUsage()


@dataclass(frozen=True)
class CompilerResult:
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False

    @property
    def output(self) -> str:
        return "\n".join(part for part in (self.stdout, self.stderr) if part).strip()


@dataclass(frozen=True)
class FailureFeedback:
    category: ErrorCategory
    message: str
    line: Optional[int] = None
    column: Optional[int] = None
    goal: Optional[str] = None
    source_excerpt: Optional[str] = None


@dataclass(frozen=True)
class AttemptRecord:
    attempt: int
    proof: str
    prompt: str
    compiler: CompilerResult
    usage: TokenUsage
    feedback: Optional[FailureFeedback] = None

    def to_dict(self, include_prompt: bool = False) -> Dict[str, Any]:
        value = asdict(self)
        value["feedback"] = asdict(self.feedback) if self.feedback else None
        if self.feedback:
            value["feedback"]["category"] = self.feedback.category.value
        if not include_prompt:
            value.pop("prompt", None)
        return value


@dataclass(frozen=True)
class SolveResult:
    problem_id: str
    mode: FeedbackMode
    solved: bool
    proof: Optional[str]
    attempts: List[AttemptRecord]

    @property
    def token_usage(self) -> TokenUsage:
        total = TokenUsage()
        for attempt in self.attempts:
            total = total + attempt.usage
        return total

    def to_dict(self, include_prompts: bool = False) -> Dict[str, Any]:
        return {
            "problem_id": self.problem_id,
            "mode": self.mode.value,
            "solved": self.solved,
            "proof": self.proof,
            "attempt_count": len(self.attempts),
            "token_usage": asdict(self.token_usage),
            "attempts": [a.to_dict(include_prompts) for a in self.attempts],
        }
