"""Server-sent events for a chat turn.

Event types:
  step      {node, label, detail?}  a graph node finished
  token     {text}                  a chunk of the explanation as the model writes it
  response  {...}                   the final response payload
  error     {message}               the turn failed or was stopped

Errors and stops are also written to the conversation, so a reloaded thread
shows them like any other answer.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph.state import CompiledStateGraph

logger = logging.getLogger(__name__)

KEEPALIVE_SECONDS = 15

STEP_LABELS = {
    "input_guard": "Checking request",
    "classify_intent": "Understanding your request",
    "reject": "Checking scope",
    "clarify": "Preparing a question",
    "retrieve_schema": "Loading schema",
    "answer_schema": "Reading the schema",
    "check_user_sql": "Checking your SQL",
    "generate_sql": "Writing SQL",
    "run_data_tools": "Looking up data",
    "validate_sql": "Validating SQL",
    "cannot_answer": "Checking the schema",
    "generation_failed": "Validating SQL",
    "optimize_sql": "Analyzing performance",
    "explain": "Writing explanation",
}


def sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


async def chat_events(graph: CompiledStateGraph, thread_id: str, message: str) -> AsyncIterator[str]:
    config = {"configurable": {"thread_id": thread_id}}
    seen_lookups = 0
    try:
        async for mode, chunk in graph.astream(
            {"messages": [HumanMessage(message)]}, config, stream_mode=["updates", "messages"]
        ):
            if mode == "messages":
                token, metadata = chunk
                if metadata.get("langgraph_node") == "explain" and token.text:
                    yield sse("token", {"text": token.text})
                continue

            for node, values in chunk.items():
                if node not in STEP_LABELS:
                    continue
                values = values or {}
                step = {"node": node, "label": STEP_LABELS[node]}
                if node == "run_data_tools":
                    new = values.get("tool_log", [])[seen_lookups:]
                    seen_lookups += len(new)
                    step["detail"] = [_describe_lookup(e) for e in new]
                elif node == "validate_sql" and values.get("validation_errors"):
                    step["detail"] = "Found problems, revising the query"
                elif node == "classify_intent":
                    step["detail"] = values.get("intent")
                yield sse("step", step)

        state = await graph.aget_state(config)
        yield sse("response", {**state.values["response"], "thread_id": thread_id})
    except Exception as e:
        logger.exception("Chat turn failed")
        message = _error_message(e)
        await record_error(graph, thread_id, message, reason="llm_error")
        yield sse("error", {"message": message})


async def record_error(graph: CompiledStateGraph, thread_id: str, message: str, reason: str) -> None:
    """Append a failed or stopped turn to the conversation as an assistant message."""
    response = {"type": "error", "reason": reason, "message": message}
    try:
        await graph.aupdate_state(
            {"configurable": {"thread_id": thread_id}},
            {"messages": [AIMessage(content=message, additional_kwargs={"response": response})]},
            as_node="respond",
        )
    except Exception:
        logger.exception("Could not record error in thread %s", thread_id)


def _error_message(error: Exception) -> str:
    text = f"{type(error).__name__} {error}"
    if "RateLimit" in text or "429" in text or "RESOURCE_EXHAUSTED" in text:
        return (
            "The language model's usage limit has been reached (free-tier quota). "
            "Wait a bit and try again, or configure a fallback model."
        )
    if "401" in text or "403" in text or "PERMISSION_DENIED" in text or "API key" in text:
        return "The language model rejected the API key. Check the key in .env."
    return "Something went wrong while contacting the language model. Please try again."


def _describe_lookup(entry: dict) -> str:
    args = entry.get("args", {})
    if entry["tool"] == "get_column_values":
        target = f"values of {args.get('table')}.{args.get('column')}"
        if args.get("search"):
            target += f" matching '{args['search']}'"
    else:
        target = "a quick probe query"
    outcome = entry.get("error") or entry.get("summary", "")
    return f"Checked {target}: {outcome}"


async def with_keepalive(events: AsyncIterator[str], interval: float = KEEPALIVE_SECONDS) -> AsyncIterator[str]:
    """Interleave SSE comment pings so proxies don't close an idle stream during slow LLM calls."""
    queue: asyncio.Queue = asyncio.Queue()
    done = object()

    async def pump() -> None:
        try:
            async for event in events:
                await queue.put(event)
        finally:
            await queue.put(done)

    task = asyncio.create_task(pump())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), interval)
            except TimeoutError:
                yield ": ping\n\n"
                continue
            if item is done:
                break
            yield item
    finally:
        task.cancel()
