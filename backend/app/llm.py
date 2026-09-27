"""LLM gateway: builds chat models from config and wires the optional fallback.

The graph asks for a model "shape" (plain, tool-calling, structured output) and
gets a runnable that transparently falls back to the secondary provider.
Fallbacks are applied after the shape because `bind_tools` and
`with_structured_output` aren't available on a `RunnableWithFallbacks`.
"""

import os
from collections.abc import Callable, Sequence
from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.exceptions import OutputParserException
from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers.openai_tools import PydanticToolsParser
from langchain_core.runnables import Runnable, RunnableLambda

from app.config import Settings


class LLM:
    def __init__(self, primary: BaseChatModel, fallback: BaseChatModel | None = None):
        self.primary = primary
        self.fallback = fallback

    def plain(self) -> Runnable:
        return self._shape(lambda m: m)

    def with_tools(self, tools: Sequence[Any]) -> Runnable:
        return self._shape(lambda m: m.bind_tools(tools))

    def structured(self, schema: type) -> Runnable:
        return self._shape(lambda m: _structured_output(m, schema))

    def _shape(self, transform: Callable[[BaseChatModel], Runnable]) -> Runnable:
        runnable = transform(self.primary)
        if self.fallback is not None:
            runnable = runnable.with_fallbacks([transform(self.fallback)])
        return runnable


class StructuredOutputError(Exception):
    """The model answered without the required structured result."""


def _structured_output(model: BaseChatModel, schema: type) -> Runnable:
    if model._llm_type.startswith("chat-google"):
        runnable = model.with_structured_output(schema)  # Gemini's native JSON-schema mode
    else:
        # Portable path: force a tool call and parse its arguments. Avoids
        # provider-specific modes (e.g. NIM's `guided_json`, which hosted NVIDIA
        # endpoints reject) and works with any model that supports tool calling.
        runnable = model.bind_tools([schema], tool_choice="required") | PydanticToolsParser(
            tools=[schema], first_tool_only=True
        )

    def require(result: Any) -> Any:
        if result is None:
            raise StructuredOutputError(f"model returned no {schema.__name__}")
        return result

    # Smaller models occasionally skip the tool call; one retry usually fixes it.
    # Other errors (rate limits, timeouts) go straight to the fallback model.
    return (runnable | RunnableLambda(require)).with_retry(
        retry_if_exception_type=(StructuredOutputError, OutputParserException), stop_after_attempt=2
    )


# Environment variables each provider reads its API key from (any one is enough).
_PROVIDER_KEYS = {
    "google_genai": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    "nvidia": ("NVIDIA_API_KEY",),
}


class LLMConfigError(Exception):
    pass


def create_llm(settings: Settings) -> LLM:
    def build(model: str) -> BaseChatModel:
        provider = model.split(":", 1)[0] if ":" in model else ""
        keys = _PROVIDER_KEYS.get(provider, ())
        if keys and not any(os.environ.get(k) for k in keys):
            raise LLMConfigError(f"set {keys[0]} in .env to use {model}")
        return init_chat_model(
            model, temperature=settings.llm_temperature, timeout=settings.llm_timeout_seconds
        )

    fallback = build(settings.llm_fallback_model) if settings.llm_fallback_model else None
    return LLM(build(settings.llm_model), fallback)
