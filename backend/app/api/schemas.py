"""Request and response models for the HTTP API."""

from typing import Any

from pydantic import BaseModel, Field

THREAD_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"


class ChatRequest(BaseModel):
    thread_id: str = Field(pattern=THREAD_ID_PATTERN)
    # Hard cap on payload size; the agent's input guard applies the user-facing limit.
    message: str = Field(max_length=20_000)


class ExecuteRequest(BaseModel):
    sql: str = Field(max_length=20_000)


class ExecuteResponse(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    elapsed_ms: float
    warnings: list[str]


class ThreadSummary(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    running: bool = False


class ThreadMessage(BaseModel):
    role: str
    content: str
    response: dict[str, Any] | None = None


class ThreadDetail(ThreadSummary):
    messages: list[ThreadMessage]
