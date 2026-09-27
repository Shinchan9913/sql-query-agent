"""A scripted chat model for testing the graph without a real LLM."""

import itertools
from collections.abc import Sequence
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import PrivateAttr

_ids = itertools.count(1)


class ScriptedChatModel(BaseChatModel):
    """Returns the scripted replies in order and records every prompt it receives.

    Works with `bind_tools` and LangChain's default `with_structured_output`,
    which reads the structured result from a tool call.
    """

    replies: list[AIMessage]
    _calls: list[list[BaseMessage]] = PrivateAttr(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    @property
    def calls(self) -> list[list[BaseMessage]]:
        return self._calls

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any):
        return self

    def _generate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs) -> ChatResult:
        self._calls.append(list(messages))
        if not self.replies:
            raise AssertionError(f"Unexpected LLM call #{len(self._calls)}")
        return ChatResult(generations=[ChatGeneration(message=self.replies.pop(0))])


def text(content: str) -> AIMessage:
    return AIMessage(content=content)


def tool_call(name: str, **args: Any) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call_{next(_ids)}"}])


def classify(intent: str, task: str = "", user_sql: str | None = None, clarification: str | None = None) -> AIMessage:
    return tool_call(
        "IntentClassification",
        intent=intent, task=task, user_sql=user_sql, clarification_question=clarification,
    )


def submit(sql: str, assumptions: list[str] | None = None, notes: list[str] | None = None) -> AIMessage:
    return tool_call("submit_sql", sql=sql, assumptions=assumptions or [], notes=notes or [])
