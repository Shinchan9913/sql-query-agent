"""Conversation list. Message contents live in the LangGraph checkpointer;
this table only records which threads exist, for the history sidebar."""

from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

_TITLE_LENGTH = 60


class ThreadStore:
    def __init__(self, path: Path):
        self.path = path

    async def init(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "CREATE TABLE IF NOT EXISTS threads ("
                " id TEXT PRIMARY KEY, title TEXT NOT NULL,"
                " created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            await db.commit()

    async def touch(self, thread_id: str, first_message: str) -> None:
        """Create the thread (titled after its first message) or bump its timestamp."""
        now = datetime.now(UTC).isoformat(timespec="seconds")
        title = " ".join(first_message.split())
        if len(title) > _TITLE_LENGTH:
            title = title[: _TITLE_LENGTH - 1].rstrip() + "…"
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO threads (id, title, created_at, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET updated_at = excluded.updated_at",
                (thread_id, title or "New conversation", now, now),
            )
            await db.commit()

    async def list(self, limit: int = 50) -> list[dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                "SELECT * FROM threads ORDER BY updated_at DESC LIMIT ?", (limit,)
            )
            return [dict(r) for r in rows]

    async def get(self, thread_id: str) -> dict | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall("SELECT * FROM threads WHERE id = ?", (thread_id,))
            return dict(rows[0]) if rows else None

    async def delete(self, thread_id: str) -> bool:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("DELETE FROM threads WHERE id = ?", (thread_id,))
            await db.commit()
            return cursor.rowcount > 0
