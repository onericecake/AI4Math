from __future__ import annotations

from typing import Any, Optional, Protocol

from .types import ModelResponse, TokenUsage


class LanguageModel(Protocol):
    def complete(self, prompt: str) -> ModelResponse:
        ...


class OpenAIModel:
    """Thin adapter over the OpenAI Responses API."""

    def __init__(
        self,
        model: str,
        max_output_tokens: int = 1800,
        client: Optional[Any] = None,
    ) -> None:
        if client is None:
            try:
                from openai import OpenAI
            except ImportError as error:
                raise RuntimeError(
                    "The OpenAI SDK is not installed. Run: pip install -e ."
                ) from error
            client = OpenAI()
        self.client = client
        self.model = model
        self.max_output_tokens = max_output_tokens

    def complete(self, prompt: str) -> ModelResponse:
        response = self.client.responses.create(
            model=self.model,
            instructions=(
                "You are an expert Lean 4 theorem prover using Mathlib. "
                "Return only the proof body: tactics that go after `by`. "
                "Do not use Markdown fences, sorry, admit, axioms, or prose."
            ),
            input=prompt,
            max_output_tokens=self.max_output_tokens,
            store=False,
        )
        usage = getattr(response, "usage", None)
        token_usage = TokenUsage(
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
            total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
        )
        return ModelResponse(text=response.output_text, usage=token_usage)

