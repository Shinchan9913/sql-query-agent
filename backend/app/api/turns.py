"""Background chat turns, decoupled from the HTTP connection.

A turn keeps running if the client disconnects (e.g. the user switches
conversation). Its events are buffered so a client can re-attach and replay
progress from the start. Once the turn finishes, its result is in the
checkpointer and the turn is dropped.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable

logger = logging.getLogger(__name__)


class TurnInProgressError(Exception):
    pass


class Turn:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.done = False
        self.task: asyncio.Task | None = None
        self._changed = asyncio.Condition()

    async def publish(self, event: str) -> None:
        async with self._changed:
            self.events.append(event)
            self._changed.notify_all()

    async def finish(self) -> None:
        async with self._changed:
            self.done = True
            self._changed.notify_all()

    async def subscribe(self) -> AsyncIterator[str]:
        """Yield every event from the start, then new ones until the turn ends."""
        sent = 0
        while True:
            async with self._changed:
                await self._changed.wait_for(lambda: len(self.events) > sent or self.done)
                batch, done = self.events[sent:], self.done
            sent += len(batch)
            for event in batch:
                yield event
            if done and sent == len(self.events):
                return


class TurnManager:
    def __init__(self) -> None:
        self._turns: dict[str, Turn] = {}

    def get(self, thread_id: str) -> Turn | None:
        return self._turns.get(thread_id)

    def running(self) -> set[str]:
        return set(self._turns)

    def start(
        self,
        thread_id: str,
        events: AsyncIterator[str],
        on_cancel: Callable[[], Awaitable[str]],
    ) -> Turn:
        """Run `events` in the background. `on_cancel` records the stop and returns an event to publish."""
        if thread_id in self._turns:
            raise TurnInProgressError(thread_id)
        turn = Turn()
        self._turns[thread_id] = turn

        async def run() -> None:
            try:
                async for event in events:
                    await turn.publish(event)
            except asyncio.CancelledError:
                await turn.publish(await on_cancel())
            except Exception:  # chat_events handles its own errors; this is a last resort
                logger.exception("Turn for thread %s crashed", thread_id)
            finally:
                self._turns.pop(thread_id, None)
                await turn.finish()

        turn.task = asyncio.create_task(run())
        return turn

    def cancel(self, thread_id: str) -> bool:
        turn = self._turns.get(thread_id)
        if turn is None or turn.task is None:
            return False
        turn.task.cancel()
        return True

    async def shutdown(self) -> None:
        tasks = [t.task for t in self._turns.values() if t.task]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
