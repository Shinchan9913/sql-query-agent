"""HTTP API: `uvicorn app.api.main:app`."""

import base64
import binascii
import logging
import re
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.agent import load_catalog
from app.api.schemas import (
    THREAD_ID_PATTERN,
    ChatRequest,
    ExecuteRequest,
    ExecuteResponse,
    ThreadDetail,
    ThreadMessage,
    ThreadSummary,
)
from app.api.streaming import chat_events, record_error, sse, with_keepalive
from app.api.threads import ThreadStore
from app.api.turns import TurnInProgressError, TurnManager
from app.config import REPO_ROOT, Settings, get_settings
from app.db.connection import QueryTimeoutError
from app.graph.builder import build_graph
from app.llm import LLM, create_llm
from app.runner.runner import QueryRejectedError, execute_query

logger = logging.getLogger(__name__)

FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def create_app(settings: Settings | None = None, llm: LLM | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        data_dir = settings.resolved_data_dir
        data_dir.mkdir(parents=True, exist_ok=True)

        app.state.catalog = load_catalog(settings)
        app.state.threads = ThreadStore(data_dir / "threads.db")
        await app.state.threads.init()
        app.state.turns = TurnManager()

        async with AsyncSqliteSaver.from_conn_string(str(data_dir / "checkpoints.db")) as checkpointer:
            app.state.graph, app.state.llm_error = None, None
            try:
                app.state.graph = build_graph(
                    llm or create_llm(settings),
                    app.state.catalog,
                    settings.resolved_database_path,
                    settings,
                    checkpointer,
                )
            except Exception as e:  # typically a missing API key; keep serving schema/execute
                logger.error("LLM unavailable: %s", e)
                app.state.llm_error = str(e).splitlines()[0]
            yield
            await app.state.turns.shutdown()

    app = FastAPI(title="SQL Query Agent", lifespan=lifespan)
    if settings.app_password:
        password = settings.app_password

        @app.middleware("http")
        async def require_password(request: Request, call_next):
            # The health check stays open so the host can monitor the service.
            if request.url.path == "/api/health" or _password_matches(request, password):
                return await call_next(request)
            return Response(
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="SQL Query Agent", charset="UTF-8"'},
            )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type"],
    )

    @app.get("/api/health")
    async def health():
        return {
            "status": "ok",
            "llm_ready": app.state.graph is not None,
            "llm_error": app.state.llm_error,
            "model": settings.llm_model,
            "fallback_model": settings.llm_fallback_model,
        }

    @app.post("/api/chat")
    async def chat(request: ChatRequest):
        if app.state.graph is None:
            message = f"The language model isn't configured: {app.state.llm_error}"
            return StreamingResponse(
                iter([sse("error", {"message": message})]),
                media_type="text/event-stream",
                headers=SSE_HEADERS,
            )
        graph, thread_id = app.state.graph, request.thread_id

        async def on_cancel() -> str:
            await record_error(graph, thread_id, "Stopped.", reason="stopped")
            return sse("error", {"message": "Stopped."})

        try:
            # The turn runs in the background, so it survives the client disconnecting.
            turn = app.state.turns.start(thread_id, chat_events(graph, thread_id, request.message), on_cancel)
        except TurnInProgressError:
            return JSONResponse(
                status_code=409,
                content={"detail": "Still working on the previous message in this conversation."},
            )
        await app.state.threads.touch(thread_id, request.message)
        return StreamingResponse(
            with_keepalive(turn.subscribe()), media_type="text/event-stream", headers=SSE_HEADERS
        )

    @app.get("/api/threads/{thread_id}/events")
    async def turn_events(thread_id: str):
        """Re-attach to a running turn: replays its events so far, then streams the rest."""
        turn = app.state.turns.get(thread_id)
        if turn is None:
            return Response(status_code=204)
        return StreamingResponse(
            with_keepalive(turn.subscribe()), media_type="text/event-stream", headers=SSE_HEADERS
        )

    @app.post("/api/threads/{thread_id}/cancel", status_code=204)
    async def cancel_turn(thread_id: str):
        if not app.state.turns.cancel(thread_id):
            raise HTTPException(status_code=404, detail="Nothing is running in this conversation")

    @app.post("/api/execute", response_model=ExecuteResponse)
    def execute(request: ExecuteRequest):
        # Sync endpoint: FastAPI runs it in a worker thread, off the event loop.
        try:
            result = execute_query(
                request.sql,
                app.state.catalog,
                settings.resolved_database_path,
                max_rows=settings.max_result_rows,
                timeout_seconds=settings.query_timeout_seconds,
            )
        except QueryRejectedError as e:
            raise HTTPException(status_code=400, detail={"errors": e.errors}) from e
        except QueryTimeoutError as e:
            raise HTTPException(status_code=408, detail={"errors": [str(e)]}) from e
        return ExecuteResponse(
            columns=result.columns,
            rows=result.rows,
            row_count=len(result.rows),
            truncated=result.truncated,
            elapsed_ms=result.elapsed_ms,
            warnings=result.warnings,
        )

    @app.get("/api/schema")
    async def schema():
        return {
            "tables": [
                {
                    "name": t.name,
                    "columns": [
                        {"name": c.name, "type": c.type, "primary_key": c.primary_key, "not_null": c.not_null}
                        for c in t.columns
                    ],
                    "foreign_keys": [
                        {"column": f.column, "ref_table": f.ref_table, "ref_column": f.ref_column}
                        for f in t.foreign_keys
                    ],
                    "indexes": [{"name": i.name, "columns": list(i.columns)} for i in t.indexes],
                }
                for t in app.state.catalog.tables
            ]
        }

    @app.get("/api/threads", response_model=list[ThreadSummary])
    async def list_threads():
        running = app.state.turns.running()
        return [{**t, "running": t["id"] in running} for t in await app.state.threads.list()]

    @app.get("/api/threads/{thread_id}", response_model=ThreadDetail)
    async def get_thread(thread_id: str):
        thread = await _require_thread(thread_id)
        messages: list[ThreadMessage] = []
        if app.state.graph is not None:
            state = await app.state.graph.aget_state({"configurable": {"thread_id": thread_id}})
            for m in state.values.get("messages", []):
                if m.type == "human":
                    messages.append(ThreadMessage(role="user", content=m.text))
                elif m.type == "ai":
                    messages.append(ThreadMessage(
                        role="assistant", content=m.text, response=m.additional_kwargs.get("response")
                    ))
        running = app.state.turns.get(thread_id) is not None
        return ThreadDetail(**thread, running=running, messages=messages)

    @app.delete("/api/threads/{thread_id}", status_code=204)
    async def delete_thread(thread_id: str):
        await _require_thread(thread_id)
        app.state.turns.cancel(thread_id)
        await app.state.threads.delete(thread_id)
        if app.state.graph is not None:
            await app.state.graph.checkpointer.adelete_thread(thread_id)

    async def _require_thread(thread_id: str) -> dict:
        thread = await app.state.threads.get(thread_id) if re.match(THREAD_ID_PATTERN, thread_id) else None
        if thread is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return thread

    # In production the built React app is served from the same origin.
    if FRONTEND_DIST.exists():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")

    return app


def _password_matches(request: Request, password: str) -> bool:
    scheme, _, encoded = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "basic":
        return False
    try:
        _, _, given = base64.b64decode(encoded).decode("utf-8").partition(":")
    except (binascii.Error, UnicodeDecodeError):
        return False
    return secrets.compare_digest(given.encode(), password.encode())


app = create_app()
