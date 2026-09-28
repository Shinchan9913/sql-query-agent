"""LLM gateway: builds chat models from config and wires the optional fallback.

The graph asks for a model "shape" (plain, tool-calling, structured output) and
gets a runnable that transparently falls back to the secondary provider.
Fallbacks are applied after the shape because `bind_tools` and
`with_structured_output` aren't available on a `RunnableWithFallbacks`.
"""

import logging
import os
import re
from collections.abc import Callable, Sequence
from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.exceptions import OutputParserException
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable, RunnableLambda
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import ValidationError

from app.config import Settings

logger = logging.getLogger(__name__)


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
            # If both fail, LangChain re-raises the primary's error, so log each
            # failure to keep the fallback's error visible too.
            runnable = runnable.with_listeners(on_error=_log_failure("primary")).with_fallbacks(
                [transform(self.fallback).with_listeners(on_error=_log_failure("fallback"))]
            )
        return runnable


def _log_failure(role: str) -> Callable:
    def log(run: Any) -> None:
        # run.error is the exception repr followed directly by its traceback.
        summary = str(run.error).split("Traceback (most recent call last)")[0].strip()
        logger.warning("%s model failed: %s", role.capitalize(), summary[:300])

    return log


class StructuredOutputError(Exception):
    """The model answered without a valid structured result."""


def _structured_output(model: BaseChatModel, schema: type) -> Runnable:
    if model._llm_type.startswith("chat-google"):
        runnable = model.with_structured_output(schema)  # Gemini's native JSON-schema mode

        def require(result: Any) -> Any:
            if result is None:
                raise StructuredOutputError(f"model returned no {schema.__name__}")
            return result

        runnable = runnable | RunnableLambda(require)
    else:
        # Portable path: force a tool call and parse its arguments. Avoids
        # provider-specific modes (e.g. NIM's `guided_json`, which hosted NVIDIA
        # endpoints reject) and works with any model that supports tool calling.
        tool_name = convert_to_openai_tool(schema)["function"]["name"]
        runnable = model.bind_tools([schema], tool_choice="required") | RunnableLambda(
            lambda message: _parse_tool_output(message, schema, tool_name)
        )

    # Models occasionally return nothing usable; one retry usually fixes it.
    # Other errors (rate limits, timeouts) go straight to the fallback model.
    return runnable.with_retry(
        retry_if_exception_type=(StructuredOutputError,), stop_after_attempt=2
    )


_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def _parse_tool_output(message: AIMessage, schema: type, tool_name: str) -> Any:
    for call in message.tool_calls:
        if call["name"] == tool_name:
            try:
                return schema.model_validate(call["args"])
            except ValidationError as e:
                raise StructuredOutputError(f"invalid {tool_name} arguments: {e}") from e

    # Some models (e.g. gpt-oss) sometimes ignore `tool_choice` and write the tool
    # arguments as JSON text instead. Accept it if it validates against the schema.
    match = _JSON_OBJECT.search(message.text)
    if match:
        try:
            return schema.model_validate_json(match.group(0))
        except ValidationError:
            pass
    raise StructuredOutputError(f"model returned no {tool_name}")


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
